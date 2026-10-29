"""Set Cost Report (FEAT-046 Task 5; FR-M7-06.1, EI-SW-006; A-53 j)."""

import frappe
from frappe.utils import add_days, add_months, get_first_day, get_last_day, getdate, today

from tracecore.costing import sheet
from tracecore.costing.report.set_cost_report import set_cost_report as report
from tracecore.costing.tests.test_sheet import SheetCase


class TestSetCostReport(SheetCase):
	def test_groups_by_set_type_and_compares_with_previous_month(self):
		self.priced()
		now_name = sheet.build("Sterilization Load", self.load(packs=self.packs[:2]))
		old_name = sheet.build("Sterilization Load", self.load(packs=self.packs[2:]))
		start = get_first_day(today())
		frappe.db.set_value("Cost Sheet", old_name, "cost_date", add_months(start, -1))
		set_type = frappe.db.get_value("Pack", self.packs[0].name, "set_type")
		_columns, rows = report.execute(
			{"from_date": start, "to_date": get_last_day(start), "group_by": "Set Type"}
		)
		mine = [row for row in rows if row["group"] == set_type]
		self.assertEqual(len(mine), 1)
		now_doc = frappe.get_doc("Cost Sheet", now_name)
		first = next(r for r in now_doc.packs if r.set_type == set_type)
		self.assertEqual(mine[0]["packs"], sum(1 for r in now_doc.packs if r.set_type == set_type))
		self.assertEqual(mine[0]["total"], sum(r.total for r in now_doc.packs if r.set_type == set_type))
		self.assertEqual(mine[0]["average"], first.total)

	def test_previous_period_average_and_change(self):
		self.priced()
		name = sheet.build("Sterilization Load", self.load(packs=self.packs[:1]))
		total = frappe.db.get_value("Cost Sheet Pack", {"parent": name}, "total")
		frappe.db.set_value("Cost Sheet", name, "cost_date", add_days(getdate(today()), -40))
		previous_name = name
		name = sheet.build("Sterilization Load", self.load(packs=self.packs[1:2]))
		set_type = frappe.db.get_value("Pack", self.packs[1].name, "set_type")
		frappe.db.set_value("Pack", self.packs[0].name, "set_type", set_type)
		frappe.db.set_value("Cost Sheet Pack", {"parent": previous_name}, "set_type", set_type)
		_columns, rows = report.execute(
			{"from_date": add_days(today(), -10), "to_date": today(), "group_by": "Set Type"}
		)
		row = next(r for r in rows if r["group"] == set_type)
		self.assertEqual(row["previous_average"], 0)  # kỳ trước 10 ngày: gói 40 ngày trước không thuộc
		_columns, rows = report.execute(
			{"from_date": add_days(today(), -30), "to_date": today(), "group_by": "Set Type"}
		)
		row = next(r for r in rows if r["group"] == set_type)
		self.assertEqual(row["previous_average"], total)
		self.assertIn("change_percent", row)

	def test_month_filter_compares_with_the_whole_previous_month(self):
		"""Lọc tháng 11 thì kỳ trước là cả tháng 10 (gồm ngày 01/10), không phải 30 ngày trước (review #3)."""
		self.priced()
		previous = sheet.build("Sterilization Load", self.load(packs=self.packs[:1]))
		current = sheet.build("Sterilization Load", self.load(packs=self.packs[1:2]))
		set_type = frappe.db.get_value("Cost Sheet Pack", {"parent": current}, "set_type")
		frappe.db.set_value("Cost Sheet Pack", {"parent": previous}, "set_type", set_type)
		frappe.db.set_value("Cost Sheet", previous, "cost_date", "2026-10-01")
		frappe.db.set_value("Cost Sheet", current, "cost_date", "2026-11-05")
		_columns, rows = report.execute(
			{"from_date": "2026-11-01", "to_date": "2026-11-30", "group_by": "Set Type"}
		)
		row = next(r for r in rows if r["group"] == set_type)
		self.assertEqual(
			row["previous_average"], frappe.db.get_value("Cost Sheet Pack", {"parent": previous}, "total")
		)

	def test_recalculated_sheets_are_excluded_and_columns_exported(self):
		self.priced()
		load = self.load(packs=self.packs[:1])
		sheet.build("Sterilization Load", load)
		sheet.build("Sterilization Load", load, rate_version=None, recalculation=True)
		columns, rows = report.execute(
			{"from_date": add_days(today(), -1), "to_date": today(), "group_by": "Cycle ID"}
		)
		self.assertEqual([r["packs"] for r in rows if r["group"] == self.packs[0].name], [1])
		self.assertEqual(
			[c["fieldname"] for c in columns],
			["group", "packs", "total", "average", "previous_average", "change_percent"],
		)
