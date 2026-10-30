"""Báo cáo tháng môi trường khu (FEAT-008, FR-M9-04, A-55 D5)."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.admin_reports.report.environment_monthly_report import environment_monthly_report as report
from tracecore.admin_reports.tests.test_environment import OTHER_ZONE, ZONE, EnvCase, at, monitor, reading


class TestEnvironmentMonthlyReport(EnvCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_single_value("TraceCore Settings", "env_reminder_times", "11:00, 17:00")
		self.day = getdate(add_days(today(), -1))
		self.filters = {"month": self.day.month, "year": self.day.year}

	def rows(self, **filters):
		columns, rows = report.execute({**self.filters, **filters})
		self.assertTrue(columns)
		return rows

	def test_one_row_per_zone_and_day_with_min_max_and_breaches(self):
		monitor(temp_max=24)
		reading(temperature=20, humidity=50, measured_at=at(self.day, 10))
		reading(temperature=26, humidity=55, pressure_diff=8, measured_at=at(self.day, 15))
		row = next(r for r in self.rows(zone=ZONE) if str(r["date"]) == str(self.day))
		self.assertEqual((row["zone"], row["readings"], row["out_of_range"]), (ZONE, 2, 1))
		self.assertEqual((row["temp_min"], row["temp_max"]), (20, 26))
		self.assertEqual((row["humidity_min"], row["humidity_max"]), (50, 55))
		self.assertEqual((row["pressure_min"], row["pressure_max"]), (8, 8))
		self.assertEqual(row["missing"], 0)

	def test_days_without_enough_readings_count_missing_times(self):
		reading(temperature=20, measured_at=at(self.day, 10))
		row = next(r for r in self.rows(zone=ZONE) if str(r["date"]) == str(self.day))
		self.assertEqual(row["missing"], 1)  # 11:00-17:00 không có lần đo

	def test_zone_filter_and_drafts(self):
		monitor(OTHER_ZONE)
		reading(zone=OTHER_ZONE, temperature=20, measured_at=at(self.day, 10))
		reading(temperature=20, measured_at=at(self.day, 10), submit=False)
		zones = {r["zone"] for r in self.rows(zone=OTHER_ZONE)}
		self.assertEqual(zones, {OTHER_ZONE})
		mine = [r for r in self.rows(zone=ZONE) if str(r["date"]) == str(self.day)]
		self.assertEqual(mine[0]["readings"], 0)

	def test_month_is_required(self):
		with self.assertRaises(frappe.ValidationError):
			report.execute({"year": self.day.year})
