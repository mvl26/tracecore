"""Script Report Stock Alerts: ba loại cảnh báo thay dashboard, nút tạo đề nghị mua một chạm (FEAT-043; FR-M6-06, .1-.3, .2;
SCR-26; A-52 C10)."""

import os

import frappe

from tracecore.inventory.report.stock_alerts import stock_alerts as report
from tracecore.inventory.tests.test_alerts import AlertCase
from tracecore.inventory.tests.test_consume import ITEM
from tracecore.tests import factories

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Material Request",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
]

REPORT_JS = os.path.join(
	frappe.get_app_path("tracecore"), "inventory", "report", "stock_alerts", "stock_alerts.js"
)


class TestStockAlertsReport(AlertCase):
	def rows(self, **filters):
		_columns, rows = report.execute(filters)[:2]
		return rows

	def of_type(self, kind, **filters):
		return [row for row in self.rows(**filters) if row["alert_type"] == kind]

	def test_below_minimum_rows_carry_the_shortfall(self):  # FR-M6-06
		self.set_minimum(20, reorder_qty=30)
		(row,) = [r for r in self.of_type("Below minimum") if r["item"] == ITEM]
		self.assertEqual(
			(row["warehouse"], row["qty"], row["minimum"], row["shortfall"]), (self.warehouse, 15, 20, 5)
		)

	def test_expiring_rows_carry_the_lot_and_days_left(self):  # FR-M6-06.1
		(row,) = [r for r in self.of_type("Expiring") if r["batch"] == self.near]
		self.assertEqual((row["item"], row["qty"], row["days_left"]), (ITEM, 5, 10))

	def test_missing_configuration_rows_have_no_stock_figures(self):  # FR-M6-06.3
		self.set_minimum(None)
		(row,) = [r for r in self.of_type("Not configured") if r["item"] == ITEM]
		self.assertFalse(row.get("qty"))
		self.assertFalse([r for r in self.of_type("Below minimum") if r["item"] == ITEM])

	def test_the_type_filter_keeps_only_that_kind(self):
		self.set_minimum(20)
		kinds = {row["alert_type"] for row in self.rows(alert_type="Expiring")}
		self.assertEqual(kinds, {"Expiring"})

	def test_the_days_filter_widens_the_expiry_window(self):
		self.assertNotIn(self.far, {r["batch"] for r in self.of_type("Expiring")})
		self.assertIn(self.far, {r["batch"] for r in self.of_type("Expiring", days=120)})

	def test_report_is_for_stock_managers_and_viewers(self):
		roles = {row.role for row in frappe.get_doc("Report", "Stock Alerts").roles}
		self.assertTrue({"TC R01", "TC R02", "TC R06", "TC R09", "System Manager"} <= roles)
		self.assertNotIn("TC R04", roles)

	def test_the_report_really_runs_for_each_allowed_role(self):
		"""`frappe.desk.query_report.run` kiểm quyền `report` trên DocType gốc; gọi `execute` thẳng không thấy lỗi này."""
		from frappe.desk.query_report import run

		self.set_minimum(20, reorder_qty=30)
		self.addCleanup(frappe.set_user, "Administrator")
		users = {
			role: factories.make_user(
				f"alerts-report-{role.lower().replace(' ', '-')}@example.com", roles=(role,)
			)
			for role in ("TC R09", "TC R02", "TC R06", "TC R01", "TC R04")
		}
		for role in ("TC R09", "TC R02", "TC R06", "TC R01"):
			frappe.set_user(users[role])
			result = run("Stock Alerts", filters={}, ignore_prepared_report=True)
			self.assertIn(ITEM, {row.get("item") for row in result["result"]}, role)
		frappe.set_user(users["TC R04"])
		with self.assertRaises(frappe.PermissionError):
			run("Stock Alerts", filters={}, ignore_prepared_report=True)

	def test_script_calls_the_one_tap_rpc_with_an_idempotency_key(self):
		with open(REPORT_JS, encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn("tracecore.v1.stock.create_purchase_request", source)
		self.assertIn("tracecore.codes.new_request", source)
		self.assertIn("tracecore.codes.send", source)
		self.assertNotIn("frappe.msgprint", source)  # lỗi chặn hiện inline, không modal
