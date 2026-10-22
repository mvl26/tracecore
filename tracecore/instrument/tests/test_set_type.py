"""Phần đầu loại bộ (FEAT-015 Task 1; FR-M1-03, FR-M1-03.3, S12, S13, S14; UC-02 bước 1, 4, 6)."""

import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
from frappe.utils import add_days, getdate, nowdate

from tracecore.instrument import set_type as set_type_rules
from tracecore.tests.factories import (
	make_bom,
	make_department,
	make_instrument,
	make_pack_type,
	make_set_type,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase

# Instrument Set Type liên kết Department, Item; Set BOM Item/Instrument liên kết Item, User của ERPNext;
# site CI mới chưa chạy Setup Wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Instrument Set Type"
SEP = set_type_rules.LINE_SEPARATOR


def _set_type_doc(type_code, **values):
	doc = {
		"doctype": DOCTYPE,
		"type_code": type_code,
		"set_type_name": f"Set {type_code}",
		"method": "Steam",
		"department": make_department(),
		"default_pack_type": make_pack_type("Giấy crepe", 30),
	}
	doc.update(values)
	return frappe.get_doc(doc)


def _set_dates(set_type, dates):
	"""Ngày hiệu lực của từng phiên bản BOM: ``{phiên bản: ngày}``."""
	for version, day in dates.items():
		frappe.db.set_value(
			"Set BOM Item", {"set_type": set_type, "bom_version": version}, "effective_from", day
		)


def _audit(name, action):
	return frappe.get_all(
		"Audit Log",
		filters={"ref_doctype": DOCTYPE, "ref_name": name, "action": action},
		fields=["old_value", "new_value"],
		order_by="creation asc",
	)


class TestSetTypeHeader(IsolatedTestCase):
	def test_header_fields_meta(self):
		meta = frappe.get_meta(DOCTYPE)
		for field in ("department", "default_pack_type"):
			self.assertTrue(meta.get_field(field).reqd, msg=field)
		self.assertEqual(meta.get_field("default_pack_type").options, "Item")
		self.assertEqual(meta.get_field("is_implant").fieldtype, "Check")
		self.assertEqual(meta.get_field("assembly_minutes").fieldtype, "Int")
		for field in ("tray_image_2", "tray_image_3"):
			self.assertEqual(meta.get_field(field).fieldtype, "Attach Image", msg=field)
		for field in ("tray_thumbnail", "tray_thumbnail_2", "tray_thumbnail_3"):
			df = meta.get_field(field)
			self.assertEqual(df.fieldtype, "Attach Image", msg=field)
			self.assertTrue(df.read_only and df.hidden, msg=field)
		self.assertTrue(meta.get_field("current_bom_version").read_only)

	def test_required_header_fields_listed(self):
		frappe.clear_messages()
		doc = _set_type_doc("RQH", department=None, default_pack_type=None)
		with self.assertRaises(frappe.MandatoryError) as raised:
			doc.insert()
		self.assertIn("department", str(raised.exception))
		self.assertIn("default_pack_type", str(raised.exception))
		messages = " ".join(str(message) for message in frappe.local.message_log)
		self.assertIn("Department", messages)
		self.assertIn("Default Pack Type", messages)
		self.assertFalse(frappe.db.exists(DOCTYPE, "RQH"))

	def test_implant_flag_and_assembly_minutes_stored(self):
		implant = _set_type_doc("IMP1", is_implant=1, assembly_minutes=600).insert()
		self.assertEqual(
			frappe.db.get_value(DOCTYPE, implant.name, ["is_implant", "assembly_minutes"]), (1, 600)
		)
		plain = _set_type_doc("IMP0").insert()
		self.assertEqual(frappe.db.get_value(DOCTYPE, plain.name, ["is_implant", "assembly_minutes"]), (0, 0))
		for index, minutes in enumerate((601, -1)):
			with self.assertRaises(frappe.ValidationError, msg=minutes):
				_set_type_doc(f"IMB{index}", assembly_minutes=minutes).insert()
			self.assertFalse(frappe.db.exists(DOCTYPE, f"IMB{index}"))
		plain.assembly_minutes = 601
		with self.assertRaises(frappe.ValidationError):
			plain.save()

	def test_current_bom_version_not_editable_by_hand(self):
		doc = make_set_type("CBV")
		doc.current_bom_version = 2
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(frappe.db.get_value(DOCTYPE, "CBV", "current_bom_version"), 1)

		with self.assertRaises(frappe.ValidationError):
			_set_type_doc("CBVN", current_bom_version=3).insert()

		# dịch vụ BOM (Task 2) đặt cờ flags.tc_bom mới được ghi
		doc = frappe.get_doc(DOCTYPE, "CBV")
		doc.current_bom_version = 2
		doc.flags.tc_bom = True
		doc.save()
		self.assertEqual(frappe.db.get_value(DOCTYPE, "CBV", "current_bom_version"), 2)

	def test_method_change_rechecks_effective_and_scheduled_bom(self):
		# FR-M1-03.3, Review Focus 4: đổi phương pháp kiểm lại phiên bản hiệu lực + đã lên lịch, liệt kê từng dòng
		today = getdate(nowdate())
		make_instrument("MC-BOTH", name="Both methods", methods=("Steam 134", "Plasma"))
		make_instrument("MC-S134", name="Steam only", methods=("Steam 134",))
		make_instrument("MC-OLD", name="Old steam only", methods=("Steam 134",))
		make_instrument("MC-S121", name="Steam 121 only", methods=("Steam 121",))
		set_type = make_set_type("MCH")
		make_bom(set_type, [("MC-OLD", 1), ("MC-BOTH", 1)], version=1)
		make_bom(set_type, [("MC-BOTH", 2), ("MC-S134", 1)], version=2)
		make_bom(set_type, [("MC-S121", 1), ("MC-BOTH", 1)], version=3)
		_set_dates(set_type.name, {1: add_days(today, -10), 2: today, 3: add_days(today, 1)})

		doc = frappe.get_doc(DOCTYPE, "MCH")
		doc.method = "Plasma"
		with self.assertRaises(frappe.ValidationError) as raised:
			doc.save()
		message = str(raised.exception)
		self.assertIn(SEP.join(("2", "MC-S134", "Steam only", "Steam 134")), message)
		self.assertIn(SEP.join(("1", "MC-S121", "Steam 121 only", "Steam 121")), message)
		self.assertNotIn("MC-OLD", message)  # chỉ ở phiên bản cũ đã thay thế
		self.assertNotIn("MC-BOTH", message)
		self.assertEqual(frappe.db.get_value(DOCTYPE, "MCH", "method"), "Steam")

		# tên và các trường khác vẫn sửa được khi không đổi phương pháp
		doc = frappe.get_doc(DOCTYPE, "MCH")
		doc.set_type_name = "Renamed"
		doc.save()

		# BOM toàn dụng cụ tương thích → đổi được
		ok = make_set_type("MCI", bom=[("MC-BOTH", 1)])
		ok.method = "Plasma"
		ok.save()
		self.assertEqual(frappe.db.get_value(DOCTYPE, "MCI", "method"), "Plasma")

	def test_derived_max_cycles(self):
		# UC-02 bước 6: cơ số bộ suy ra = min cơ số > 0 của dụng cụ trong BOM, kèm dụng cụ Chưa xác định
		today = getdate(nowdate())
		make_instrument("DM-500", max_cycles=500)
		make_instrument("DM-300", max_cycles=300)
		make_instrument("DM-NONE", max_cycles=None)
		set_type = make_set_type("DMC", bom=[("DM-500", 1), ("DM-300", 2), ("DM-NONE", 1)])
		make_bom(set_type, [("DM-NONE", 1)], version=2)
		_set_dates(set_type.name, {1: today, 2: add_days(today, 3)})

		self.assertEqual(
			set_type_rules.derived_max_cycles(set_type.name),
			{"value": 300, "undefined": ["DM-NONE"], "limiting": ["DM-300"]},
		)
		self.assertEqual(
			set_type_rules.derived_max_cycles(set_type.name, 2),
			{"value": None, "undefined": ["DM-NONE"], "limiting": []},
		)
		self.assertEqual(
			set_type_rules.derived_max_cycles(set_type.name, 9),
			{"value": None, "undefined": [], "limiting": []},
		)
		# chỉ đọc: không ghi gì vào loại bộ
		self.assertFalse(_audit(set_type.name, "Update"))

	def test_permissions_match_s12(self):
		validate_permissions_for_doctype(DOCTYPE)
		perms = {row.role: row for row in frappe.get_meta(DOCTYPE).permissions}
		for role in ("System Manager", "TC R02", "TC R10"):
			for right in ("read", "write", "create", "report"):
				self.assertEqual(perms[role].get(right), 1, msg=(role, right))
		self.assertEqual((perms["TC R01"].read, perms["TC R01"].report), (1, 1))
		for role in [f"TC R{n:02d}" for n in (1, 3, 4, 5, 6, 7, 8, 9)]:
			self.assertEqual(perms[role].read, 1, msg=role)
			self.assertFalse(perms[role].write or perms[role].create, msg=role)
		self.assertFalse(any(row.delete for row in perms.values()))

		writer = make_user("settype-r02@example.com", roles=["TC R02"])
		admin = make_user("settype-r10@example.com", roles=["TC R10"])
		reader = make_user("settype-r04@example.com", roles=["TC R04"])
		for user in (writer, admin):
			self.assertTrue(frappe.has_permission(DOCTYPE, "create", user=user), user)
			self.assertTrue(frappe.has_permission(DOCTYPE, "write", user=user), user)
			self.assertFalse(frappe.has_permission(DOCTYPE, "delete", user=user), user)
		self.assertTrue(frappe.has_permission(DOCTYPE, "read", user=reader))
		for ptype in ("create", "write", "delete"):
			self.assertFalse(frappe.has_permission(DOCTYPE, ptype, user=reader), ptype)

		doc = _set_type_doc("PRM10")  # khoa/loại gói tạo trước khi đổi user
		frappe.set_user(admin)
		try:
			doc.insert()
			doc.gtin = "09520000000011"  # R10 ghi được GTIN (A-02 ruling Task 3)
			doc.save()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(DOCTYPE, "PRM10", ["owner", "gtin"]), (admin, "09520000000011"))

	def test_set_type_changes_audited(self):
		doc = make_set_type("AUD", shelf_life_days=0)
		self.assertEqual(len(_audit(doc.name, "Create")), 1)
		doc.shelf_life_days = 20
		doc.method = "Plasma"
		doc.save()
		updates = _audit(doc.name, "Update")
		self.assertEqual(len(updates), 1)
		old, new = frappe.parse_json(updates[0].old_value), frappe.parse_json(updates[0].new_value)
		self.assertEqual((old["shelf_life_days"], new["shelf_life_days"]), (0, 20))
		self.assertEqual((old["method"], new["method"]), ("Steam", "Plasma"))
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(DOCTYPE, doc.name)

	def test_patch_backfills_without_inventing_clinical_data(self):
		from tracecore.patches.v0_1 import set_type_master_defaults

		legacy = make_set_type("LEGST")
		# dòng có từ trước FEAT-015: chưa có khoa, loại gói
		frappe.db.set_value(
			DOCTYPE, legacy.name, {"department": None, "default_pack_type": None}, update_modified=False
		)
		set_type_master_defaults.execute()
		set_type_master_defaults.execute()  # chạy lại không đổi gì thêm
		self.assertEqual(
			frappe.db.get_value(
				DOCTYPE, legacy.name, ["department", "default_pack_type", "is_implant", "assembly_minutes"]
			),
			(None, None, 0, 0),
		)
		self.assertFalse(_audit(legacy.name, "Update"))

		# lưu lại bản ghi cũ sẽ yêu cầu điền khoa và loại gói
		doc = frappe.get_doc(DOCTYPE, legacy.name)
		with self.assertRaises(frappe.MandatoryError):
			doc.save()

	def test_patch_registered_post_model_sync(self):
		with open(frappe.get_app_path("tracecore", "patches.txt"), encoding="utf-8") as handle:
			text = handle.read()
		post = text.split("[post_model_sync]", 1)[1]
		self.assertIn("tracecore.patches.v0_1.set_type_master_defaults", post)
