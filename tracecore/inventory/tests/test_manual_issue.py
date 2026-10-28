"""Xuất kho thủ công theo FEFO có lý do (FEAT-042, FR-M6-04, BRU-INV-001)."""

import frappe
from frappe.utils import add_days, today

from tracecore.core.errors import BlockedError
from tracecore.inventory import manual
from tracecore.inventory.tests.test_consume import ITEM, ConsumeCase, stock_of
from tracecore.tests import factories
from tracecore.tests.utils import bru

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
]


def block_code(case, **kwargs):
	with case.assertRaises(BlockedError) as ctx:
		manual.issue(**kwargs)
	return ctx.exception.block.code


@bru("BRU-INV-001")
class TestSuggest(ConsumeCase):
	def test_suggests_nearest_expiry_lots_first(self):
		result = manual.suggest(ITEM, 8)
		self.assertEqual(
			[(row["batch"], row["qty"]) for row in result["lots"]], [(self.near, 5), (self.far, 3)]
		)
		self.assertEqual(result["short"], 0)
		self.assertEqual(result["lots"][0]["expiry_date"], str(add_days(today(), 10)))


@bru("BRU-INV-001")
class TestManualIssue(ConsumeCase):
	def args(self, **kwargs):
		return {"item": ITEM, "qty": 4, "reason": "Cấp cho khoa Mắt", **kwargs}

	def test_default_is_fefo_and_records_reason_and_user(self):
		result = manual.issue(**self.args())
		doc = frappe.get_doc("Stock Entry", result["entry"])
		self.assertEqual(
			(doc.docstatus, doc.purpose, doc.tc_source_doctype), (1, "Material Issue", "Manual Issue")
		)
		self.assertEqual(doc.tc_reason, "Cấp cho khoa Mắt")
		self.assertEqual([(row.batch_no, row.qty) for row in doc.items], [(self.near, 4)])
		self.assertEqual(result["warnings"], [])
		self.assertEqual(stock_of(ITEM), 11)

	def test_reason_is_required(self):
		for reason in (None, "", "   "):
			self.assertEqual(block_code(self, **self.args(reason=reason)), "REASON_REQUIRED")
		self.assertEqual(stock_of(ITEM), 15)

	def test_quantity_must_be_positive(self):
		for qty in (0, -1, None):
			self.assertEqual(block_code(self, **self.args(qty=qty)), "ISSUE_QTY_INVALID")

	def test_unknown_item_is_refused(self):
		self.assertEqual(block_code(self, **self.args(item="KHONG-CO")), "ISSUE_ITEM_INVALID")

	def test_expired_lot_is_blocked(self):
		frappe.db.set_value("Batch", self.near, "expiry_date", add_days(today(), -1))
		code = block_code(self, **self.args(lots=[{"batch": self.near, "qty": 4}]))
		self.assertEqual(code, "LOT_EXPIRED")
		self.assertEqual(stock_of(ITEM), 15)

	def test_lot_of_another_item_is_refused(self):
		other = factories.make_chemical_batch("HC-F42-OTHER", "F42-OTHER", qty=5)
		code = block_code(self, **self.args(lots=[{"batch": other.name, "qty": 4}]))
		self.assertEqual(code, "LOT_INVALID")

	def test_not_enough_stock_in_the_chosen_lot_is_blocked(self):
		code = block_code(self, **self.args(qty=8, lots=[{"batch": self.near, "qty": 8}]))
		self.assertEqual(code, "STOCK_INSUFFICIENT")
		self.assertEqual(stock_of(ITEM), 15)

	def test_lot_quantities_must_add_up_to_the_request(self):
		code = block_code(self, **self.args(qty=4, lots=[{"batch": self.near, "qty": 3}]))
		self.assertEqual(code, "ISSUE_QTY_INVALID")

	def test_later_lot_while_nearer_one_has_stock_warns_but_issues(self):
		result = manual.issue(**self.args(lots=[{"batch": self.far, "qty": 4}]))
		self.assertEqual([w["code"] for w in result["warnings"]], ["FEFO_NOT_FOLLOWED"])
		self.assertEqual(stock_of(ITEM), 11)

	def test_department_is_written_into_the_reason(self):
		department = factories.make_department("Khoa Mắt F42")
		result = manual.issue(**self.args(department=department))
		self.assertIn(department, frappe.db.get_value("Stock Entry", result["entry"], "tc_reason"))
