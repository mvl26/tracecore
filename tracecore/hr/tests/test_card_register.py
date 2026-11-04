"""Thẻ nhân viên riêng (không phải NV-) được ghi sổ mã để in được nhãn QR quét là đăng nhập trạm (FEAT-079, FR-M9-07.4)."""

import frappe

from tracecore.core import code_registry
from tracecore.core import print as core_print
from tracecore.hr import employees
from tracecore.patches.v0_1 import register_employee_cards
from tracecore.tests.factories import make_employee
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def registry_row(code):
	return frappe.db.get_value(
		"Code Registry", code, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
	)


class TestEmployeeCardRegister(IsolatedTestCase):
	@bru("BRU-ID-006")
	def test_saving_an_employee_registers_its_own_card(self):
		card = "T9-" + frappe.generate_hash(length=10).upper()
		employee = make_employee(card=card)
		row = registry_row(card)
		self.assertEqual(
			(row.prefix, row.ref_doctype, row.ref_name, row.status),
			(code_registry.CARD_PREFIX, "Employee", employee.name, "Active"),
		)

	def test_card_is_printable_as_an_employee_label(self):
		card = "T9-" + frappe.generate_hash(length=10).upper()
		make_employee(card=card)
		self.assertIsNone(core_print.object_code_problem("Employee Card", card))

	def test_default_nv_card_is_not_registered_twice(self):
		employee = make_employee(card=None)
		frappe.db.set_value("Employee", employee.name, "tc_card_id", employee.name, update_modified=False)
		employees.register_card_code(frappe.get_doc("Employee", employee.name))  # không lỗi, không ghi CARD
		self.assertNotEqual((registry_row(employee.name) or {}).get("prefix"), code_registry.CARD_PREFIX)

	def test_invalid_card_does_not_block_saving(self):
		employee = make_employee(card="AB")  # ngắn hơn 4 ký tự: không ghi sổ được
		self.assertIsNone(registry_row("AB"))
		self.assertTrue(frappe.db.exists("Employee", employee.name))

	def test_register_is_idempotent_and_keeps_existing_row(self):
		card = "T9-" + frappe.generate_hash(length=10).upper()
		employee = make_employee(card=card)
		employees.register_card_code(frappe.get_doc("Employee", employee.name))
		self.assertEqual(registry_row(card).ref_name, employee.name)

	def test_patch_registers_cards_of_existing_employees(self):
		card = "T9-" + frappe.generate_hash(length=10).upper()
		employee = make_employee(card=card)
		frappe.db.delete("Code Registry", {"name": card})  # nhân viên cũ: có thẻ nhưng chưa ghi sổ
		self.assertIsNone(registry_row(card))
		register_employee_cards.execute()
		self.assertEqual(registry_row(card).ref_name, employee.name)
		register_employee_cards.execute()  # chạy lại không đổi
		self.assertEqual(registry_row(card).prefix, code_registry.CARD_PREFIX)
