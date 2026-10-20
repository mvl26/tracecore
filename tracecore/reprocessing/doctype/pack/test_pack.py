import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
from frappe.utils import add_days, today

from tracecore.tests.factories import (
	make_bom,
	make_instrument,
	make_pack,
	make_pack_type,
	make_set_type,
	make_set_unit,
	make_user,
	next_free_test_cycle_id,
)
from tracecore.tests.utils import IsolatedTestCase

# Pack liên kết Item, Batch, Department, User, Employee (trực tiếp hoặc qua bảng con) của ERPNext/HRMS;
# site CI mới chưa chạy Setup Wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

# WF-02 (D12): đúng thứ tự này
PACK_STATUSES = [
	"Packed",
	"In Load",
	"Quarantine",
	"Released",
	"In Sterile Stock",
	"Issued",
	"Used",
	"Recalled",
	"Void",
]
VOID_REASONS = ["Used", "Expired", "Torn", "Load Failed", "Returned Unused", "Label Damaged"]
ALLOW_ON_SUBMIT = {"status", "void_reason", "void_note", "label_print_count"}


def _set_unit(code="PKT"):
	return make_set_unit(make_set_type(code).name)


class TestPack(IsolatedTestCase):
	def test_pack_status_options_wf02(self):
		field = frappe.get_meta("Pack").get_field("status")
		self.assertEqual(field.options.split("\n"), PACK_STATUSES)
		self.assertEqual(field.default, "Packed")

	def test_void_reason_options(self):
		field = frappe.get_meta("Pack").get_field("void_reason")
		self.assertEqual(field.options.split("\n"), ["", *VOID_REASONS])

	def test_pack_is_submittable_and_only_four_fields_change_after_submit(self):
		meta = frappe.get_meta("Pack")
		self.assertTrue(meta.is_submittable)
		editable = {f.fieldname for f in meta.fields if f.allow_on_submit}
		self.assertEqual(editable, ALLOW_ON_SUBMIT)

	def test_pack_structure(self):
		meta = frappe.get_meta("Pack")
		self.assertEqual(meta.module, "Reprocessing")
		expected = {
			"set_unit": ("Link", "Set Unit"),
			"set_type": ("Link", "Instrument Set Type"),
			"department": ("Link", "Department"),
			"assembly": ("Link", "Assembly Record"),
			"pack_type": ("Link", "Item"),
			"packed_by_user": ("Link", "User"),
			"packed_by": ("Link", "Employee"),
			"ci_batch": ("Link", "Batch"),
			"station": ("Link", "Zone Station"),
			"label_type": ("Link", "Item"),
			"method": ("Select", "Steam\nPlasma"),
			"shelf_life_source": ("Select", "Pack Type\nSet Type"),
			"instruments_confirmed": ("Table", "Pack Instrument Confirmed"),
			"maint_done": ("Table", "Pack Maintenance Done"),
		}
		for fieldname, (fieldtype, options) in expected.items():
			field = meta.get_field(fieldname)
			self.assertEqual((field.fieldtype, field.options), (fieldtype, options), msg=fieldname)
		self.assertTrue(meta.get_field("packed_by_user").reqd)
		for fieldname in (
			"cycle_no",
			"bom_version",
			"packed_at",
			"client_ts",
			"expiry",
			"shelf_life_days_applied",
			"gtin",
			"barcode_payload",
			"void_note",
			"label_print_count",
		):
			self.assertIsNotNone(meta.get_field(fieldname), fieldname)
		done = frappe.get_meta("Pack Maintenance Done")
		self.assertEqual(done.get_field("action").options, "Done\nDeferred")
		self.assertEqual(done.get_field("oil_batch").options, "Batch")
		self.assertTrue(frappe.get_meta("Pack Instrument Confirmed").istable)
		self.assertTrue(done.istable)

	def test_pack_is_named_only_by_a_preset_cycle_id(self):
		su = _set_unit()
		cycle_id = next_free_test_cycle_id()
		doc = make_pack(su, cycle_id=cycle_id, submit=False)
		self.assertEqual(doc.name, cycle_id)
		self.assertEqual(frappe.db.get_value("Pack", cycle_id, "docstatus"), 0)
		# không có đường tạo Pack không tên: kể cả truyền sẵn name cũng bị từ chối
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Pack",
					"name": "CY-261020-0001",
					"set_unit": su.name,
					"cycle_no": 1,
					"method": "Steam",
					"pack_type": make_pack_type(),
					"packed_by_user": frappe.session.user,
					"packed_at": frappe.utils.now_datetime(),
					"expiry": add_days(today(), 30),
				}
			).insert()
		self.assertFalse(frappe.db.exists("Pack", "CY-261020-0001"))

	def test_set_type_is_taken_from_the_set_unit(self):
		su = _set_unit()
		other = make_set_type("PKO")
		# set_type luôn suy ra từ Set Unit; giá trị truyền vào không làm lệch được
		doc = make_pack(su, set_type=other.name)
		self.assertEqual(doc.set_type, su.set_type)
		self.assertNotEqual(doc.set_type, other.name)
		self.assertEqual(
			doc.set_name, frappe.db.get_value("Instrument Set Type", su.set_type, "set_type_name")
		)

	def test_pack_cannot_be_deleted(self):
		su = _set_unit()
		draft = make_pack(su, submit=False)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Pack", draft.name, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Pack", draft.name))
		perms = frappe.get_all(
			"DocPerm", filters={"parent": "Pack"}, fields=["role", "delete", "cancel", "amend"]
		)
		self.assertTrue(perms)
		for perm in perms:
			for ptype in ("delete", "cancel", "amend"):
				self.assertFalse(perm[ptype], msg=f"{perm.role} has {ptype}")

	def test_submitted_pack_cannot_be_cancelled(self):
		doc = make_pack(_set_unit())
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()
		self.assertEqual(frappe.db.get_value("Pack", doc.name, "docstatus"), 1)

	def test_business_fields_are_locked_after_submit(self):
		doc = make_pack(_set_unit())
		for fieldname, value in (
			("expiry", add_days(today(), 5)),
			("pack_type", make_pack_type("Tyvek", 180)),
			("shelf_life_days_applied", 7),
			("method", "Plasma"),
			("gtin", "09520000000028"),
		):
			doc.reload()
			doc.set(fieldname, value)
			with self.assertRaises(frappe.UpdateAfterSubmitError, msg=fieldname):
				doc.save()
		doc.reload()
		self.assertEqual(doc.shelf_life_days_applied, 30)

	def test_status_void_fields_and_print_count_can_change_after_submit(self):
		doc = make_pack(_set_unit())
		doc.reload()
		doc.label_print_count = 2
		doc.status = "Void"
		doc.void_reason = "Label Damaged"
		doc.void_note = "Nhãn bị nhòe"
		doc.save()
		row = frappe.db.get_value(
			"Pack",
			doc.name,
			["status", "void_reason", "void_note", "label_print_count", "docstatus"],
			as_dict=True,
		)
		self.assertEqual(
			row,
			{
				"status": "Void",
				"void_reason": "Label Damaged",
				"void_note": "Nhãn bị nhòe",
				"label_print_count": 2,
				"docstatus": 1,
			},
		)

	def test_void_needs_a_reason(self):
		doc = make_pack(_set_unit())
		doc.reload()
		doc.status = "Void"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(frappe.db.get_value("Pack", doc.name, "status"), "Packed")

	def test_status_and_void_reason_reject_unknown_values(self):
		doc = make_pack(_set_unit())
		doc.reload()
		doc.status = "Lost"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.status = "Void"
		doc.void_reason = "Dropped"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_child_tables_are_saved_with_the_pack(self):
		su = _set_unit()
		bom = make_bom(su.set_type, [("KC-01", 2), ("KC-02", 1)])
		oil = make_instrument("KC-03")
		doc = make_pack(
			su,
			instruments_confirmed=[{"instrument": row.instrument, "qty": row.qty} for row in bom],
			maint_done=[
				{"instrument": oil.name, "action": "Deferred", "reason": "Hết dầu", "cycles_at_action": 12}
			],
		)
		doc = frappe.get_doc("Pack", doc.name)
		self.assertEqual(
			[(row.instrument, row.qty) for row in doc.instruments_confirmed], [("KC-01", 2), ("KC-02", 1)]
		)
		row = doc.maint_done[0]
		self.assertEqual(
			(row.instrument, row.action, row.reason, row.cycles_at_action),
			("KC-03", "Deferred", "Hết dầu", 12),
		)

	def test_maintenance_action_must_be_done_or_deferred(self):
		su = _set_unit()
		kc = make_instrument("KC-04")
		with self.assertRaises(frappe.ValidationError):
			make_pack(su, maint_done=[{"instrument": kc.name, "action": "Skipped"}], submit=False)

	def test_packer_is_mandatory(self):
		with self.assertRaises(frappe.MandatoryError):
			make_pack(_set_unit(), packed_by_user=None, submit=False)

	def test_audit_log_records_create_submit_and_void(self):
		doc = make_pack(_set_unit())
		doc.reload()
		doc.status = "Void"
		doc.void_reason = "Torn"
		doc.save()
		actions = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Pack", "ref_name": doc.name},
			fields=["action", "new_value"],
			order_by="creation asc",
		)
		kinds = [row.action for row in actions]
		for expected in ("Create", "Submit", "Update"):
			self.assertIn(expected, kinds)
		update = [row for row in actions if row.action == "Update"][-1]
		self.assertIn("Void", update.new_value)

	def test_station_role_r04_can_create_and_submit_others_only_read(self):
		author = make_user("pack-r04@example.com", roles=["TC R04"])
		for ptype in ("create", "read", "write", "submit"):
			self.assertTrue(frappe.has_permission("Pack", ptype, user=author), ptype)
		for ptype in ("delete", "cancel", "amend"):
			self.assertFalse(frappe.has_permission("Pack", ptype, user=author), ptype)
		for role in ("TC R01", "TC R02", "TC R05"):
			reader = make_user(f"pack-{role[-3:].lower()}@example.com", roles=[role])
			self.assertTrue(frappe.has_permission("Pack", "read", user=reader), role)
			for ptype in ("create", "write", "submit", "delete"):
				self.assertFalse(frappe.has_permission("Pack", ptype, user=reader), f"{role} {ptype}")
		manager = frappe.get_all(
			"DocPerm",
			filters={"parent": "Pack", "role": "System Manager"},
			fields=["create", "write", "submit", "read"],
		)
		self.assertEqual([(p["read"], p["write"], p["create"], p["submit"]) for p in manager], [(1, 1, 1, 1)])

	def test_permission_rows_pass_frappe_validation(self):
		# Cùng kiểm tra mà Customize Form / Role Permission Manager chạy khi lưu DocType: migrate bỏ qua
		# bước này nên một dòng quyền sai (ví dụ submit mà thiếu write) chỉ lộ ra ở lần lưu sau.
		validate_permissions_for_doctype("Pack")
		for perm in frappe.get_all(
			"DocPerm", filters={"parent": "Pack"}, fields=["role", "write", "create", "submit"]
		):
			if perm["submit"] or perm["create"]:
				self.assertTrue(perm["write"], msg=f"{perm['role']} needs write to create/submit")

	def test_r04_user_can_create_submit_and_update_after_submit_but_not_cancel_or_delete(self):
		su = _set_unit("PKR")
		author = make_user("pack-r04-flow@example.com", roles=["TC R04"])
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(author)

		# đi qua đường quyền thật (không ignore_permissions): insert → submit → sửa trường allow_on_submit
		doc = make_pack(su, submit=False)
		self.assertEqual(frappe.db.get_value("Pack", doc.name, "docstatus"), 0)
		doc.submit()
		self.assertEqual(frappe.db.get_value("Pack", doc.name, "docstatus"), 1)
		doc.reload()
		doc.label_print_count = 1
		doc.save()
		self.assertEqual(frappe.db.get_value("Pack", doc.name, "label_print_count"), 1)

		doc.reload()
		with self.assertRaises(frappe.PermissionError):
			doc.cancel()
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("Pack", doc.name)
		self.assertEqual(frappe.db.get_value("Pack", doc.name, "docstatus"), 1)
