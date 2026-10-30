import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import step_gate
from tracecore.setup.permissions import ROLE_CODES, build_custom_docperms
from tracecore.tests.factories import make_set_unit, make_user
from tracecore.tests.utils import assert_permission_matrix

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

	def test_native_rows_are_read_only_and_effective_matrix_matches(self):
		perms = frappe.get_all(
			"DocPerm", filters={"parent": "Step Gate Result"}, fields=["role", "read", *WRITE_PTYPES]
		)
		self.assertTrue(perms)
		assert_permission_matrix(self, "Step Gate Result")
		for perm in perms:
			for ptype in WRITE_PTYPES:
				self.assertFalse(perm[ptype], msg=f"{perm.role} has {ptype}")
		self.assertEqual({p.role for p in perms if p.read}, {"System Manager", "TC R01", "TC R02"})

	def test_generated_step_gate_read_permissions_and_no_delete(self):
		generated = {row["role"]: row for row in build_custom_docperms({"Step Gate Result"})}
		su = make_set_unit().name
		step_gate.start_cycle(su)
		name = step_gate.record(su, "T4", "Pass")
		for code in ROLE_CODES:
			role = f"TC {code}"
			user = make_user(f"sgr-{code.lower()}@example.com", roles=[role])
			self.assertEqual(
				bool(frappe.has_permission("Step Gate Result", "read", doc=name, user=user)),
				bool(generated.get(role, {}).get("read", 0)),
				role,
			)
			self.assertFalse(frappe.has_permission("Step Gate Result", "delete", doc=name, user=user), role)
		manager = make_user("sgr-system-manager@example.com", roles=["System Manager"])
		self.assertFalse(frappe.has_permission("Step Gate Result", "read", doc=name, user=manager))
		self.assertFalse(frappe.has_permission("Step Gate Result", "delete", doc=name, user=manager))

	def test_cannot_be_deleted_even_by_administrator(self):
		su = make_set_unit().name
		step_gate.start_cycle(su)
		name = step_gate.record(su, "T4", "Pass")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Step Gate Result", name, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Step Gate Result", name))
