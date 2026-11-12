"""A-156 (FEAT-098): quy trình xử lý của loại bộ — nhiệt độ cao / nhiệt độ thấp / khử khuẩn (FR-M1-03.10)."""

import csv
import os

import frappe

from tracecore.instrument import bom_versions, imports
from tracecore.tests.factories import make_bom, make_instrument, make_set_type
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Instrument Set Type"
DISINFECTION = "Disinfection"


def _line(code, row=1):
	return {"row": row, "instrument": code, "qty": 1, "given_position": None}


class TestRouteField(IsolatedTestCase):
	def test_method_is_the_processing_route_with_three_choices(self):
		field = frappe.get_meta(DOCTYPE).get_field("method")
		self.assertEqual(field.label, "Processing Route")
		self.assertEqual(field.fieldtype, "Select")
		self.assertEqual(field.options.split("\n"), ["Steam", "Plasma", DISINFECTION])
		self.assertTrue(field.reqd)

	def test_import_accepts_the_three_routes(self):
		self.assertEqual(imports.SET_METHODS, ("Steam", "Plasma", DISINFECTION))

	def test_route_labels_are_translated_in_set_type_context(self):
		path = os.path.join(frappe.get_app_path("tracecore"), "translations", "vi.csv")
		with open(path, encoding="utf-8") as handle:
			rows = {(row[0], row[2] if len(row) > 2 else ""): row[1] for row in csv.reader(handle) if row}
		self.assertEqual(rows[("Processing Route", DOCTYPE)], "Quy trình xử lý")
		self.assertEqual(rows[("Steam", DOCTYPE)], "Tiệt khuẩn nhiệt độ cao (hấp)")
		self.assertEqual(rows[("Plasma", DOCTYPE)], "Tiệt khuẩn nhiệt độ thấp (plasma)")
		self.assertEqual(rows[(DISINFECTION, DOCTYPE)], "Khử khuẩn")


class TestDisinfectionBom(IsolatedTestCase):
	@bru("BRU-REP-004")
	def test_disinfection_takes_semi_and_non_critical_instruments(self):
		make_instrument("RT-SEMI", name="Semi", spaulding="Semi-critical", methods=("Steam 134",))
		make_instrument("RT-NON", name="Non", spaulding="Non-critical", methods=("Plasma",))
		rows = [_line("RT-SEMI", 1), _line("RT-NON", 2)]
		self.assertEqual(bom_versions.line_errors(DISINFECTION, rows), [])
		doc = make_set_type("RTD1", method=DISINFECTION, bom=[("RT-SEMI", 1), ("RT-NON", 1)])
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "method"), DISINFECTION)

	@bru("BRU-REP-004")
	def test_disinfection_rejects_critical_instruments(self):
		make_instrument("RT-CRIT", name="Critical", spaulding="Critical", methods=("Steam 134",))
		make_instrument("RT-SEMI2", name="Semi", spaulding="Semi-critical", methods=("Steam 134",))
		errors = bom_versions.line_errors(DISINFECTION, [_line("RT-CRIT", 1), _line("RT-SEMI2", 2)])
		self.assertEqual(
			[(e["row"], e["instrument"], e["code"]) for e in errors], [(1, "RT-CRIT", "INCOMPATIBLE")]
		)
		self.assertIn("Critical", errors[0]["message"])

	@bru("BRU-REP-004")
	def test_changing_to_disinfection_rechecks_bom(self):
		make_instrument("RT-CRIT3", name="Critical three", spaulding="Critical", methods=("Steam 134",))
		set_type = make_set_type("RTD3")
		make_bom(set_type, [("RT-CRIT3", 1)], version=1)
		doc = frappe.get_doc(DOCTYPE, "RTD3")
		doc.method = DISINFECTION
		with self.assertRaises(frappe.ValidationError) as raised:
			doc.save()
		self.assertIn("RT-CRIT3", str(raised.exception))
		self.assertEqual(frappe.db.get_value(DOCTYPE, "RTD3", "method"), "Steam")

	def test_disinfection_takes_no_chemical_indicator_class(self):
		make_instrument("RT-SEMI4", name="Semi four", spaulding="Semi-critical", methods=("Steam 134",))
		doc = make_set_type("RTD4", method=DISINFECTION, bom=[("RT-SEMI4", 1)])
		doc.reload()
		doc.ci_class = "5"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.ci_class = "Not Needed"
		doc.save()
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "ci_class"), "Not Needed")
