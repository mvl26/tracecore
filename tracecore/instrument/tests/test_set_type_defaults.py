"""A-122 (FEAT-086): chỉ thị mặc định và tab Mặc định xử lý của loại bộ."""

import frappe

from tracecore.instrument import bom_versions
from tracecore.tests.factories import make_item, make_set_type
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import set_type as set_type_api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestDefaultIndicator(IsolatedTestCase):
	def test_valid_indicator_item_is_saved(self):
		ci = make_item("CI5-STEAM-A122", "Chemical Indicator", method="Steam", ci_class="5").name
		doc = make_set_type("A122A", method="Steam")
		doc.default_ci_item = ci
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Instrument Set Type", doc.name, "default_ci_item"), ci)

	def test_blank_indicator_is_allowed(self):
		doc = make_set_type("A122B", method="Steam")
		doc.default_ci_item = None
		doc.save(ignore_permissions=True)  # thiếu mặc định không chặn

	def test_wrong_indicator_items_are_refused(self):
		doc = make_set_type("A122C", method="Steam")
		cases = {
			"wrong method": make_item("CI5-PLASMA-A122", "Chemical Indicator", method="Plasma", ci_class="5"),
			"class 4": make_item("CI4-STEAM-A122", "Chemical Indicator", method="Steam", ci_class="4"),
			"not an indicator": make_item("VT-GOI-A122C", "Packaging", shelf_life_days=30),
		}
		disabled = make_item("CI6-OFF-A122", "Chemical Indicator", method="Steam", ci_class="6")
		frappe.db.set_value("Item", disabled.name, "disabled", 1)
		cases["disabled"] = disabled
		for label, item in cases.items():
			doc.reload()
			doc.default_ci_item = item.name
			with self.assertRaises(frappe.ValidationError, msg=label):
				doc.save(ignore_permissions=True)

	def test_indicator_without_method_is_refused(self):
		# lô của chỉ thị trống phương pháp bị T4 từ chối (resolve_ci_batch), nên không làm mặc định được
		ci = make_item("CI6-ANY-A122", "Chemical Indicator", ci_class="6").name
		doc = make_set_type("A122D", method="Plasma")
		doc.default_ci_item = ci
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_query_lists_only_usable_indicators_of_the_method(self):
		good = make_item("CI5-Q-STEAM-A122", "Chemical Indicator", method="Steam", ci_class="5").name
		plasma = make_item("CI5-Q-PLASMA-A122", "Chemical Indicator", method="Plasma", ci_class="5").name
		weak = make_item("CI4-Q-STEAM-A122", "Chemical Indicator", method="Steam", ci_class="4").name
		rows = set_type_api.ci_item_query(txt="Q-", filters={"method": "Steam"})
		codes = [row[0] for row in rows]
		self.assertIn(good, codes)
		self.assertNotIn(plasma, codes)
		self.assertNotIn(weak, codes)

	def test_indicator_is_part_of_create_and_copy_headers(self):
		self.assertIn("default_ci_item", bom_versions.HEADER_FIELDS)
		self.assertIn("default_ci_item", bom_versions.COPY_FIELDS)


class TestProcessingDefaultsTab(IsolatedTestCase):
	def test_pack_type_indicator_and_programs_share_one_tab(self):
		meta = frappe.get_meta("Instrument Set Type")
		order = [field.fieldname for field in meta.fields]
		tab = order.index("tab_programs")
		self.assertEqual(meta.get_field("tab_programs").label, "Processing Defaults")
		following = order[tab + 1 : order.index("tab_history")]
		for fieldname in ("default_pack_type", "default_ci_item", "shelf_life_days", "programs"):
			self.assertIn(fieldname, following)
		self.assertNotIn("gtin", following)
