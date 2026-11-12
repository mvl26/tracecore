"""A-154 (FEAT-096): loại chỉ thị hóa học của loại bộ (FR-M1-03.9)."""

import frappe

from tracecore.core import ci_class
from tracecore.instrument import bom_versions
from tracecore.tests.factories import make_item, make_set_type
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import set_type as set_type_api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestCiClassRules(IsolatedTestCase):
	def test_classes_for_each_setting(self):
		self.assertEqual(ci_class.classes_for(None), ("5", "6"))  # chưa khai: luật cũ
		self.assertEqual(ci_class.classes_for(""), ("5", "6"))
		self.assertEqual(ci_class.classes_for("4"), ("4",))
		self.assertEqual(ci_class.classes_for("5"), ("5",))
		self.assertEqual(ci_class.classes_for("6"), ("6",))
		self.assertEqual(ci_class.classes_for(ci_class.NOT_REQUIRED), ())
		self.assertTrue(ci_class.is_required(None))
		self.assertTrue(ci_class.is_required("4"))
		self.assertFalse(ci_class.is_required(ci_class.NOT_REQUIRED))
		self.assertEqual(ci_class.PACK_CLASSES, ("4", "5", "6"))


class TestSetTypeCiClassField(IsolatedTestCase):
	def test_field_is_an_optional_select_before_the_default_indicator(self):
		meta = frappe.get_meta("Instrument Set Type")
		field = meta.get_field("ci_class")
		self.assertIsNotNone(field)
		self.assertEqual(field.fieldtype, "Select")
		self.assertEqual(field.options.split("\n"), ["", "Not Needed", "4", "5", "6"])
		self.assertFalse(field.reqd)
		order = [row.fieldname for row in meta.fields]
		self.assertLess(order.index("tab_programs"), order.index("ci_class"))
		self.assertEqual(order.index("ci_class") + 1, order.index("default_ci_item"))

	def test_ci_class_is_part_of_create_and_copy_headers(self):
		self.assertIn("ci_class", bom_versions.HEADER_FIELDS)
		self.assertIn("ci_class", bom_versions.COPY_FIELDS)

	def test_each_choice_is_saved(self):
		doc = make_set_type("A154A", method="Steam")
		for value in ("Not Needed", "4", "5", "6", ""):
			doc.reload()
			doc.ci_class = value
			doc.default_ci_item = None
			doc.save(ignore_permissions=True)
			self.assertEqual(frappe.db.get_value("Instrument Set Type", doc.name, "ci_class") or "", value)


class TestDefaultIndicatorFollowsClass(IsolatedTestCase):
	def test_default_indicator_must_have_the_declared_class(self):
		ci4 = make_item("CI4-STEAM-A154", "Chemical Indicator", method="Steam", ci_class="4").name
		ci6 = make_item("CI6-STEAM-A154", "Chemical Indicator", method="Steam", ci_class="6").name
		doc = make_set_type("A154B", method="Steam")
		doc.ci_class = "4"
		doc.default_ci_item = ci4
		doc.save(ignore_permissions=True)  # loại 4 hợp lệ khi bộ khai loại 4
		doc.reload()
		doc.ci_class = "5"
		doc.default_ci_item = ci6
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_not_required_refuses_a_default_indicator(self):
		ci5 = make_item("CI5-STEAM-A154", "Chemical Indicator", method="Steam", ci_class="5").name
		doc = make_set_type("A154C", method="Steam")
		doc.ci_class = "Not Needed"
		doc.default_ci_item = ci5
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		doc.reload()
		doc.ci_class = "Not Needed"
		doc.default_ci_item = None
		doc.save(ignore_permissions=True)

	def test_blank_class_keeps_class_5_or_6_rule(self):
		ci4 = make_item("CI4-BLANK-A154", "Chemical Indicator", method="Steam", ci_class="4").name
		doc = make_set_type("A154D", method="Steam")
		doc.ci_class = ""
		doc.default_ci_item = ci4
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_query_follows_the_declared_class(self):
		four = make_item("CI4-QC-STEAM-A154", "Chemical Indicator", method="Steam", ci_class="4").name
		five = make_item("CI5-QC-STEAM-A154", "Chemical Indicator", method="Steam", ci_class="5").name
		codes = [
			r[0] for r in set_type_api.ci_item_query(txt="QC-", filters={"method": "Steam", "ci_class": "4"})
		]
		self.assertEqual(codes, [four])
		codes = [
			r[0] for r in set_type_api.ci_item_query(txt="QC-", filters={"method": "Steam", "ci_class": ""})
		]
		self.assertEqual(codes, [five])
		codes = set_type_api.ci_item_query(txt="QC-", filters={"method": "Steam", "ci_class": "Not Needed"})
		self.assertEqual(list(codes), [])
