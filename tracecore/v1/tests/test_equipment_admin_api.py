"""RPC tracecore.v1.equipment_admin.* (FEAT-038 Task 5): ngừng sử dụng thiết bị và sao chép chương trình từ Desk.

Quyền R10/R02/System Manager kiểm trước mọi thao tác ghi; từ chối nghiệp vụ trả body chuẩn + Audit Log `Reject`.
"""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.equipment.status import set_status
from tracecore.equipment.tests.test_norms import consumable, make_type_norm
from tracecore.tests.factories import make_equipment, make_program, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import equipment_admin as admin_api

test_ignore = ["Asset", "Item", "User"]


def now_ts():
	return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def call(fn, key=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4())}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def as_user(roles, fn, **kwargs):
	email = make_user(
		f"eq-admin-{'-'.join(r.lower().replace(' ', '') for r in roles) or 'none'}@example.com", roles
	)
	frappe.set_user(email)
	try:
		return call(fn, **kwargs)
	finally:
		frappe.set_user("Administrator")


def rejects(code):
	return frappe.db.count("Audit Log", {"action": "Reject", "reason": code})


class TestRetireRpc(IsolatedTestCase):
	@bru("BRU-EQP-003")
	def test_retire_allowed_roles(self):
		for index, roles in enumerate((["TC R10"], ["TC R02"], ["System Manager"])):
			equipment = make_equipment(name=f"Máy {index}", serial=f"SN-RET-{index}")
			result = as_user(roles, admin_api.retire, equipment=equipment.name, reason=" Hết khấu hao ")
			self.assertTrue(result["ok"], roles)
			self.assertEqual(result["equipment"]["name"], equipment.name)
			self.assertEqual(result["equipment"]["status"], "Retired")
			self.assertEqual(result["equipment"]["retired_reason"], "Hết khấu hao")
			self.assertEqual(frappe.db.get_value("Equipment", equipment.name, "status"), "Retired")
			self.assertIsNone(http_status())

	def test_retire_writes_audit_update(self):
		equipment = make_equipment(name="Máy audit", serial="SN-RET-AUD")
		call(admin_api.retire, equipment=equipment.name, reason="Hỏng nặng")
		rows = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Equipment", "ref_name": equipment.name, "action": "Update"},
			fields=["new_value"],
		)
		self.assertTrue(any("Retired" in (row.new_value or "") for row in rows))

	def test_retire_role_checked_before_any_write(self):
		equipment = make_equipment(name="Máy R04", serial="SN-RET-R04")
		keys = frappe.db.count("Idempotency Key")
		audit_rows = frappe.db.count("Audit Log")
		with self.assertRaises(frappe.PermissionError):
			as_user(["TC R04"], admin_api.retire, equipment=equipment.name, reason="Thử")
		self.assertEqual(frappe.db.get_value("Equipment", equipment.name, "status"), "Ready")
		self.assertEqual(frappe.db.count("Idempotency Key"), keys)
		self.assertEqual(frappe.db.count("Audit Log"), audit_rows)

	@bru("BRU-EQP-003")
	def test_retire_requires_reason(self):
		equipment = make_equipment(name="Máy lý do", serial="SN-RET-REASON")
		before = rejects("REASON_REQUIRED")
		for reason in ("", "   ", None):
			result = call(admin_api.retire, equipment=equipment.name, reason=reason)
			self.assertFalse(result["ok"])
			self.assertEqual(result["error"]["code"], "REASON_REQUIRED")
			self.assertTrue(
				result["error"]["title"] and result["error"]["reason"] and result["error"]["action"]
			)
			self.assertEqual(http_status(), 422)
		self.assertEqual(rejects("REASON_REQUIRED"), before + 3)
		self.assertEqual(frappe.db.get_value("Equipment", equipment.name, "status"), "Ready")

	def test_retire_only_from_ready(self):
		before = rejects("EQUIPMENT_NOT_RETIRABLE")
		retired = make_equipment(name="Máy đã ngừng", serial="SN-RET-DONE")
		set_status(retired.name, "Retired", "Cũ")
		locked = make_equipment(name="Máy khóa", serial="SN-RET-LOCK")
		set_status(locked.name, "Locked")
		repair = make_equipment(name="Máy sửa", serial="SN-RET-REP")
		set_status(repair.name, "Repair")
		for equipment, status in ((retired, "Retired"), (locked, "Locked"), (repair, "Repair")):
			result = call(admin_api.retire, equipment=equipment.name, reason="Thử")
			self.assertFalse(result["ok"])
			self.assertEqual(result["error"]["code"], "EQUIPMENT_NOT_RETIRABLE")
			self.assertEqual(http_status(), 409)
			self.assertEqual(frappe.db.get_value("Equipment", equipment.name, "status"), status)
		self.assertEqual(rejects("EQUIPMENT_NOT_RETIRABLE"), before + 3)

	def test_retire_unknown_equipment(self):
		result = call(admin_api.retire, equipment="TB-9999", reason="Thử")
		self.assertEqual(result["error"]["code"], "EQUIPMENT_NOT_FOUND")
		self.assertEqual(http_status(), 404)

	def test_retire_replay_same_key_returns_stored_response(self):
		equipment = make_equipment(name="Máy lặp", serial="SN-RET-REPLAY")
		key = str(uuid.uuid4())
		ts = now_ts()
		first = call(admin_api.retire, key=key, equipment=equipment.name, reason="Cũ", client_ts=ts)
		audit_rows = frappe.db.count("Audit Log")
		second = call(admin_api.retire, key=key, equipment=equipment.name, reason="Cũ", client_ts=ts)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Audit Log"), audit_rows)
		# khóa mới trên máy đã ngừng: từ chối rõ ràng, không lỗi hệ thống
		third = call(admin_api.retire, equipment=equipment.name, reason="Cũ")
		self.assertEqual(third["error"]["code"], "EQUIPMENT_NOT_RETIRABLE")

	def test_retire_is_whitelisted_post_only(self):
		self.assertIn(admin_api.retire, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[admin_api.retire], ["POST"])
		self.assertEqual(frappe.get_attr("tracecore.v1.equipment_admin.retire"), admin_api.retire)


