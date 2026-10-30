"""RPC tracecore.v1.recall.* (FEAT-029, SCR-14): lập lệnh, xác nhận gói, đóng lệnh từ Desk."""

import frappe

from tracecore.reprocessing.tests.test_usage import issue
from tracecore.tests import factories
from tracecore.tests.factories import make_department, make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import recall as api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestRecallApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user("th-api-r02@example.com", ["TC R02"])
		self.r09 = make_user("th-api-r09@example.com", ["TC R09"])
		self.ward = make_user("th-api-r08@example.com", ["TC R08"])
		self.dept = make_department("Khoa API thu hồi")
		make_employee(first_name="Điều dưỡng API", department=self.dept, user_id=self.ward)
		equipment = factories.make_sterilizer(name="Máy hấp API thu hồi").name
		program = factories.make_sterilize_program(equipment)
		self.load = factories.make_load(equipment, program, [factories.make_load_ready_pack()]).name
		self.pack = issue(factories.make_stocked_pack(), self.dept)
		frappe.db.set_value("Pack", self.pack.name, "load", self.load, update_modified=False)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_open_confirm_and_close(self):
		frappe.set_user(self.r02)
		opened = api.create(load=self.load, reason="Rò hơi")
		self.assertTrue(opened["ok"])
		name = opened["recall"]["name"]
		self.assertEqual((opened["recall"]["pack_count"], opened["recall"]["confirmed_count"]), (1, 0))
		self.assertEqual(api.close(recall=name)["error"]["code"], "RECALL_INCOMPLETE")
		frappe.set_user(self.ward)
		confirmed = api.confirm_pack(recall=name, pack=self.pack.name, note="Đã trả về CSSD")
		self.assertEqual(confirmed["recall"]["confirmed_count"], 1)
		frappe.set_user(self.r02)
		self.assertEqual(api.close(recall=name)["recall"]["status"], "Closed")

	def test_rejections_are_bodies_and_audited(self):
		frappe.set_user(self.r09)
		denied = api.create(load=self.load, reason="x")
		self.assertEqual(denied["error"]["code"], "RECALL_NOT_ALLOWED")
		self.assertTrue(frappe.db.exists("Audit Log", {"action": "Reject", "reason": "RECALL_NOT_ALLOWED"}))
		frappe.set_user(self.r02)
		self.assertEqual(api.create(lot="LO-KHONG-CO", reason="x")["error"]["code"], "RECALL_EMPTY")

	def test_load_or_lot_is_required(self):
		frappe.set_user(self.r02)
		with self.assertRaises(frappe.ValidationError):
			api.create(reason="x")
