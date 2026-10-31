"""Rà soát máy in và agent của các trạm, chỉ đọc (ticket T2 31/10/2026, mục 4; A-72)."""

import frappe

from tracecore.setup import survey
from tracecore.tests.factories import deactivate_printers
from tracecore.tests.utils import IsolatedTestCase


class TestSurveyPrinters(IsolatedTestCase):
	def test_station_without_an_active_printer_is_flagged(self):
		deactivate_printers("TR-002")
		row = next(row for row in survey.printers() if row["station"] == "TR-002")
		self.assertEqual(row["printers"], [])
		self.assertIn("NO_ACTIVE_PRINTER", row["problems"])

	def test_station_with_a_printer_lists_it_with_the_loaded_label(self):
		deactivate_printers("TR-002")
		printer = frappe.get_doc(
			{
				"doctype": "Printer",
				"printer_name": "ZT-SURVEY",
				"station": "TR-002",
				"is_active": 1,
				"language": "ZPL",
			}
		).insert(ignore_permissions=True)
		row = next(row for row in survey.printers() if row["station"] == "TR-002")
		self.assertEqual([printer["name"] for printer in row["printers"]], [printer.name])
		self.assertNotIn("NO_ACTIVE_PRINTER", row["problems"])

	def test_agent_user_is_reported_per_station(self):
		row = next(row for row in survey.printers() if row["station"] == "TR-002")
		self.assertIn(row["has_agent_user"], (0, 1))

	def test_survey_writes_nothing(self):
		before = (frappe.db.count("Printer"), frappe.db.count("User"), frappe.db.count("Audit Log"))
		survey.printers()
		self.assertEqual(
			before, (frappe.db.count("Printer"), frappe.db.count("User"), frappe.db.count("Audit Log"))
		)
