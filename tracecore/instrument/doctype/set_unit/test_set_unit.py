import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry, gs1
from tracecore.tests.factories import make_set_type, make_set_unit
from tracecore.tests.utils import bru

# Department (ERPNext) kéo theo test record Company → Warehouse, cần ERPNext đã chạy Setup Wizard;
# test Set Unit không dùng department nên bỏ phụ thuộc này (site CI mới chưa có wizard).
test_ignore = ["Department"]


def _audit_rows(set_unit, action):
	return frappe.get_all(
		"Audit Log",
		filters={"ref_doctype": "Set Unit", "ref_name": set_unit, "action": action},
		fields=["old_value", "new_value"],
	)


class TestSetUnit(FrappeTestCase):
	@bru("BRU-ID-001")
	def test_set_id_is_generated_giai(self):
		su = make_set_unit(set_type=make_set_type("SUT").name)
		self.assertEqual(su.name, su.set_id)
		self.assertTrue(su.name.startswith(code_registry.company_prefix() + "SUT"))
		self.assertEqual(gs1.parse_scan(su.name), {"type": "set", "id": su.name, "raw": su.name})
		self.assertEqual(su.status, "New")
		self.assertEqual(su.cycles_used, 0)

	@bru("BRU-ID-001")
	def test_user_supplied_name_ignored(self):
		su = frappe.get_doc(
			{
				"doctype": "Set Unit",
				"name": "MY-OWN-ID",
				"set_id": "MY-OWN-ID",
				"set_type": make_set_type("SUT").name,
				"max_cycles": 100,
			}
		).insert()
		self.assertNotEqual(su.name, "MY-OWN-ID")
		self.assertEqual(su.set_id, su.name)

	@bru("BRU-ID-001")
	def test_user_supplied_name_ignored_during_import(self):
		frappe.flags.in_import = True
		try:
			su = frappe.get_doc(
				{
					"doctype": "Set Unit",
					"name": "MY-IMPORT-ID",
					"set_type": make_set_type("SUT").name,
					"max_cycles": 100,
				}
			).insert()
		finally:
			frappe.flags.in_import = False
		self.assertNotEqual(su.name, "MY-IMPORT-ID")

	@bru("BRU-ID-001")
	def test_set_id_cannot_be_changed(self):
		su = make_set_unit()
		su.set_id = code_registry.company_prefix() + "SUT999999"
		with self.assertRaises(frappe.ValidationError):
			su.save()

	@bru("BRU-ID-006")
	def test_set_id_registered_in_code_registry(self):
		su = make_set_unit()
		self.assertEqual(
			frappe.db.get_value("Code Registry", su.name, ["ref_doctype", "ref_name"]), ("Set Unit", su.name)
		)

	def test_max_cycles_must_be_positive(self):
		with self.assertRaises(frappe.ValidationError):
			make_set_unit(max_cycles=0)

	def test_create_and_update_write_audit_log(self):
		su = make_set_unit(max_cycles=300)
		created = _audit_rows(su.name, "Create")
		self.assertEqual(len(created), 1)
		self.assertEqual(frappe.parse_json(created[0].new_value)["set_type"], su.set_type)

		su.max_cycles = 250
		su.save()
		updated = _audit_rows(su.name, "Update")
		self.assertEqual(len(updated), 1)
		self.assertEqual(frappe.parse_json(updated[0].old_value), {"max_cycles": 300})
		self.assertEqual(frappe.parse_json(updated[0].new_value), {"max_cycles": 250})

	def test_save_without_changes_writes_no_update(self):
		su = make_set_unit()
		su.save()
		self.assertEqual(_audit_rows(su.name, "Update"), [])

	def test_delete_blocked(self):
		su = make_set_unit()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Set Unit", su.name)
		self.assertTrue(frappe.db.exists("Set Unit", su.name))
