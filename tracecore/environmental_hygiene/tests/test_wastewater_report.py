"""Báo cáo nước thải, dòng tóm tắt trong báo cáo môi trường, chỉ số SCR-66 và badge (FEAT-095; FR-M15-12, .1;
AC-095-12)."""

import frappe

from tracecore.environmental_hygiene import indicators, report_data, wastewater, wastewater_report
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase

FULL = {"pH": 7.1, "COD": 48, "Coliforms": 3000, "Salmonella": "KPH"}


class TestWastewaterReport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Wastewater Point")
		self.point = ef.make_point().name
		ef.make_permit("T-BC", rows=ef.rows_for(self.point))
		self.passed = ef.make_monitoring(self.point, FULL, sampled_on="2026-03-18")
		self.failed = ef.make_monitoring(
			self.point, {**FULL, "Coliforms": 9300, "COD": 120}, sampled_on="2026-09-22"
		)

	def test_summary_lists_point_parameter_round_with_limit_and_exceed_count(self):
		"""AC-095-12."""
		data = wastewater_report.summary("2026-01-01", "2026-12-31")
		self.assertEqual((data["rounds"], data["failed"]), (2, 1))
		coli = [row for row in data["rows"] if row["parameter"] == "Coliforms"]
		self.assertEqual([row["monitoring"] for row in coli], [self.passed.name, self.failed.name])
		self.assertIn("5", coli[0]["limit_applied"])
		self.assertEqual(data["exceed"][(self.point, "Coliforms")], 1)
		self.assertEqual(data["exceed"][(self.point, "COD")], 1)
		self.assertEqual(wastewater_report.summary("2026-07-01", "2026-12-31", self.point)["rounds"], 1)

	def test_script_report_rows_and_exceed_section(self):
		from tracecore.environmental_hygiene.report.wastewater_monitoring_summary import (
			wastewater_monitoring_summary as script,
		)

		columns, rows = script.execute({"from_date": "2026-01-01", "to_date": "2026-12-31"})[:2]
		self.assertIn("limit_applied", [col["fieldname"] for col in columns])
		self.assertTrue(
			any(row.get("result") == frappe._("Fail") and row.get("parameter") == "Coliforms" for row in rows)
		)
		self.assertTrue(any(row.get("section") and row.get("exceed") == 1 for row in rows))

	def test_environment_report_has_a_wastewater_line_and_indicator_is_registered(self):
		"""FR-M15-12.1."""
		data = report_data.build("Quarter", "2026-09-15")
		self.assertEqual((data["wastewater"]["rounds"], data["wastewater"]["failed"]), (1, 1))
		from tracecore.environmental_hygiene.report.environmental_hygiene import (
			environmental_hygiene as script,
		)

		rows = script.execute({"period_type": "Quarter", "date": "2026-09-15"})[1]
		line = [row for row in rows if row.get("section") == frappe._("Medical wastewater")]
		self.assertEqual((line[0]["total"], line[0]["passed"]), (1, 0))
		self.assertIn(indicators.WASTEWATER_ON_TIME, indicators.register())
		self.assertEqual(indicators.wastewater_on_time("2026-10")[:2], (2, 3))

	def test_badges_count_flagged_points_for_r01_r11_only(self):
		badge = wastewater.badges("Administrator")[wastewater.BADGE_SLUG]
		self.assertGreaterEqual(badge, 1)
		self.assertEqual(wastewater.badges(make_user("ww-r13@example.com", ["TC R13"])), {})
