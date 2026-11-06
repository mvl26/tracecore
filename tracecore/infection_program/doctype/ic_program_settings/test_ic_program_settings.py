"""IC Program Settings — cài đặt chương trình KSNK (FEAT-056 AC-3, FR-M11-01 nền, architecture §5.3.1, §8.2; plan D5)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix

DOCTYPE = "IC Program Settings"


class TestICProgramSettings(IsolatedTestCase):
	def _settings(self, **values):
		doc = frappe.get_single(DOCTYPE)
		doc.update({"bed_count": 420, "facility_level": "Specialized", "has_inpatient": 1, **values})
		return doc

	def test_is_single_in_infection_program_module(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertTrue(meta.issingle)
		self.assertEqual(meta.module, "Infection Program")

	def test_defaults_and_fields(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertEqual(meta.get_field("surveillance_ratio_beds").default, "150")
		self.assertEqual(meta.get_field("doc_review_months").default, "12")
		self.assertEqual(
			meta.get_field("facility_level").options.split("\n"), ["Specialized", "Basic", "Primary"]
		)
		for field in ("patient_data_retention_months", "exposure_retention_months"):
			self.assertEqual(meta.get_field(field).fieldtype, "Int", msg=field)

	def test_save_valid_settings(self):
		doc = self._settings(surveillance_ratio_beds=150, doc_review_months=12)
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_single_value(DOCTYPE, "bed_count"), 420)

	def test_negative_or_zero_values_rejected(self):
		for field, value in (
			("bed_count", -1),
			("surveillance_ratio_beds", 0),
			("doc_review_months", 0),
			("patient_data_retention_months", -3),
			("exposure_retention_months", 0),
		):
			doc = self._settings(**{field: value})
			with self.assertRaises(frappe.ValidationError, msg=field):
				doc.save(ignore_permissions=True)

	def test_retention_left_empty_means_not_applied(self):
		doc = self._settings(patient_data_retention_months=None, exposure_retention_months=None)
		doc.save(ignore_permissions=True)
		self.assertFalse(frappe.db.get_single_value(DOCTYPE, "patient_data_retention_months"))


class TestICProgramSettingsPermissions(FrappeTestCase):
	def test_permission_matrix(self):
		assert_permission_matrix(self, DOCTYPE)
