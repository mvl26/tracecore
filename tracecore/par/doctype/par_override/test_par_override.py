"""DocType Par Override (DT-OVERRIDE, WF-08, FEAT-032): đặt tên, quyền theo ma trận, Audit Log, bất biến."""

import re

import frappe
from frappe.utils import today

from tracecore.par import override
from tracecore.par.tests.test_override import OverrideCase, exceeded_set
from tracecore.tests.factories import make_user
from tracecore.tests.utils import assert_permission_matrix, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestParOverride(OverrideCase):
	def test_naming_series(self):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Cần").name
		self.assertRegex(name, rf"^GD-{today()[:4]}-\d{{5}}$")

	@bru("BRU-PAR-004")
	def test_permissions_match_matrix(self):
		assert_permission_matrix(self, "Par Override")

	def test_roles_effective_rights(self):
		unit, _codes = exceeded_set()
		doc = override.request(unit, "Cần")
		rights = {
			"TC R01": {"read": 1, "write": 1, "submit": 1, "cancel": 1},
			"TC R02": {"read": 1, "write": 1, "submit": 1, "cancel": 0},
			"TC R04": {"read": 1, "write": 0, "submit": 0, "cancel": 0},
			"TC R03": {"read": 0, "write": 0, "submit": 0, "cancel": 0},
		}
		for role, expected in rights.items():
			frappe.set_user(make_user(f"par-doc-{role[-3:].lower()}@test.local", roles=(role,)))
			try:
				for right, allowed in expected.items():
					self.assertEqual(
						int(bool(frappe.has_permission("Par Override", right, doc=doc))),
						allowed,
						msg=(role, right),
					)
			finally:
				frappe.set_user("Administrator")

	def test_create_and_decision_are_audited_with_reason(self):
		unit, _codes = exceeded_set()
		doc = override.request(unit, "Cần")
		created = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Par Override", "ref_name": doc.name, "action": "Create"},
			pluck="name",
		)
		self.assertEqual(len(created), 1)
		self.approve(doc.name, reason="Đồng ý ghi đè")
		actions = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Par Override", "ref_name": doc.name},
			fields=["action", "reason", "user"],
			order_by="creation asc, name asc",
		)
		self.assertIn("Submit", [row.action for row in actions])
		self.assertTrue(any(row.reason == "Đồng ý ghi đè" and row.user == self.approver for row in actions))

	def test_requested_fields_cannot_be_edited_by_hand(self):
		unit, _codes = exceeded_set()
		doc = override.request(unit, "Cần")
		doc.reload()
		doc.extra_cycles = 5
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.reason = "Đổi lý do"  # set_only_once
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_settings_delegate_is_a_user_link(self):
		field = frappe.get_meta("TraceCore Settings").get_field("par_override_delegate")
		self.assertEqual((field.fieldtype, field.options), ("Link", "User"))
		self.assertTrue(re.search("R01", field.description))
