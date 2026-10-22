import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import step_gate
from tracecore.tests.factories import make_set_unit, make_user

# recorded_by → User → Email Account → Company (ERPNext) cần Setup Wizard; test tự tạo user qua factory.
test_ignore = ["User"]

WRITE_PTYPES = ("create", "write", "delete", "submit", "cancel", "amend")


class TestStepGateResult(FrappeTestCase):
	def test_name_is_set_unit_cycle_and_step(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		name = step_gate.record(su, "T4", "Pass")
		self.assertEqual(name, f"{su}-C1-T4")
		doc = frappe.get_doc("Step Gate Result", name)
		self.assertEqual((doc.set_unit, doc.cycle_no, doc.step), (su, 1, "T4"))

	def test_same_key_cannot_be_inserted_twice(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		step_gate.record(su, "T4", "Pass")
		duplicate = frappe.get_doc(
			{"doctype": "Step Gate Result", "set_unit": su, "cycle_no": 1, "step": "T4", "result": "Pass"}
		)
		with self.assertRaises(frappe.DuplicateEntryError):
			duplicate.insert(ignore_permissions=True)

	def test_no_role_can_write_or_delete(self):
		perms = frappe.get_all(
			"DocPerm", filters={"parent": "Step Gate Result"}, fields=["role", "read", *WRITE_PTYPES]
		)
		self.assertTrue(perms)
		for perm in perms:
			for ptype in WRITE_PTYPES:
				self.assertFalse(perm[ptype], msg=f"{perm.role} has {ptype}")
		self.assertEqual({p.role for p in perms if p.read}, {"System Manager", "TC R01", "TC R02"})

	def test_only_manager_r01_r02_can_read(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		name = step_gate.record(su, "T4", "Pass")
		for role, can_read in (
			("System Manager", True),
			("TC R01", True),
			("TC R02", True),
			("TC R04", False),
			("TC R10", False),
		):
			user = make_user(f"sgr-{role.lower().replace(' ', '-')}@example.com", roles=[role])
			self.assertEqual(
				bool(frappe.has_permission("Step Gate Result", "read", doc=name, user=user)), can_read, role
			)
			self.assertFalse(frappe.has_permission("Step Gate Result", "write", doc=name, user=user), role)
			self.assertFalse(frappe.has_permission("Step Gate Result", "delete", doc=name, user=user), role)

	def test_cannot_be_deleted_even_by_administrator(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		name = step_gate.record(su, "T4", "Pass")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Step Gate Result", name, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Step Gate Result", name))
