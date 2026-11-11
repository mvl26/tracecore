"""Phần của gói hồ sơ KSNK: chặn dữ liệu cá nhân, dải tháng (FEAT-074; FR-M9-30.1; BRU-RPT-002; UC-57 E5; A-152)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import dossier
from tracecore.core.dossier import DossierSection, ExportField
from tracecore.tests.utils import bru


def section(key="demo", fields=None, rows=None, order=10):
	return DossierSection(
		key=key,
		label="Demo",
		order=order,
		fields=fields or [ExportField("name", "Name"), ExportField("patient_code_masked", "Patient Code")],
		rows=lambda ctx: rows or [],
	)


class TestCoreDossier(FrappeTestCase):
	@bru("BRU-RPT-002")
	def test_clear_patient_or_staff_columns_are_refused(self):
		for field in ("patient_code", "patient_name", "employee_name", "source_patient_code", "full_name"):
			with self.assertRaises(dossier.DossierPrivacyError):
				dossier.check_section(section(fields=[ExportField(field, "X")]))
		self.assertTrue(dossier.check_section(section()))

	@bru("BRU-RPT-002")
	def test_unmasked_codes_are_refused(self):
		sec = section()
		ok = [{"name": "A", "patient_code_masked": "***5678"}, {"name": "B", "patient_code_masked": ""}]
		self.assertEqual(dossier.check_rows(sec, ok), ok)
		with self.assertRaises(dossier.DossierPrivacyError):
			dossier.check_rows(sec, [{"name": "C", "patient_code_masked": "BN12345678"}])

	def test_sections_are_ordered_and_can_be_chosen(self):
		found = [[section("b", order=20), section("a", order=10)]]
		with patch("tracecore.core.dossier.extension.run", return_value=found):
			self.assertEqual([s.key for s in dossier.sections()], ["a", "b"])
			self.assertEqual([s.key for s in dossier.sections(["b"])], ["b"])
			self.assertRaises(frappe.ValidationError, dossier.sections, ["zzz"])

	def test_registered_sections_pass_the_privacy_check(self):
		keys = [s.key for s in dossier.sections()]
		for key in ("indicators", "plan_activities", "compliance", "hai_cases", "mdro_isolates"):
			self.assertIn(key, keys)
		self.assertIn("exposures", keys)
		self.assertIn("environment_samples", keys)

	def test_months_and_context(self):
		self.assertEqual(dossier.months("2025-11", "2026-02"), ["2025-11", "2025-12", "2026-01", "2026-02"])
		ctx = dossier.context("2026-01", "2026-02")
		self.assertEqual(str(ctx.from_date), "2026-01-01")
		self.assertEqual(str(ctx.to_date), "2026-02-28")
		self.assertEqual(ctx.years, [2026])
		self.assertEqual(dossier.month_range("2026-01-01", "2026-02-28"), ("2026-01", "2026-02"))
		self.assertRaises(frappe.ValidationError, dossier.months, "2026-13", "2026-12")
		self.assertRaises(frappe.ValidationError, dossier.months, "2026-05", "2026-01")
		self.assertRaises(frappe.ValidationError, dossier.months, "2020-01", "2026-12")
