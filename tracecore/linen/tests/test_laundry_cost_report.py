"""Báo cáo Laundry Cost per Kg: chi phí/kg theo tháng (FEAT-034; FR-M3-04.1; A-50 D12)."""

import frappe

from tracecore.linen.report.laundry_cost_per_kg import laundry_cost_per_kg as report
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

REPORT = "Laundry Cost per Kg"


def submitted_batch(ended_at, kg, cost, note=None, submit=True):
	doc = frappe.get_doc(
		{
			"doctype": "Laundry Batch",
			"batch_type": "Outsourced",
			"vendor": "Giặt ABC",
			"price_per_kg": 1000,
			"weight_kg": kg,
			"status": "Passed",
			"ended_at": ended_at,
			"cost_total": cost,
			"cost_per_kg": cost / kg,
			"cost_note": note,
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


class TestLaundryCostReport(IsolatedTestCase):
	def run_report(self, start="2026-01-01", end="2026-12-31"):
		columns, rows = report.execute({"from_date": start, "to_date": end})[:2]
		return [column["fieldname"] for column in columns], rows

	def test_one_row_per_month_with_weighted_cost_per_kg(self):  # FR-M3-04.1
		submitted_batch("2026-03-05 10:00:00", 10, 50000)
		submitted_batch("2026-03-20 15:00:00", 30, 90000)
		submitted_batch("2026-04-02 08:00:00", 20, 40000)
		_fields, rows = self.run_report()
		self.assertEqual(
			[
				(row["month"], row["batches"], row["weight_kg"], row["cost_total"], row["cost_per_kg"])
				for row in rows
			],
			[("2026-03", 2, 40, 140000, 3500), ("2026-04", 1, 20, 40000, 2000)],
		)

	def test_running_and_cancelled_batches_are_not_counted(self):
		submitted_batch("2026-05-05 10:00:00", 10, 50000, submit=False)
		cancelled = submitted_batch("2026-05-06 10:00:00", 10, 70000)
		cancelled.cancel()
		_fields, rows = self.run_report()
		self.assertEqual(rows, [])

	def test_batches_without_a_rate_are_counted_separately(self):
		submitted_batch("2026-06-05 10:00:00", 10, 50000)
		submitted_batch("2026-06-06 10:00:00", 10, 0, note="No rate for: Labor")
		_fields, rows = self.run_report()
		self.assertEqual((rows[0]["batches"], rows[0]["without_rate"]), (2, 1))

	def test_only_the_filtered_dates_are_included(self):
		submitted_batch("2026-07-05 10:00:00", 10, 50000)
		submitted_batch("2026-08-05 10:00:00", 10, 50000)
		_fields, rows = self.run_report("2026-08-01", "2026-08-31")
		self.assertEqual([row["month"] for row in rows], ["2026-08"])

	def test_dates_are_required_and_ordered(self):
		for filters in (
			{},
			{"from_date": "2026-01-01"},
			{"from_date": "2026-02-01", "to_date": "2026-01-01"},
		):
			with self.assertRaises(frappe.ValidationError):
				report.execute(filters)

	def test_report_is_for_managers_and_finance(self):
		roles = {row.role for row in frappe.get_doc("Report", REPORT).roles}
		self.assertEqual(roles, {"TC R01", "TC R02", "TC R07", "TC R09", "TC R10", "System Manager"})