class TestCopyProgramRpc(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.source_eq = make_equipment(name="Máy nguồn", serial="SN-CP-S")
		self.target_eq = make_equipment(name="Máy đích", serial="SN-CP-T")
		self.source = make_program(self.source_eq.name, code="CP-SRC", temperature=134)

	@bru("BRU-EQP-003")
	def test_copy_success_for_each_allowed_role(self):
		for index, roles in enumerate((["TC R10"], ["TC R02"], ["System Manager"])):
			result = as_user(
				roles,
				admin_api.copy_program,
				program=self.source.name,
				equipment=self.target_eq.name,
				new_code=f"cp-new-{index}",
			)
			self.assertEqual(result, {"ok": True, "program": f"CP-NEW-{index}"}, roles)
			copy = frappe.get_doc("Process Program", result["program"])
			self.assertEqual((copy.equipment, copy.temperature), (self.target_eq.name, 134))

	def test_copy_role_checked_first(self):
		keys = frappe.db.count("Idempotency Key")
		with self.assertRaises(frappe.PermissionError):
			as_user(
				["TC R04"],
				admin_api.copy_program,
				program=self.source.name,
				equipment=self.target_eq.name,
				new_code="CP-R04",
			)
		self.assertFalse(frappe.db.exists("Process Program", "CP-R04"))
		self.assertEqual(frappe.db.count("Idempotency Key"), keys)

	def test_copy_model_mismatch(self):
		other = make_equipment(name="Máy khác model", serial="SN-CP-O", model="TM-2")
		before = rejects("PROGRAM_MODEL_MISMATCH")
		result = call(
			admin_api.copy_program, program=self.source.name, equipment=other.name, new_code="CP-MM"
		)
		self.assertEqual(result["error"]["code"], "PROGRAM_MODEL_MISMATCH")
		self.assertTrue(result["error"]["title"] and result["error"]["reason"] and result["error"]["action"])
		self.assertEqual(http_status(), 422)
		self.assertEqual(rejects("PROGRAM_MODEL_MISMATCH"), before + 1)
		self.assertFalse(frappe.db.exists("Process Program", "CP-MM"))

	def test_copy_to_retired_target(self):
		set_status(self.target_eq.name, "Retired", "Cũ")
		result = call(
			admin_api.copy_program, program=self.source.name, equipment=self.target_eq.name, new_code="CP-RT"
		)
		self.assertEqual(result["error"]["code"], "EQUIPMENT_RETIRED")
		self.assertEqual(http_status(), 409)

	def test_copy_duplicate_code(self):
		make_program(self.target_eq.name, code="CP-DUP")
		result = call(
			admin_api.copy_program, program=self.source.name, equipment=self.target_eq.name, new_code="cp-dup"
		)
		self.assertEqual(result["error"]["code"], "PROGRAM_CODE_EXISTS")
		self.assertEqual(http_status(), 409)

	def test_copy_other_domain_errors_fall_back_to_generic_422(self):
		# cùng máy và mã sai định dạng: lỗi miền không có mã riêng, vẫn là body chuẩn mang thông báo đã dịch
		same = call(
			admin_api.copy_program, program=self.source.name, equipment=self.source_eq.name, new_code="CP-X"
		)
		self.assertEqual(same["error"]["code"], "PROGRAM_COPY_INVALID")
		self.assertEqual(http_status(), 422)
		self.assertIn(self.source.name, same["error"]["reason"])
		bad = call(
			admin_api.copy_program, program=self.source.name, equipment=self.target_eq.name, new_code="cp x!"
		)
		self.assertEqual(bad["error"]["code"], "PROGRAM_COPY_INVALID")
		self.assertEqual(http_status(), 422)

	def test_copy_is_whitelisted_post_only(self):
		self.assertIn(admin_api.copy_program, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[admin_api.copy_program], ["POST"])

	@bru("BRU-EQP-003")
	def test_copy_default_norms_flag_only_kept_for_r10_and_system_manager(self):
		make_type_norm()
		source = make_program(
			self.source_eq.name,
			code="CP-DEF",
			minutes=0,
			consumables=consumable("CP-CI-A"),
			use_default_norms=1,
		)
		self.assertEqual((source.use_default_norms, source.norm_status), (1, "Default"))
		for index, roles in enumerate((["TC R10"], ["System Manager"])):
			result = as_user(
				roles,
				admin_api.copy_program,
				program=source.name,
				equipment=self.target_eq.name,
				new_code=f"cp-keep-{index}",
			)
			copy = frappe.get_doc("Process Program", result["program"])
			self.assertEqual(copy.use_default_norms, 1, roles)

	@bru("BRU-EQP-003")
	def test_copy_by_r02_resets_default_norms_flag(self):
		make_type_norm()
		source = make_program(
			self.source_eq.name,
			code="CP-DEF2",
			minutes=0,
			consumables=consumable("CP-CI-B"),
			use_default_norms=1,
		)
		result = as_user(
			["TC R02"],
			admin_api.copy_program,
			program=source.name,
			equipment=self.target_eq.name,
			new_code="cp-r02",
		)
		copy = frappe.get_doc("Process Program", result["program"])
		# cờ bị bỏ: định mức của bản sao theo dữ liệu của chính nó (định mức mặc định đã điền vào bản nguồn nên đủ)
		self.assertEqual((copy.use_default_norms, copy.norm_status), (0, "Complete"))
