"""Load Indicator Result (FEAT-023 D1; FR-M2-11; BRU-REP-006): chỉ dịch vụ giải phóng ghi, chỉ thị theo mẻ hoặc gói."""

import frappe

from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestLoadIndicatorResult(IsolatedTestCase):
	def test_only_the_release_service_writes(self):
		doc = frappe.get_doc(
			{"doctype": "Load Indicator Result", "indicator": "chemical_class_5", "result": "Pass"}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_indicator_and_result_options(self):
		meta = frappe.get_meta("Load Indicator Result")
		self.assertEqual(
			meta.get_field("indicator").options.split("\n"),
			["bowie_dick", "chemical_class_5", "chemical_plasma", "biological"],
		)
		self.assertEqual(meta.get_field("result").options.split("\n"), ["Pending", "Pass", "Fail"])
