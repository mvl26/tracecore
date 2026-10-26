"""RPC tracecore.v1.incident.* (FEAT-030, SCR-15): tạo, chuyển trạng thái, hoàn thành hành động, đóng, hủy từ Desk."""

import frappe
from frappe.utils import add_days, today

from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import incident as api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestIncidentApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user("nc-api-r02@example.com", ["TC R02"])
		self.r09 = make_user("nc-api-r09@example.com", ["TC R09"])
		self.tech = make_user("nc-api-r05@example.com", ["TC R05"])
		self.equipment = factories.make_equipment(
			name="Máy NC API", serial="NCA-" + frappe.generate_hash(length=8)
		).name
		self.addCleanup(frappe.set_user, "Administrator")

	def test_technician_reports_and_supervisor_runs_the_workflow(self):
		frappe.set_user(self.tech)
		created = api.create(
			incident_type="Equipment Fault",
			severity="Medium",
			description="Rò hơi cửa",
			equipment=self.equipment,
		)
		self.assertTrue(created["ok"])
		name = created["incident"]["name"]
		self.assertEqual(created["incident"]["status"], "New")

		frappe.set_user(self.r02)
		self.assertEqual(api.advance(incident=name, step="start_analysis")["incident"]["status"], "Analysis")
		actions = [
			{
				"action_type": "Corrective",
				"description": "Thay gioăng",
				"responsible": self.tech,
				"due_date": add_days(today(), 2),
			}
		]
		planned = api.plan_capa(incident=name, root_cause="Gioăng mòn", actions=frappe.as_json(actions))
		self.assertEqual(planned["incident"]["status"], "CAPA")
		row = frappe.get_doc("Incident CAPA", name).actions[0].name
		frappe.set_user(self.tech)
		self.assertTrue(api.complete_action(incident=name, action=row, result="Đã thay")["ok"])
		frappe.set_user(self.r02)
		self.assertEqual(
			api.advance(incident=name, step="submit_verification")["incident"]["status"], "Verification"
		)
		closed = api.close(incident=name, verification_result="Ba mẻ Đạt")
		self.assertEqual(closed["incident"]["status"], "Closed")

	def test_business_rejection_is_a_body_not_an_exception(self):
		frappe.set_user(self.tech)
		missing = api.create(incident_type="Other", severity="Low", description="Không liên kết")
		self.assertFalse(missing["ok"])
		self.assertEqual(missing["error"]["code"], "INCIDENT_LINK_REQUIRED")
		name = api.create(incident_type="Other", severity="Low", description="x", equipment=self.equipment)[
			"incident"
		]["name"]
		denied = api.advance(incident=name, step="start_analysis")
		self.assertEqual(denied["error"]["code"], "INCIDENT_NOT_ALLOWED")
		self.assertTrue(frappe.db.exists("Audit Log", {"action": "Reject", "reason": "INCIDENT_NOT_ALLOWED"}))

	def test_role_without_write_cannot_create(self):
		# ma trận DT-INCIDENT: R09 chỉ đọc
		frappe.set_user(self.r09)
		with self.assertRaises(frappe.PermissionError):
			api.create(incident_type="Other", severity="Low", description="x", equipment=self.equipment)

	def test_unknown_step_is_rejected(self):
		frappe.set_user(self.r02)
		name = api.create(incident_type="Other", severity="Low", description="x", equipment=self.equipment)[
			"incident"
		]["name"]
		with self.assertRaises(frappe.ValidationError):
			api.advance(incident=name, step="close")
