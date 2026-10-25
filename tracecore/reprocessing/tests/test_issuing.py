"""Cấp phát T7 (FEAT-026, UC-12, FR-M2-15/16): phiếu nhiều gói cho một khoa, người nhận, chữ ký, cơ số khoa."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from tracecore.core import station_auth
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import issuing, storage
from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_par_level,
	make_released_pack,
	make_set_type,
	make_sterile_location,
	make_stocked_pack,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-007"
SIGNATURE = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def blocked(testcase, code, fn, *args, **kwargs):
	"""Gọi `fn` và kiểm nó ném BlockedError mang mã `code`; trả Block."""
	with testcase.assertRaises(BlockedError) as caught:
		fn(*args, **kwargs)
	testcase.assertEqual(caught.exception.block.code, code)
	return caught.exception.block


class IssuingCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.shelf = make_sterile_location("Kệ T7")
		self.dept = make_department("Khoa Ngoại test T7")
		self.set_type = make_set_type("ISS").name
		self.recipient = make_employee(first_name="Điều dưỡng nhận", department=self.dept)

	def stocked(self, expiry_days=30, set_type=None):
		return make_stocked_pack(set_type or self.set_type, expiry_days=expiry_days, location=self.shelf)

	def draft(self):
		return issuing.create(self.dept, STATION)["issue_note"]

	def par(self, min_qty=0, max_qty=10, **values):
		return make_par_level(
			"Instrument Set Type",
			self.set_type,
			par_kind="Department Stock",
			department=self.dept,
			min_qty=min_qty,
			max_qty=max_qty,
			is_active=1,
			**values,
		)

	def ready(self, packs=1):
		"""Phiếu nháp đã có `packs` gói và đã ký bằng thẻ người nhận; trả (tên phiếu, các Pack)."""
		name = self.draft()
		items = [self.stocked() for _ in range(packs)]
		for pack in items:
			issuing.add_pack(name, pack.name, STATION)
		issuing.sign(name, self.recipient.tc_card_id, STATION)
		return name, items


class TestCreate(IssuingCase):
	def test_create_opens_draft_for_department(self):
		view = issuing.create(self.dept, STATION, client_ts=None)
		note = frappe.get_doc("Issue Note", view["issue_note"])
		self.assertEqual((note.docstatus, note.department, note.station), (0, self.dept, STATION))
		self.assertEqual(note.issued_by_user, frappe.session.user)
		self.assertEqual(view["packs"], [])

	def test_create_resumes_own_draft_for_same_department(self):
		first = self.draft()
		self.assertEqual(self.draft(), first)

	def test_unknown_department_is_rejected(self):
		blocked(self, "DEPARTMENT_NOT_FOUND", issuing.create, "Khoa không có", STATION)

	def test_wrong_station_is_rejected(self):
		blocked(self, "STATION_WRONG_STEP", issuing.create, self.dept, "TR-006")

	def test_departments_lists_enabled_departments(self):
		names = [row["name"] for row in issuing.departments()]
		self.assertIn(self.dept, names)


class TestAddPack(IssuingCase):
	@bru("BRU-FLOW-002")
	def test_add_pack_in_sterile_stock(self):
		name = self.draft()
		pack = self.stocked()
		view = issuing.add_pack(name, pack.name, STATION)
		self.assertEqual([row["cycle_id"] for row in view["packs"]], [pack.name])
		row = view["packs"][0]
		self.assertEqual((row["set_id"], row["set_type"]), (pack.set_unit, self.set_type))

	def test_add_pack_accepts_datamatrix_hri(self):
		name = self.draft()
		pack = self.stocked()
		hri = f"(01){pack.gtin}(11){frappe.utils.getdate(pack.packed_at):%y%m%d}(17){frappe.utils.getdate(pack.expiry):%y%m%d}(21){pack.name}"
		self.assertEqual(len(issuing.add_pack(name, hri, STATION)["packs"]), 1)

	def test_scanning_same_pack_twice_keeps_one_row(self):
		name = self.draft()
		pack = self.stocked()
		issuing.add_pack(name, pack.name, STATION)
		view = issuing.add_pack(name, pack.name, STATION)
		self.assertEqual(len(view["packs"]), 1)

	@bru("BRU-FLOW-002")
	def test_add_pack_rejects_pack_not_in_stock(self):
		# FR-M2-00.1: T7 chỉ nhận gói Trong kho vô khuẩn (gói mới giải phóng chưa nhập kho thì không)
		name = self.draft()
		pack = make_released_pack(set_type=self.set_type)
		block = blocked(self, "PACK_NOT_IN_STOCK", issuing.add_pack, name, pack.name, STATION)
		self.assertIn(pack.name, block.reason)

	@bru("BRU-FLOW-002")
	def test_add_pack_rejects_expired(self):
		# UC-12 E1: gói quá hạn (job 00:00 chưa chạy) bị chặn
		name = self.draft()
		pack = self.stocked(expiry_days=-1)
		blocked(self, "PACK_EXPIRED", issuing.add_pack, name, pack.name, STATION)

	def test_add_pack_rejects_other_codes(self):
		name = self.draft()
		blocked(self, "SCAN_INVALID", issuing.add_pack, name, self.shelf.name, STATION)
		blocked(self, "PACK_NOT_FOUND", issuing.add_pack, name, "CY-990101-9999", STATION)

	def test_pack_in_other_draft_is_rejected_until_moved(self):
		pack = self.stocked()
		other = issuing.create(make_department("Khoa khác T7"), STATION)["issue_note"]
		issuing.add_pack(other, pack.name, STATION)
		name = self.draft()
		block = blocked(self, "PACK_IN_OTHER_ISSUE", issuing.add_pack, name, pack.name, STATION)
		self.assertIn(other, block.reason)
		issuing.add_pack(name, pack.name, STATION, move=1)
		self.assertEqual(frappe.get_doc("Issue Note", other).packs, [])
		self.assertEqual(frappe.get_doc("Issue Note", name).packs[0].pack, pack.name)

	def test_fefo_requires_note_for_later_pack(self):
		# FR-M2-13.4, UC-12 A2: còn gói cùng loại hạn gần hơn → phải ghi chú (khoa chỉ định Set ID)
		name = self.draft()
		self.stocked(expiry_days=5)
		later = self.stocked(expiry_days=20)
		block = blocked(self, "FEFO_NOTE_REQUIRED", issuing.add_pack, name, later.name, STATION)
		self.assertTrue(block.items)
		view = issuing.add_pack(name, later.name, STATION, note="PTV chỉ định bộ này")
		self.assertEqual(view["packs"][0]["fefo_note"], "PTV chỉ định bộ này")

	def test_fefo_order_needs_no_note(self):
		# lấy gói hạn sớm trước rồi gói hạn muộn hơn: gói sớm đã nằm trong phiếu nên không còn là "gói gần hơn"
		name = self.draft()
		early = self.stocked(expiry_days=5)
		later = self.stocked(expiry_days=20)
		issuing.add_pack(name, early.name, STATION)
		view = issuing.add_pack(name, later.name, STATION)
		self.assertEqual([row["cycle_id"] for row in view["packs"]], [early.name, later.name])
		self.assertIsNone(view["packs"][1]["fefo_note"])

	def test_wrong_issue_note(self):
		blocked(self, "ISSUE_NOT_FOUND", issuing.add_pack, "IS-1999-00001", "x", STATION)

	def test_remove_pack(self):
		name = self.draft()
		pack = self.stocked()
		issuing.add_pack(name, pack.name, STATION)
		view = issuing.remove_pack(name, pack.name, STATION)
		self.assertEqual(view["packs"], [])

	def test_changing_packs_clears_signature(self):
		# chữ ký thuộc về danh sách gói đã ký: thêm/bỏ gói thì phải ký lại
		name, _packs = self.ready()
		view = issuing.add_pack(name, self.stocked(set_type=make_set_type("IS2").name).name, STATION)
		self.assertFalse(view["signed"])


class TestContext(IssuingCase):
	@bru("BRU-PAR-005")
	def test_context_shows_stock_and_par_per_set_type(self):
		# UC-12 bước 1: chọn khoa → tồn khoa và cơ số theo loại bộ; tồn kho vô khuẩn để biết còn gói cấp
		self.par(min_qty=2, max_qty=4)
		self.stocked()
		row = next(r for r in issuing.context(self.dept)["rows"] if r["set_type"] == self.set_type)
		self.assertEqual((row["stock"], row["min"], row["max"], row["available"]), (0, 2, 4, 1))
		self.assertEqual(row["suggest"], 2)  # FR-M2-16.2: tồn khoa < tối thiểu → gợi ý cấp bổ sung


class TestSign(IssuingCase):
	def test_card_signature_records_recipient(self):
		name = self.draft()
		issuing.add_pack(name, self.stocked().name, STATION)
		view = issuing.sign(name, self.recipient.tc_card_id.lower(), STATION)
		note = frappe.get_doc("Issue Note", name)
		self.assertEqual((note.recipient, note.sign_method), (self.recipient.name, "Card"))
		self.assertTrue(note.signed_at)
		self.assertTrue(view["signed"])

	def test_touch_signature_is_stored(self):
		name = self.draft()
		issuing.add_pack(name, self.stocked().name, STATION)
		issuing.sign(name, self.recipient.tc_card_id, STATION, method="Touch", signature=SIGNATURE)
		note = frappe.get_doc("Issue Note", name)
		self.assertEqual((note.sign_method, note.signature), ("Touch", SIGNATURE))

	def test_touch_signature_must_be_png_image(self):
		name = self.draft()
		issuing.add_pack(name, self.stocked().name, STATION)
		for bad in (None, "", "javascript:alert(1)", "data:image/png;base64," + "A" * 300_000):
			blocked(
				self,
				"SIGNATURE_INVALID",
				issuing.sign,
				name,
				self.recipient.tc_card_id,
				STATION,
				method="Touch",
				signature=bad,
			)

	def test_unknown_or_disabled_card_is_rejected(self):
		name = self.draft()
		issuing.add_pack(name, self.stocked().name, STATION)
		blocked(self, "RECIPIENT_INVALID", issuing.sign, name, "KHONG-CO", STATION)
		frappe.db.set_value("Employee", self.recipient.name, "tc_card_enabled", 0)
		blocked(self, "RECIPIENT_INVALID", issuing.sign, name, self.recipient.tc_card_id, STATION)

	def test_recipient_other_department_needs_reason(self):
		# FR-M2-15.2, UC-12 E2: người nhận không thuộc khoa → cảnh báo, tiếp tục khi có lý do
		name = self.draft()
		issuing.add_pack(name, self.stocked().name, STATION)
		stranger = make_employee(department=make_department("Khoa Nội test T7"))
		blocked(self, "RECIPIENT_DEPT_MISMATCH", issuing.sign, name, stranger.tc_card_id, STATION)
		issuing.sign(name, stranger.tc_card_id, STATION, reason="Điều dưỡng khoa Nội nhận hộ")
		note = frappe.get_doc("Issue Note", name)
		self.assertEqual(note.dept_mismatch_reason, "Điều dưỡng khoa Nội nhận hộ")

	def test_sign_empty_note_is_rejected(self):
		blocked(self, "ISSUE_EMPTY", issuing.sign, self.draft(), self.recipient.tc_card_id, STATION)


class TestSubmit(IssuingCase):
	@bru("BRU-FLOW-003", "BRU-PAR-005")
	def test_submit_issues_packs_and_moves_stock(self):
		# FR-M2-15: Pack → Đã cấp phát, Set Unit → Tại khoa, tồn kho vô khuẩn giảm, tồn khoa tăng
		self.par(min_qty=0, max_qty=5)
		name, packs = self.ready(packs=2)
		before = next(r for r in issuing.context(self.dept)["rows"] if r["set_type"] == self.set_type)
		result = issuing.submit(name, STATION)
		note = frappe.get_doc("Issue Note", name)
		self.assertEqual(note.docstatus, 1)
		self.assertTrue(note.issued_at)
		for pack in packs:
			row = frappe.db.get_value("Pack", pack.name, ["status", "location"], as_dict=True)
			self.assertEqual((row.status, row.location), ("Issued", None))
			unit = frappe.db.get_value("Set Unit", pack.set_unit, ["status", "current_station"], as_dict=True)
			self.assertEqual((unit.status, unit.current_station), ("At Department", STATION))
		after = next(r for r in issuing.context(self.dept)["rows"] if r["set_type"] == self.set_type)
		self.assertEqual((before["stock"], after["stock"]), (0, 2))
		self.assertEqual((before["available"], after["available"]), (2, 0))
		self.assertIn("format=TC+Issue+Note", result["print_url"])
		self.assertIn(name, result["print_url"])
		self.assertEqual(frappe.parse_json(note.par_result)[0]["state"], "ok")

	def test_submit_requires_signature_and_packs(self):
		name = self.draft()
		blocked(self, "ISSUE_EMPTY", issuing.submit, name, STATION)
		issuing.add_pack(name, self.stocked().name, STATION)
		blocked(self, "ISSUE_NOT_SIGNED", issuing.submit, name, STATION)

	def test_submitted_note_is_not_draft(self):
		name, _packs = self.ready()
		issuing.submit(name, STATION)
		blocked(self, "ISSUE_NOT_DRAFT", issuing.add_pack, name, self.stocked().name, STATION)

	@bru("BRU-FLOW-002")
	def test_submit_rechecks_pack_status(self):
		# gói bị báo rách sau khi quét vào phiếu: ghi sổ bị chặn, không gói nào đổi trạng thái
		name, packs = self.ready(packs=2)
		storage.mark_damaged(packs[1].name, "Rách", "TR-006")
		blocked(self, "PACK_NOT_IN_STOCK", issuing.submit, name, STATION)
		self.assertEqual(frappe.db.get_value("Pack", packs[0].name, "status"), "In Sterile Stock")
		self.assertEqual(frappe.db.get_value("Issue Note", name, "docstatus"), 0)

	@bru("BRU-PAR-005")
	def test_over_max_requires_r02_card_pin(self):
		# FR-M2-16.1, UC-12 A1: vượt tối đa → R02 duyệt tại chỗ bằng thẻ + PIN
		self.par(min_qty=0, max_qty=1)
		name, packs = self.ready(packs=2)
		block = blocked(self, "PAR_APPROVAL_REQUIRED", issuing.submit, name, STATION)
		self.assertEqual(block.items, [self.set_type])
		self.assertEqual(frappe.db.get_value("Pack", packs[0].name, "status"), "In Sterile Stock")

		# proof người duyệt do FEAT-019 (station_auth.create/consume_approver_proof, chưa có trên develop): test patch
		# consume_approver_proof; sau khi 019 merge thì bỏ patch và tạo proof thật
		r06 = make_user("khong-phai-r02@example.com", ["TC R06"])
		r02 = make_user("giam-sat-r02@example.com", ["TC R02"])

		def consume(session, proof, role="TC R02"):
			users = {"proof-r06": r06, "proof-r02": r02}
			if session != "SES-1" or proof not in users:
				raise BlockedError(Block("PIN_PROOF_INVALID", "t", "r", "a"))
			return frappe._dict(employee="E", user=users[proof], employee_name="N")

		with patch.object(station_auth, "consume_approver_proof", consume, create=True):
			blocked(self, "PAR_APPROVAL_REQUIRED", issuing.submit, name, STATION, "proof-xxx", "SES-1")
			blocked(self, "PAR_APPROVAL_REQUIRED", issuing.submit, name, STATION, "proof-r06", "SES-1")
			blocked(self, "PAR_APPROVAL_REQUIRED", issuing.submit, name, STATION, "proof-r02", "SES-OTHER")
			issuing.submit(name, STATION, "proof-r02", "SES-1")
		note = frappe.get_doc("Issue Note", name)
		self.assertEqual((note.docstatus, note.approved_by), (1, "giam-sat-r02@example.com"))
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_name": name, "reason": "PAR_OVER_APPROVED"}))

	@bru("BRU-PAR-005")
	def test_emergency_over_within_percent_logs(self):
		# FR-M2-16.3: khoa cấp cứu vượt ≤ 20 % → không cần duyệt, ghi log
		self.par(min_qty=0, max_qty=5, over_percent=20, is_emergency_dept=1)
		name, _packs = self.ready(packs=6)
		issuing.submit(name, STATION)
		self.assertEqual(frappe.db.get_value("Issue Note", name, "docstatus"), 1)
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_name": name, "reason": "PAR_OVER_ALLOWED"}))

	@bru("BRU-PAR-005")
	def test_unconfigured_par_allows_and_logs(self):
		# FR-M2-16.4: khoa chưa có cơ số → cho cấp, cảnh báo, ghi thiếu cấu hình
		name, _packs = self.ready()
		view = issuing.add_pack(name, self.stocked(set_type=make_set_type("IS3").name).name, STATION)
		self.assertTrue(all(row["state"] == "unconfigured" for row in view["par"]))
		issuing.sign(name, self.recipient.tc_card_id, STATION)
		issuing.submit(name, STATION)
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_name": name, "reason": "PAR_UNCONFIGURED"}))

	def test_expired_at_submit_is_blocked(self):
		name, packs = self.ready()
		frappe.db.set_value("Pack", packs[0].name, "expiry", add_days(today(), -1), update_modified=False)
		blocked(self, "PACK_EXPIRED", issuing.submit, name, STATION)
