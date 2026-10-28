"""Cost by Target: chi phí theo thiết bị/khu/chương trình và kỳ (FEAT-044; FR-M7-02.3; UC-27 bước 5; A-47 C11)."""

import frappe

from tracecore.costing.report.cost_by_target.cost_by_target import execute
from tracecore.tests.factories import cost_allocation, make_cost_entry, make_equipment, make_user
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def table(report):
	"""{(loại đối tượng, đối tượng, khoản mục): số tiền} của kết quả báo cáo."""
	return {(r["target_type"], r["target"], r["category"]): r["amount"] for r in report[1]}


def total(report):
	return {item["label"]: item["value"] for item in report[4]}["Total Cost"]


class TestCostByTarget(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.a = make_equipment(serial="SN-A").name
		self.b = make_equipment(serial="SN-B").name
		# 3.100.000 đ cả tháng 1/2026 (100.000 đ/ngày), A 60 % và B 40 %
		self.power = make_cost_entry(
			category="Electricity Expense",
			amount=3100000,
			period_from="2026-01-01",
			period_to="2026-01-31",
			allocations=[cost_allocation(self.a, 60), cost_allocation(self.b, 40)],
		)
		# 1.100.000 đ từ 10/1 đến 20/1 (100.000 đ/ngày), toàn bộ cho A
		self.steam = make_cost_entry(
			category="Steam Cost",
			amount=1100000,
			period_from="2026-01-10",
			period_to="2026-01-20",
			allocations=[cost_allocation(self.a, 100)],
		)
		self.power.submit()
		self.steam.submit()

	def run_report(self, **filters):
		return execute({"from_date": "2026-01-01", "to_date": "2026-01-15", **filters})

	def test_amounts_are_prorated_by_day_and_split_by_percent(self):
		report = self.run_report()
		self.assertEqual(
			table(report),
			{
				("Equipment", self.a, "Electricity Expense"): 900000,
				("Equipment", self.a, "Steam Cost"): 600000,
				("Equipment", self.b, "Electricity Expense"): 600000,
			},
		)
		self.assertEqual(total(report), 2100000)

	def test_whole_period_gives_the_whole_amounts(self):
		report = execute({"from_date": "2026-01-01", "to_date": "2026-01-31"})
		self.assertEqual(total(report), 4200000)

	def test_period_without_costs_is_empty(self):
		report = execute({"from_date": "2026-03-01", "to_date": "2026-03-31"})
		self.assertEqual(report[1], [])
		self.assertEqual(total(report), 0)

	def test_only_submitted_entries_count(self):
		make_cost_entry(
			amount=9000000,
			period_from="2026-01-01",
			period_to="2026-01-31",
			allocations=[cost_allocation(self.a, 100)],
		)  # Nháp
		cancelled = make_cost_entry(
			amount=7000000,
			period_from="2026-01-01",
			period_to="2026-01-31",
			allocations=[cost_allocation(self.a, 100)],
		)
		cancelled.submit()
		cancelled.cancel()
		self.assertEqual(total(self.run_report()), 2100000)

	def test_filters_by_target_and_category(self):
		self.assertEqual(
			table(self.run_report(target_type="Equipment", target=self.b)),
			{("Equipment", self.b, "Electricity Expense"): 600000},
		)
		self.assertEqual(
			table(self.run_report(category="Steam Cost")), {("Equipment", self.a, "Steam Cost"): 600000}
		)
		self.assertEqual(table(self.run_report(target_type="Zone Station")), {})

	def test_rows_add_up_to_the_summary(self):
		report = self.run_report()
		self.assertEqual(sum(r["amount"] for r in report[1]), total(report))

	def test_columns_carry_translatable_labels_and_types(self):
		columns = self.run_report()[0]
		self.assertEqual(
			[(c["fieldname"], c["fieldtype"]) for c in columns],
			[
				("target_type", "Data"),
				("target", "Dynamic Link"),
				("category", "Link"),
				("amount", "Currency"),
			],
		)

	def test_missing_dates_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			execute({"from_date": "2026-01-01"})
		with self.assertRaises(frappe.ValidationError):
			execute({"from_date": "2026-02-01", "to_date": "2026-01-01"})

	def test_user_without_cost_permission_cannot_run_it(self):
		user = make_user("cbt-r03@example.com", ["TC R03"])
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				self.run_report()
		finally:
			frappe.set_user("Administrator")

	def test_accountant_and_head_can_run_it(self):
		for role in ("TC R09", "TC R01"):
			user = make_user(f"cbt-{role.split()[-1].lower()}@example.com", [role])
			frappe.set_user(user)
			try:
				self.assertEqual(total(self.run_report()), 2100000)
			finally:
				frappe.set_user("Administrator")
