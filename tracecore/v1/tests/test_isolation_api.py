"""RPC tracecore.v1.isolation.* — SCR-60 Lệnh cách ly & phòng cách ly (FEAT-068; FR-M14-06, FR-M14-07; UC-52; A-146)."""

import uuid

import frappe
from frappe.utils import today

from tracecore.microbiology import isolation
from tracecore.microbiology.tests import factories as mf
from tracecore.microbiology.tests.test_isolation import make_clinical, make_dept_user, make_room
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import isolation as api

TS = "2026-11-10T09:00:00+07:00"


class IsolationApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.ward = make_clinical("CLA Khoa Hồi sức")
		self.other = make_clinical("CLA Khoa Nội")
		for department in (self.ward, self.other):
			frappe.db.delete(isolation.DOCTYPE, {"department": department})
			frappe.db.delete(isolation.ROOM_DOCTYPE, {"department": department})
		self.r08 = make_dept_user("cla-r08@example.com", "TC R08", self.ward)
		self.r12 = make_dept_user("cla-r12@example.com", "TC R12", self.ward)
		self.r11 = make_user("cla-r11@example.com", ["TC R11"])
		self.r13 = make_user("cla-r13@example.com", ["TC R13"])
		self.room = make_room(self.ward, code="PCL-CLA-01", beds=2)

	def call(self, fn, key=None, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4())}):
			return fn(**kwargs)

	def create_args(self, **values):
		args = {
			"department": self.ward,
			"patient_code": "BN0004821",
			"precaution_type": "Contact",
			"reason": isolation.REASON_COMMUNICABLE,
			"isolation_room": self.room.name,
			"client_ts": TS,
		}
		args.update(values)
		return args


class TestCreateAndList(IsolationApiCase):
	def test_department_user_creates_and_sees_own_open_list(self):
		frappe.set_user(self.r12)
		result = self.call(api.create_order, **self.create_args())
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["order"]["patient_code_masked"], "***4821")
		self.assertNotIn("patient_code", result["order"])
		self.call(api.create_order, **self.create_args(patient_code="BN0001111", department=self.ward))
		frappe.set_user("Administrator")
		isolation.create_order(
			{
				"department": self.other,
				"patient_code": "BN0002222",
				"precaution_type": "Droplet",
				"reason": isolation.REASON_SUSPECTED,
			}
		)
		frappe.set_user(self.r12)
		context = api.portal_context()
		self.assertEqual([row["name"] for row in context["departments"]], [self.ward])
		self.assertEqual({row["department"] for row in context["orders"]}, {self.ward})
		self.assertEqual(len(context["orders"]), 2)
		self.assertEqual([row["name"] for row in context["rooms"]], [self.room.name])
		self.assertEqual(context["rooms"][0]["occupied"], 2)

	def test_missing_precaution_returns_inline_block(self):
		frappe.set_user(self.r08)
		result = self.call(api.create_order, **self.create_args(precaution_type=""))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "ISOLATION_PRECAUTION_REQUIRED")
		self.assertFalse(frappe.db.exists(isolation.DOCTYPE, {"department": self.ward}))

	def test_other_department_blocked(self):
		frappe.set_user(self.r08)
		result = self.call(api.create_order, **self.create_args(department=self.other, isolation_room=""))
		self.assertEqual(result["error"]["code"], "ISOLATION_NOT_ALLOWED")

	def test_roles_without_write_rejected(self):
		frappe.set_user(self.r13)
		with self.assertRaises(frappe.PermissionError):
			self.call(api.create_order, **self.create_args())

	def test_bedside_warning_returned(self):
		frappe.set_user(self.r08)
		result = self.call(api.create_order, **self.create_args(isolation_room=""))
		self.assertTrue(result["ok"])
		self.assertTrue(result["order"]["bedside_isolation"])
		self.assertTrue(result["warnings"])


