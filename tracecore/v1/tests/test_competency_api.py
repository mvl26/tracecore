"""RPC tracecore.v1.competency.* — ma trận năng lực SCR-20 trên Desk (FEAT-037, FR-M4-03.4, API-M4-02)."""

import frappe
from frappe.utils import add_days, now_datetime

from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import competency as api
from tracecore.v1.tests.station_fixtures import make_station_employee

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
STATION = "TR-004"


class TestCompetencyApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user("comp-api-r02@example.com", ["TC R02"])
		self.r04 = make_user("comp-api-r04@example.com", ["TC R04"])
		self.employee = make_station_employee(make_user("comp-api-worker@example.com", ["TC R04"])).name
		self.addCleanup(frappe.set_user, "Administrator")

	def until(self, days=30):
		return str(add_days(now_datetime(), days))

	def test_matrix_returns_stations_employees_and_edit_flag(self):
		frappe.set_user(self.r02)
		result = api.matrix()
		self.assertTrue(result["ok"])
		self.assertTrue(result["can_edit"])
		self.assertIn(STATION, [station["name"] for station in result["stations"]])
		self.assertIn(self.employee, [row["employee"] for row in result["employees"]])

	def test_grant_and_revoke_round_trip(self):
		frappe.set_user(self.r02)
		granted = api.grant(self.employee, STATION, self.until(), required_certificates='["Sterilization"]')
		self.assertTrue(granted["ok"])
		cell = next(r for r in api.matrix()["employees"] if r["employee"] == self.employee)["cells"][STATION]
		self.assertEqual((cell["state"], cell["missing"]), ("suspended", ["Sterilization"]))
		duplicate = api.grant(self.employee, STATION, self.until())
		self.assertEqual((duplicate["ok"], duplicate["error"]["code"]), (False, "COMPETENCY_EXISTS"))
		self.assertTrue(api.revoke(granted["name"], "Đổi trạm")["ok"])
		cell = next(r for r in api.matrix()["employees"] if r["employee"] == self.employee)["cells"][STATION]
		self.assertEqual(cell["state"], "none")

	def test_temporary_grant_over_24_hours_is_a_business_rejection(self):
		frappe.set_user(self.r02)
		result = api.grant(
			self.employee, STATION, str(add_days(now_datetime(), 2)), is_temporary=1, reason="Thiếu người"
		)
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "TEMP_TOO_LONG"))

	def test_roles_without_permission_get_a_business_rejection(self):
		frappe.set_user(self.r04)
		self.assertEqual(api.matrix()["error"]["code"], "COMPETENCY_NOT_ALLOWED")
		self.assertEqual(
			api.grant(self.employee, STATION, self.until())["error"]["code"], "COMPETENCY_NOT_ALLOWED"
		)

	def test_guest_is_refused_and_bad_certificate_list_is_a_validation_error(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.matrix()
		frappe.set_user(self.r02)
		with self.assertRaises(frappe.ValidationError):
			api.grant(self.employee, STATION, self.until(), required_certificates="not-json")
