"""RPC thanh lý (tracecore.v1.set_unit.disposal_*) và chuyển trạng thái thủ công (tracecore.v1.admin) — FEAT-004."""

import frappe

from tracecore.core import station_auth, step_gate
from tracecore.tests import factories
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import admin
from tracecore.v1 import set_unit as api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
PIN = "246813"


class TestDisposalApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r01 = make_user("tla-r01@example.com", ["TC R01"])
		self.r02 = make_user("tla-r02@example.com", ["TC R02"])
		employee = make_employee(first_name="Duyệt", user_id=self.r01).name
		station_auth.set_pin(employee, PIN)
		station_auth.clear_pin_rate_limit(employee)
		self.unit = factories.make_set_unit().name
		factories.make_cycle(self.unit, passed=("T1", "T2", "T3"))
		step_gate.end_of_life(self.unit, "Hết cơ số")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_request_then_approve(self):
		frappe.set_user(self.r02)
		self.assertEqual(api.disposal_request(self.unit, "Mòn")["disposal_status"], "Requested")
		refused = api.disposal_request(self.unit, "Lần 2")
		self.assertEqual((refused["ok"], refused["error"]["code"]), (False, "DISPOSAL_PENDING"))
		frappe.set_user(self.r01)
		self.assertEqual(api.disposal_reject(self.unit, "", PIN)["error"]["code"], "REASON_REQUIRED")
		result = api.disposal_approve(self.unit, "Đồng ý", PIN)
		self.assertEqual((result["ok"], result["status"]), (True, "Disposed"))

	def test_force_transition(self):
		frappe.set_user(self.r02)
		result = admin.force_transition("Set Unit", self.unit, "Processing", "Máy chủ lỗi", "SC-9")
		self.assertTrue(result["ok"])
		self.assertTrue(result["incident"])
		refused = admin.force_transition("Set Unit", self.unit, "Disposed", "x", "SC-9")
		self.assertEqual((refused["ok"], refused["error"]["code"]), (False, "STATUS_INVALID"))
		with self.assertRaises(frappe.ValidationError):
			admin.force_transition("Instrument", self.unit, "Processing", "x", "SC-9")
