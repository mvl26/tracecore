"""Phần "phơi nhiễm nghề nghiệp" của gói hồ sơ KSNK: chỉ số liệu tổng hợp (FEAT-074; FR-M9-30.1; FR-M16-06;
BRU-RPT-002; A-152 Q3)."""

import frappe

from tracecore.core import dossier as core_dossier
from tracecore.occupational_safety import dossier
from tracecore.tests.utils import IsolatedTestCase, bru

NEEDLE = "Needlestick or Sharps"


def exposure(occurred_at, status="New", **values):
	doc = frappe.get_doc(
		{
			"doctype": "Occupational Exposure",
			"employee_name": "Nhân viên A",
			"department_name": "Khoa hồ sơ phơi nhiễm",
			"exposure_type": NEEDLE,
			"occurred_at": occurred_at,
			"status": status,
			"source_patient_code_masked": "***7777",
			**values,
		}
	)
	doc.db_insert()
	return doc


class TestExposureDossier(IsolatedTestCase):
	@bru("BRU-RPT-002")
	def test_only_aggregates_without_staff_or_source_patient(self):
		exposure("2026-01-03 10:00:00", report_late=1, prophylaxis="Given")
		exposure("2026-01-20 10:00:00", status="Completed")
		exposure("2026-01-21 10:00:00", status="Cancelled")
		exposure("2026-03-01 10:00:00")
		rows = [
			row
			for row in dossier.rows(core_dossier.context("2026-01", "2026-02"))
			if row.department_name == "Khoa hồ sơ phơi nhiễm"
		]
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row.month, "2026-01")
		self.assertEqual(
			(row.exposures, row.reported_late, row.prophylaxis_given, row.follow_up_completed), (2, 1, 1, 1)
		)
		section = dossier.register()[0]
		fields = {item.field for item in section.fields}
		self.assertFalse(fields & {"employee", "employee_name", "source_patient_code_masked"})
		self.assertNotIn("Nhân viên A", {str(value) for value in row.values()})
		self.assertTrue(core_dossier.check_section(section))
