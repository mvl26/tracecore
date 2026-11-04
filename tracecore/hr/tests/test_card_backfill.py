"""Patch điền mã thẻ = ID nhân viên cho nhân viên cũ chưa có thẻ (FEAT-078, BRU-ID-006)."""

import frappe

from tracecore.patches.v0_1 import fill_employee_card_id
from tracecore.tests.factories import make_employee
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def card_of(name):
	return frappe.db.get_value("Employee", name, "tc_card_id")


class TestCardBackfill(IsolatedTestCase):
	def clear_card(self, employee):
		frappe.db.set_value("Employee", employee.name, "tc_card_id", None, update_modified=False)

	@bru("BRU-ID-006")
	def test_employee_without_card_gets_its_own_id(self):
		employee = make_employee()
		self.clear_card(employee)
		fill_employee_card_id.execute()
		self.assertEqual(card_of(employee.name), employee.name.upper())

	def test_empty_string_card_is_filled_too(self):
		employee = make_employee()
		frappe.db.set_value("Employee", employee.name, "tc_card_id", "", update_modified=False)
		fill_employee_card_id.execute()
		self.assertEqual(card_of(employee.name), employee.name.upper())

	def test_existing_card_is_kept(self):
		employee = make_employee(card="THE-BENH-VIEN-01")
		fill_employee_card_id.execute()
		self.assertEqual(card_of(employee.name), "THE-BENH-VIEN-01")

	def test_card_already_used_by_someone_else_is_skipped(self):
		first, second = make_employee(), make_employee()
		self.clear_card(second)
		frappe.db.set_value("Employee", first.name, "tc_card_id", second.name.upper(), update_modified=False)
		fill_employee_card_id.execute()
		self.assertIsNone(card_of(second.name) or None)
		self.assertEqual(card_of(first.name), second.name.upper())

	def test_patch_is_idempotent(self):
		employee = make_employee()
		self.clear_card(employee)
		fill_employee_card_id.execute()
		fill_employee_card_id.execute()
		self.assertEqual(card_of(employee.name), employee.name.upper())
