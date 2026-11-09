"""Sự cố phơi nhiễm vật sắc nhọn M10 → Occupational Exposure qua hook (FEAT-071; FR-M10-06.1, FR-M16-02, FR-M16-02.1;
BRU-OCC-002; UC-55 A1)."""

import frappe

from tracecore.core import extension
from tracecore.occupational_safety import exposure
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.reprocessing import incidents
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

DOCTYPE = "Occupational Exposure"
HOOK = "tracecore_exposure_incident"


class TestExposureIncidentHook(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.department = factories.make_department("PN Kho chất thải")
		self.employee = fx.employee("PN Hộ lý", self.department)

	def _sharps(self, **values):
		return incidents.create(
			{
				"incident_type": "Sharps Exposure",
				"description": "Needle in a general waste bag",
				"employee": self.employee,
				"department": self.department,
				"exposure_source": "Used needle from ward",
				**values,
			}
		)

	def test_hook_is_registered(self):
		self.assertIn("tracecore.occupational_safety.exposure.from_incident", frappe.get_hooks(HOOK))

	@bru("BRU-OCC-002")
	def test_sharps_incident_creates_exactly_one_exposure(self):
		incident = self._sharps()
		rows = frappe.get_all(
			DOCTYPE,
			filters={"incident_capa": incident.name},
			fields=["name", "employee", "department", "exposure_type", "report_channel", "status", "activity"],
		)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row.employee, self.employee)
		self.assertEqual(row.department, self.department)
		self.assertEqual(row.exposure_type, fx.SHARPS)
		self.assertEqual(row.report_channel, "Waste Incident")
		self.assertEqual(row.status, "New")
		# chữ tự do của sự cố không chép sang hồ sơ (có thể chứa thông tin người bệnh)
		self.assertFalse(row.activity)

		# FR-M16-02.1: ghi lại cùng sự cố → vẫn một hồ sơ
		self.assertEqual(extension.run(HOOK, incident), [row.name])
		self.assertEqual(exposure.from_incident(incident), row.name)
		self.assertEqual(frappe.db.count(DOCTYPE, {"incident_capa": incident.name}), 1)

	def test_other_incidents_create_no_exposure(self):
		before = frappe.db.count(DOCTYPE)
		incidents.create(
			{"incident_type": "Waste Spill", "severity": "Low", "description": "Spill", "department": self.department}
		)
		self.assertEqual(frappe.db.count(DOCTYPE), before)
