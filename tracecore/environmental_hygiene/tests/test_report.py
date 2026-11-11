"""Chỉ số M15 cho M9 và báo cáo môi trường tháng/quý (FEAT-070; FR-M15-07, .1; QĐ 38; UC-54 bước 8)."""

import frappe

from tracecore.environmental_hygiene import indicators, report_data, zones
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.utils import IsolatedTestCase


class TestEnvironmentReport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.ward = ef.make_department("BC Khoa Gây mê")
		frappe.db.delete(zones.DOCTYPE, {"department": self.ward})
		self.zone = ef.make_zone(self.ward, area="Phòng mổ BC").name
		self.template = ef.make_env_template().name
		ef.make_limit("T-PM-KK", value=10, effective_from="2026-01-01")
		ef.make_session(self.template, self.ward, self.zone, audit_date="2026-10-02")
		ef.make_session(self.template, self.ward, self.zone, passed=False, audit_date="2026-11-02")
		ef.make_sample(self.zone, 4, sampled_on="2026-10-05")
		ef.make_sample(self.zone, 40, sampled_on="2026-11-05")

	def test_indicators_are_registered(self):
		registered = indicators.register()
		for key in (
			indicators.SURFACE_HIGH_RISK,
			indicators.SAMPLE_PASS,
			indicators.VENTILATION_ON_TIME,
			indicators.WATER_ON_TIME,
		):
			self.assertIn(key, registered)
		self.assertEqual(indicators.surface_high_risk_pass("2026-10")[:2], (1, 1))
		self.assertEqual(indicators.sample_pass("2026-11")[:2], (0, 1))
		self.assertEqual(indicators.sample_pass("2026-11", self.ward)[:2], (0, 1))

	def test_quarter_report_merges_audits_samples_infrastructure_and_chemicals(self):
		data = report_data.build("Quarter", "2026-11-15")
		self.assertEqual((str(data["from_date"]), str(data["to_date"])), ("2026-10-01", "2026-12-31"))
		self.assertEqual(data["samples"]["total"], 2)
		self.assertEqual(data["samples"]["failed"], 1)
		risk = {row["key"]: row for row in data["hygiene"]["by_risk"]}
		self.assertEqual(risk[ef.make_level()]["total"], 2)
		self.assertIn("rows", data["infrastructure"])
		self.assertIn("litres", data["chemicals"])

	def test_month_report_and_script_report_rows(self):
		data = report_data.build("Month", "2026-10-20")
		self.assertEqual(data["samples"]["total"], 1)
		from tracecore.environmental_hygiene.report.environmental_hygiene import (
			environmental_hygiene as script,
		)

		columns, rows = script.execute({"period_type": "Month", "date": "2026-10-20"})[:2]
		self.assertTrue(columns)
		self.assertTrue(any(row.get("section") for row in rows))
