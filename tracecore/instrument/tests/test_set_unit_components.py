"""A-154 (FEAT-096): thành phần bộ và loại chỉ thị trên form Set Unit (FR-M1-06.5)."""

import frappe

from tracecore.instrument import set_history
from tracecore.tests.factories import make_bom, make_cycle, make_set_type, make_set_unit
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _lines(summary):
	return [(row["position"], row["instrument"], row["qty"]) for row in summary["components"]]


class TestSetUnitComponents(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.set_type = make_set_type("A154S", method="Steam").name
		make_bom(self.set_type, [("A154-KEP", 2), ("A154-KEO", 1), ("A154-NHIP", 3)])
		self.unit = make_set_unit(self.set_type).name

	def test_unpinned_set_shows_the_effective_version(self):
		summary = set_history.summary(self.unit)
		self.assertFalse(summary["bom_pinned"])
		self.assertEqual(summary["components_version"], 1)
		self.assertEqual(_lines(summary), [(1, "A154-KEP", 2), (2, "A154-KEO", 1), (3, "A154-NHIP", 3)])
		self.assertEqual(summary["components_total"], 6)
		names = [row["instrument_name"] for row in summary["components"]]
		self.assertTrue(all(names))

	def test_pinned_version_wins_over_a_newer_version(self):
		make_cycle(self.unit, passed=())  # ghim v1 khi mở chu trình
		make_bom(self.set_type, [("A154-KEP", 1)], version=2)
		summary = set_history.summary(self.unit)
		self.assertTrue(summary["bom_pinned"])
		self.assertEqual(summary["components_version"], 1)
		self.assertEqual(summary["components_total"], 6)
		self.assertEqual(len(summary["components"]), 3)

	def test_summary_carries_the_set_type_indicator_class(self):
		self.assertEqual(set_history.summary(self.unit)["ci_class"], "")
		frappe.db.set_value("Instrument Set Type", self.set_type, "ci_class", "4")
		self.assertEqual(set_history.summary(self.unit)["ci_class"], "4")

	def test_set_type_without_bom_gives_an_empty_list(self):
		bare = make_set_unit(make_set_type("A154E", method="Steam").name).name
		summary = set_history.summary(bare)
		self.assertEqual(summary["components"], [])
		self.assertEqual(summary["components_total"], 0)

	def test_summary_carries_the_set_type_processing_route(self):
		# A-156 (FR-M1-03.10): form Set Unit hiện Quy trình xử lý của loại bộ
		self.assertEqual(set_history.summary(self.unit)["processing_route"], "Steam")
		frappe.db.set_value("Instrument Set Type", self.set_type, "method", "Plasma")
		self.assertEqual(set_history.summary(self.unit)["processing_route"], "Plasma")

	def test_set_unit_form_shows_the_processing_route_row(self):
		path = frappe.get_app_path("tracecore", "instrument", "doctype", "set_unit", "set_unit.js")
		with open(path, encoding="utf-8") as handle:
			script = handle.read()
		self.assertIn('__("Processing Route", null, "Instrument Set Type")', script)
		self.assertIn('__(s.processing_route, null, "Instrument Set Type")', script)
