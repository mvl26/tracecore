"""Báo cáo phơi nhiễm theo kỳ và chỉ số M16 sang M9 (FEAT-071; FR-M16-09, FR-M16-09.1; BRU-OCC-003; NFR-PRIV-01;
UC-55 bước 8)."""

import frappe
from frappe.utils import getdate, now_datetime, today

from tracecore.core import indicators
from tracecore.occupational_safety import exposure
from tracecore.occupational_safety.report.occupational_exposure_by_period import (
	occupational_exposure_by_period as report,
)
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru


class TestExposureReport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.sql("update `tabOccupational Exposure` set status = 'Cancelled'")
		fx.clear_templates()
		fx.thresholds(report_hours=2)
		self.department = factories.make_department("PN Báo cáo")
		self.employee = fx.employee(
			"PN Report Nguyen Van Ten", self.department, designation="PN Report Nurse"
		)
		fx.template(steps=(("Step 1", 0),))
		late = exposure.create_report(
			{
				"employee": self.employee,
				"exposure_type": fx.SHARPS,
				"occurred_at": fx.hours_ago(5),
				"device": "Needle",
				"source_known": "Yes",
				"source_patient_code": "BN-REPORT-4455",
			}
		)
		done = exposure.record_handling(late.name, first_aid_done=1, prophylaxis="Not Indicated")
		exposure.mark_followup_done(done.name, done.followups[0].name, today())
		exposure.create_report(
			{"employee": self.employee, "exposure_type": fx.SHARPS, "occurred_at": now_datetime()}
		)
		exposure.create_report(
			{"employee": self.employee, "exposure_type": fx.SPLASH, "occurred_at": now_datetime()}
		)

	def _run(self, group_by="Exposure Type"):
		return report.execute(
			{"from_date": f"{getdate().year}-01-01", "to_date": today(), "group_by": group_by}
		)

	def test_groups_rates_and_total(self):
		_columns, rows = self._run()
		by_group = {row["group"]: row for row in rows}
		sharps = by_group[frappe._("Needlestick or Sharps", context="Occupational Exposure")]
		self.assertEqual(
			(sharps["exposures"], sharps["on_time"], sharps["scheduled"], sharps["completed"]), (2, 1, 1, 1)
		)
		self.assertEqual(sharps["on_time_rate"], 50.0)
		self.assertEqual(sharps["completion_rate"], 100.0)
		self.assertEqual(rows[-1]["exposures"], 3)

	@bru("BRU-OCC-003")
	def test_report_has_no_staff_name_or_patient_code(self):
		"""FR-M16-09.1, NFR-PRIV-01: mọi cách nhóm đều không in tên nhân viên hay mã BN nguồn."""
		for group_by in report.GROUPS:
			columns, rows = self._run(group_by)
			text = frappe.as_json([columns, rows])
			self.assertNotIn("Nguyen Van Ten", text, group_by)
			self.assertNotIn("4455", text, group_by)
			self.assertNotIn(self.employee, text, group_by)

	def test_report_roles_allow_r13_without_personal_read(self):
		doc = frappe.get_doc("Report", "Occupational Exposure by Period")
		self.assertEqual({row.role for row in doc.roles}, {"TC R01", "TC R11", "TC R13", "System Manager"})
		self.assertEqual(doc.ref_doctype, "IC Indicator Value")

	def test_indicators_registered_with_m9(self):
		methods = indicators.registry()
		for key in ("exposure_report_on_time", "exposure_followup_completion", "immunization_coverage"):
			self.assertIn(key, methods)
		period = today()[:7]
		self.assertEqual(methods["exposure_report_on_time"](period, None), (2, 3, 3))
		self.assertEqual(methods["exposure_followup_completion"](period, self.department), (1, 1, 1))
		num, den, _sample = methods["immunization_coverage"](period, None)
		self.assertLessEqual(num, den)
