"""Dịch vụ bảng định giá `costing.rates` (FEAT-045; FR-M7-03 .1/.3, FR-M7-04 .2/.3; UC-28 E1-E3, A1; A-48 D1-D6)."""

import frappe

from tracecore.tests.factories import (
	make_cost_rate_version,
	make_equipment,
	make_item,
	make_program,
	norm_line,
	rate_line,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "User"]

DOCTYPE = "Cost Rate Version"
POUCH = "VT-F45-TUI"
LABEL = "VT-F45-NHAN"


def warnings():
	return " ".join(str(m.get("message")) for m in frappe.get_message_log())


class RatesCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.pouch = make_item(POUCH, "Pouch").name
		self.label = make_item(LABEL, "Label").name
		frappe.clear_messages()


@bru("BRU-CST-002")
class TestRateLines(RatesCase):
	def test_negative_rate_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			make_cost_rate_version(rates=[rate_line(-1, "Electricity")])

	def test_item_rate_requires_item(self):
		with self.assertRaises(frappe.ValidationError):
			make_cost_rate_version(rates=[rate_line(1000, "Item")])

	def test_non_item_rate_must_not_have_item(self):
		with self.assertRaises(frappe.ValidationError):
			make_cost_rate_version(rates=[rate_line(1000, "Labor", self.pouch)])

	def test_duplicate_rate_blocked(self):
		for rows in (
			[rate_line(1000, "Item", self.pouch), rate_line(2000, "Item", self.pouch)],
			[rate_line(3000, "Electricity"), rate_line(3500, "Electricity")],
		):
			with self.assertRaises(frappe.ValidationError, msg=rows):
				make_cost_rate_version(rates=rows)

	def test_same_rate_type_for_different_items_is_accepted(self):
		doc = make_cost_rate_version(
			rates=[rate_line(1000, "Item", self.pouch), rate_line(200, "Item", self.label)]
		)
		self.assertEqual(len(doc.rates), 2)

	def test_uom_set_from_type(self):
		doc = make_cost_rate_version(
			rates=[
				rate_line(1000, "Item", self.pouch),
				rate_line(50000, "Labor"),
				rate_line(3000, "Electricity"),
				rate_line(15, "Tap Water"),
				rate_line(40, "RO Water"),
				rate_line(800, "Steam"),
			]
		)
		stock_uom = frappe.db.get_value("Item", self.pouch, "stock_uom")
		self.assertEqual([r.uom for r in doc.rates], [stock_uom, "hour", "kWh", "L", "L", "kg"])

	def test_zero_rate_or_norm_warns_but_saves(self):  # FR-M7-04.3, UC-28 E2
		doc = make_cost_rate_version(
			rates=[rate_line(0, "Item", self.pouch)], pack_norms=[norm_line(self.pouch, self.label, 0)]
		)
		self.assertTrue(frappe.db.exists(DOCTYPE, doc.name))
		self.assertIn(POUCH, warnings())
		self.assertIn(LABEL, warnings())

	def test_negative_norm_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			make_cost_rate_version(pack_norms=[norm_line(self.pouch, self.label, -1)])

	def test_duplicate_pack_norm_blocked(self):
		rows = [norm_line(self.pouch, self.label, 1), norm_line(self.pouch, self.label, 2)]
		with self.assertRaises(frappe.ValidationError):
			make_cost_rate_version(pack_norms=rows)

	def test_programs_without_norm_are_listed(self):  # FR-M7-04.2
		program = make_program(make_equipment().name, code="MH-F45-01")
		self.assertEqual(program.norm_status, "Missing")
		make_cost_rate_version()
		self.assertIn("MH-F45-01", warnings())

	def test_empty_draft_can_be_saved(self):
		self.assertEqual(make_cost_rate_version(rates=[]).docstatus, 0)