class TestClose(IsolationApiCase):
	@bru("BRU-MDR-003")
	def test_department_cannot_close_mdro_order_supervisor_can(self):
		order = isolation.create_order(
			{
				"department": self.ward,
				"patient_code": "BN0004821",
				"precaution_type": "Contact",
				"reason": isolation.REASON_MDRO,
			}
		)
		frappe.set_user(self.r08)
		denied = self.call(api.close_order, order=order.name, end_reason="Âm tính", client_ts=TS)
		self.assertEqual(denied["error"]["code"], "ISOLATION_MDRO_CLOSE_DENIED")
		missing = self.call(api.close_order, order=order.name, end_reason="", client_ts=TS)
		self.assertEqual(missing["error"]["code"], "ISOLATION_END_REASON_REQUIRED")
		frappe.set_user(self.r11)
		closed = self.call(api.close_order, order=order.name, end_reason="Âm tính", client_ts=TS)
		self.assertTrue(closed["ok"], closed)
		self.assertEqual(frappe.db.get_value(isolation.DOCTYPE, order.name, "status"), isolation.CLOSED)

	def test_cancel_by_supervisor(self):
		order = isolation.create_order(
			{
				"department": self.ward,
				"patient_code": "BN0004821",
				"precaution_type": "Contact",
				"reason": isolation.REASON_SUSPECTED,
			}
		)
		frappe.set_user(self.r11)
		result = self.call(api.cancel_order, order=order.name, reason="Nhập nhầm", client_ts=TS)
		self.assertTrue(result["ok"])
		self.assertEqual(frappe.db.get_value(isolation.DOCTYPE, order.name, "docstatus"), 2)


class TestOverview(IsolationApiCase):
	def test_supervisor_sees_all_departments_coverage_and_prefill(self):
		mf.make_organism()
		if not frappe.db.exists("MDRO Rule", {"rule_code": "T-CRE", "docstatus": 1}):
			mf.make_rule()
		frappe.db.delete("Microbiology Isolate", {"lab_sample_id": "CLA-L-1"})
		isolate = mf.new_isolate(lab="CLA-L-1", department=self.ward, patient="BN0007730")
		isolation.create_order(
			{
				"department": self.other,
				"patient_code": "BN0002222",
				"precaution_type": "Droplet",
				"reason": isolation.REASON_SUSPECTED,
			}
		)
		frappe.set_user(self.r11)
		data = api.overview(isolate=isolate.name)
		self.assertTrue(data["can_write"])
		self.assertIn(self.other, {row["department"] for row in data["orders"]})
		self.assertEqual(data["prefill"]["patient_code_masked"], "***7730")
		self.assertEqual(data["prefill"]["reason"], isolation.REASON_MDRO)
		mine = {row["department"]: row for row in data["coverage"]["departments"]}
		self.assertTrue(mine[self.ward]["covered"])
		self.assertFalse(mine[self.other]["covered"])

	def test_r13_sees_rate_without_orders(self):
		frappe.set_user(self.r13)
		data = api.overview()
		self.assertFalse(data["can_write"])
		self.assertEqual(data["orders"], [])
		self.assertIsNotNone(data["coverage"]["total"])

	def test_department_user_cannot_open_desk_screen(self):
		frappe.set_user(self.r08)
		with self.assertRaises(frappe.PermissionError):
			api.overview()

	def test_portal_prefill_only_for_own_department_isolate(self):
		mf.make_organism()
		if not frappe.db.exists("MDRO Rule", {"rule_code": "T-CRE", "docstatus": 1}):
			mf.make_rule()
		frappe.db.delete("Microbiology Isolate", {"lab_sample_id": ["in", ["CLA-L-2", "CLA-L-3"]]})
		mine = mf.new_isolate(lab="CLA-L-2", department=self.ward, patient="BN0005555")
		theirs = mf.new_isolate(lab="CLA-L-3", department=self.other, patient="BN0006666")
		frappe.set_user(self.r08)
		self.assertEqual(api.portal_context(isolate=mine.name)["prefill"]["isolate"], mine.name)
		self.assertIsNone(api.portal_context(isolate=theirs.name)["prefill"])
		created = self.call(
			api.create_order,
			isolate=mine.name,
			precaution_type="Contact",
			reason=isolation.REASON_MDRO,
			isolation_room="",
			client_ts=TS,
		)
		self.assertTrue(created["ok"], created)
		self.assertEqual(created["order"]["patient_code_masked"], "***5555")
		self.assertTrue(created["order"]["is_mdro"])
		self.assertEqual(today(), str(created["order"]["start_at"])[:10])
