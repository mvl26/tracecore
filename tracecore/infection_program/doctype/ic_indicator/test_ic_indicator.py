"""IC Indicator — danh mục chỉ số KSNK (FEAT-056 AC-4, FR-M9-27, FR-M11-04, architecture §5.3.1)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix

DOCTYPE = "IC Indicator"
MEASURE_GROUPS = (
	"Infection Surveillance",
	"Practice Compliance Monitoring",
	"Invasive Procedures and High-Risk Patients",
	"Patient Counselling",
	"Microorganism-Related Transmission Prevention",
	"Standard Precautions",
	"Transmission-Based Precautions",
	"Hand Hygiene",
	"Medical Devices and Equipment",
	"Medical Waste",
	"Environmental Hygiene and Infrastructure",
	"Linen",
	"Occupational Exposure",
	"Food Safety",
)


def make_indicator(code="T-HH-01", **values):
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"code": code,
			"indicator_name": "Hand hygiene compliance",
			"measure_group": "Hand Hygiene",
			"kind": "Percentage",
			**values,
		}
	)
	return doc.insert(ignore_permissions=True)


class TestICIndicator(IsolatedTestCase):
	def test_named_by_code_in_infection_program(self):
		doc = make_indicator()
		self.assertEqual(doc.name, "T-HH-01")
		self.assertEqual(frappe.get_meta(DOCTYPE).module, "Infection Program")

	def test_fourteen_measure_groups_and_three_kinds(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertEqual(tuple(meta.get_field("measure_group").options.split("\n")), MEASURE_GROUPS)
		self.assertEqual(meta.get_field("kind").options.split("\n"), ["Percentage", "Rate per 1000", "Count"])

	def test_inactive_indicator_needs_no_registered_method(self):
		doc = make_indicator(is_active=0, source_method="NOT_YET")
		self.assertEqual(doc.is_active, 0)

	def test_active_indicator_needs_registered_method(self):
		with patch("tracecore.core.indicators.registry", return_value={"HH_RATE": lambda p, d: (1, 1, 1)}):
			with self.assertRaises(frappe.ValidationError):
				make_indicator(code="T-HH-02", is_active=1)
			with self.assertRaises(frappe.ValidationError):
				make_indicator(code="T-HH-03", is_active=1, source_method="UNKNOWN")
			doc = make_indicator(code="T-HH-04", is_active=1, source_method="HH_RATE")
		self.assertEqual(doc.source_method, "HH_RATE")

	def test_target_needs_direction(self):
		with self.assertRaises(frappe.ValidationError):
			make_indicator(code="T-HH-05", national_target=80)
		doc = make_indicator(code="T-HH-06", national_target=80, target_direction="Higher is better")
		self.assertEqual(doc.national_target, 80)

	def test_min_sample_not_negative(self):
		with self.assertRaises(frappe.ValidationError):
			make_indicator(code="T-HH-07", min_sample=-1)


class TestICIndicatorPermissions(FrappeTestCase):
	def test_permission_matrix(self):
		assert_permission_matrix(self, DOCTYPE)
