"""RPC tracecore.v1.exposure.* (FEAT-071; FR-M16-01, 01.1, 03, 04, 05; UC-55 bước 1-5, A2, A4; NFR-AVAIL-05; A-137 Q2,
Q4): phiên thẻ PDA idempotent, phát lại offline, Cổng khoa báo thay cùng khoa, màn SCR-64."""

import uuid
from datetime import timedelta

import frappe
from frappe.utils import add_to_date, now_datetime, today

from tracecore.core import notification
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.tests.factories import make_department, make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import exposure as api
from tracecore.v1 import station as station_api

CARD = "PN-R08-CARD"
TS = "2026-11-09T09:00:00+07:00"
DOCTYPE = "Occupational Exposure"
STATION = "TR-PN-PDA"


def _iso(dt):
	return dt.strftime("%Y-%m-%dT%H:%M:%S+07:00")


def make_exposure_station():
	if not frappe.db.exists("Zone Station", STATION):
		zone = frappe.get_doc(
			{
				"doctype": "Zone Station",
				"zone_station_name": "PN Ward zone",
				"is_zone": 1,
				"zone_type": "Department",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Zone Station",
				"is_zone": 0,
				"is_active": 1,
				"zone_station_name": "PN Ward PDA",
				"parent_zone": zone.name,
				"functions": [{"station_function": "EXPOSURE"}],
			}
		).insert(ignore_permissions=True, set_name=STATION)
	return STATION


class ExposureApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		notification.ensure_default_rules()
		fx.thresholds()
		fx.clear_templates()
		self.department = make_department("PN Khoa API")
		self.other_department = make_department("PN Khoa khác API")
		self.user = make_user("os-api-r08@example.com", ["TC R08"])
		self.employee = make_employee(
			card=CARD,
			first_name="PN API Nurse",
			user_id=self.user,
			department=self.department,
			company=frappe.db.get_value("Company", {}, "name"),
		).name
		self.colleague = fx.employee("PN API Colleague", self.department)
		self.stranger = fx.employee("PN API Stranger", self.other_department)
		self.r11 = make_user("os-api-r11@example.com", ["TC R11"])
		self.r13 = make_user("os-api-r13@example.com", ["TC R13"])

	def headers(self, key=None, **extra):
		return request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), **extra})


class TestPdaReport(ExposureApiCase):
	def setUp(self):
		super().setUp()
		self.station = make_exposure_station()
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": self.employee,
				"station": self.station,
				"valid_from": now - timedelta(hours=1),
				"valid_until": now + timedelta(hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.token = station_api.login(CARD, self.station, client_ts=TS)["session"]["token"]

	def report(self, key=None, replay=False, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		kwargs.setdefault("station", self.station)
		kwargs.setdefault("client_ts", TS)
		kwargs.setdefault("token", self.token)
		kwargs.setdefault("exposure_type", fx.SHARPS)
		kwargs.setdefault("occurred_at", _iso(add_to_date(now_datetime(), minutes=-20)))
		extra = {"X-TC-Station": self.station}
		if replay:
			extra["X-TC-Replay"] = "1"
		with self.headers(key, **extra):
			return api.report(**kwargs)

	def test_report_creates_record_for_session_employee_and_notifies_r11(self):
		result = self.report(
			activity="Recapping", device="Needle", source_known="Yes", source_patient_code="BN0077"
		)
		self.assertTrue(result["ok"], result)
		name = result["exposure"]["name"]
		doc = frappe.get_doc(DOCTYPE, name)
		self.assertEqual(doc.employee, self.employee)
		self.assertEqual(doc.report_channel, "PDA")
		self.assertEqual(doc.source_patient_code_masked, "***0077")
		self.assertIn("procedure", result["exposure"])
		self.assertNotIn("BN0077", frappe.as_json(result))
		self.assertTrue(
			frappe.db.exists(
				"Notification Delivery",
				{"event_code": "EXPOSURE_REPORTED", "recipient": self.r11, "ref_name": name},
			)
		)

	def test_same_key_creates_one_record(self):
		"""NFR-AVAIL-05: gửi lại cùng X-Idempotency-Key không tạo trùng."""
		key = str(uuid.uuid4())
		occurred = _iso(add_to_date(now_datetime(), minutes=-20))
		first = self.report(key=key, occurred_at=occurred)
		second = self.report(key=key, occurred_at=occurred)
		self.assertEqual(first["exposure"]["name"], second["exposure"]["name"])
		self.assertEqual(frappe.db.count(DOCTYPE, {"employee": self.employee}), 1)

	def test_offline_replay_uses_client_time_as_report_time(self):
		"""UC-55 A2: báo lúc mất mạng, gửi khi có mạng (X-TC-Replay); giờ báo = client_ts, không trùng khi gửi lại."""
		reported = now_datetime().replace(microsecond=0)
		key = str(uuid.uuid4())
		occurred = _iso(add_to_date(reported, hours=-1))
		result = self.report(key=key, replay=True, occurred_at=occurred, client_ts=_iso(reported))
		self.assertTrue(result["ok"], result)
		doc = frappe.get_doc(DOCTYPE, result["exposure"]["name"])
		self.assertEqual(str(doc.reported_at), str(reported))
		self.assertAlmostEqual(doc.minutes_to_report, 60, delta=1)
		again = self.report(key=key, replay=True, occurred_at=occurred, client_ts=_iso(reported))
		self.assertEqual(again["exposure"]["name"], doc.name)

	def test_offline_snapshot_gives_patient_key_to_exposure_station(self):
		"""PDA chỉ có chức năng EXPOSURE vẫn mã hóa được mã BN nguồn khi mất mạng."""
		from tracecore.v1 import sync as sync_api

		frappe.local.response.pop("http_status_code", None)
		with self.headers(**{"X-TC-Station": self.station}):
			data = sync_api.snapshot(station=self.station, client_ts=TS, token=self.token)
		self.assertTrue(data["offline"], data)
		self.assertEqual(data["function"], "EXPOSURE")
		self.assertTrue(data["patient_key"])

	def test_future_time_rejected_with_body(self):
		result = self.report(occurred_at=_iso(add_to_date(now_datetime(), hours=2)))
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "EXPOSURE_TIME_INVALID")
		self.assertEqual(frappe.local.response.get("http_status_code"), 422)

	def test_bad_time_format_is_400(self):
		from tracecore.v1._common import BadRequestError

		with self.assertRaises(BadRequestError):
			self.report(occurred_at="09:00")


class TestPortalReport(ExposureApiCase):
	def portal(self, key=None, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		kwargs.setdefault("client_ts", TS)
		kwargs.setdefault("exposure_type", fx.SPLASH)
		kwargs.setdefault("occurred_at", _iso(add_to_date(now_datetime(), minutes=-10)))
		with self.headers(key):
			return api.report_portal(**kwargs)

	def test_staff_reports_for_self(self):
		frappe.set_user(self.user)
		result = self.portal()
		self.assertTrue(result["ok"], result)
		doc = frappe.get_doc(DOCTYPE, result["exposure"]["name"])
		self.assertEqual((doc.employee, doc.report_channel), (self.employee, "Department Portal"))
		self.assertEqual([row.name for row in api.my_records()], [doc.name])

	def test_r08_reports_for_colleague_of_same_department_only(self):
		frappe.set_user(self.user)
		ok = self.portal(employee=self.colleague)
		self.assertTrue(ok["ok"], ok)
		self.assertEqual(frappe.db.get_value(DOCTYPE, ok["exposure"]["name"], "employee"), self.colleague)
		blocked = self.portal(employee=self.stranger)
		self.assertFalse(blocked["ok"])
		self.assertEqual(blocked["error"]["code"], "EXPOSURE_NOT_ALLOWED")
		self.assertEqual(frappe.local.response.get("http_status_code"), 403)

	def test_user_without_staff_record_is_told_to_ask_for_help(self):
		frappe.set_user(make_user("os-api-nostaff@example.com", ["TC R03"]))
		result = self.portal()
		self.assertEqual(result["error"]["code"], "EXPOSURE_NO_EMPLOYEE")

	def test_portal_context_lists_colleagues_for_proxy(self):
		frappe.set_user(self.user)
		context = api.portal_context()
		self.assertEqual(context["employee"], self.employee)
		self.assertIn(self.colleague, [row.employee for row in context["colleagues"]])
		self.assertNotIn(self.stranger, [row.employee for row in context["colleagues"]])
		self.assertEqual(len(context["types"]), 5)

	def test_guest_cannot_report(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			self.portal()

	def test_replay_report_time_is_clamped_between_exposure_and_now(self):
		"""Gói phát lại không đặt được giờ báo trước giờ phơi nhiễm hay ở tương lai."""
		frappe.set_user(self.user)
		occurred = add_to_date(now_datetime(), hours=-2).replace(microsecond=0)
		frappe.local.response.pop("http_status_code", None)
		with self.headers(**{"X-TC-Replay": "1"}):
			result = api.report_portal(
				exposure_type=fx.SPLASH,
				occurred_at=_iso(occurred),
				client_ts=_iso(add_to_date(occurred, hours=-5)),
			)
		self.assertTrue(result["ok"], result)
		frappe.set_user("Administrator")
		self.assertEqual(
			str(frappe.db.get_value(DOCTYPE, result["exposure"]["name"], "reported_at")), str(occurred)
		)


class TestScreenApi(ExposureApiCase):
	def setUp(self):
		super().setUp()
		fx.template(steps=(("Step 1", 0), ("Step 2", 30)))
		frappe.set_user(self.user)
		with self.headers():
			self.name = api.report_portal(
				exposure_type=fx.SHARPS,
				occurred_at=_iso(add_to_date(now_datetime(), hours=-1)),
				source_known="Yes",
				source_patient_code="BN-SCR64-9876",
				client_ts=TS,
			)["exposure"]["name"]
		frappe.set_user("Administrator")

	def test_r11_sees_records_and_r13_only_totals(self):
		frappe.set_user(self.r11)
		data = api.dashboard_data()
		self.assertTrue(data["is_manager"])
		row = next(r for r in data["records"] if r.name == self.name)
		self.assertEqual(row.status, "New")
		self.assertNotIn("BN-SCR64-9876", frappe.as_json(data))
		frappe.set_user(self.r13)
		data = api.dashboard_data()
		self.assertFalse(data["is_manager"])
		self.assertNotIn("records", data)
		self.assertGreaterEqual(data["kpis"]["year_total"], 1)
		with self.assertRaises(frappe.PermissionError):
			api.detail(self.name)

	def test_handling_then_steps_done_completes(self):
		frappe.set_user(self.r11)
		blocked = api.record_handling(self.name, first_aid_done=1)
		self.assertEqual(blocked["error"]["code"], "EXPOSURE_HANDLING_INCOMPLETE")
		result = api.record_handling(
			self.name, first_aid_done=1, prophylaxis="Given", prophylaxis_started_at=str(now_datetime())
		)
		self.assertTrue(result["ok"], result)
		detail = result["detail"]
		self.assertEqual(detail["status"], "Following Up")
		self.assertEqual(len(detail["followups"]), 2)
		for row in detail["followups"]:
			detail = api.followup_done(self.name, row["name"], today())["detail"]
		self.assertEqual(detail["status"], "Completed")

	def test_reveal_and_cancel(self):
		frappe.set_user(self.r11)
		self.assertEqual(api.reveal_source_code(self.name, "")["error"]["code"], "REASON_REQUIRED")
		self.assertEqual(
			api.reveal_source_code(self.name, "Source follow-up")["source_patient_code"], "BN-SCR64-9876"
		)
		self.assertEqual(api.cancel(self.name, "")["error"]["code"], "REASON_REQUIRED")
		self.assertEqual(api.cancel(self.name, "Duplicate")["detail"]["status"], "Cancelled")

	def test_staff_cannot_open_screen_rpcs(self):
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			api.dashboard_data()
		with self.assertRaises(frappe.PermissionError):
			api.record_handling(self.name, prophylaxis="Refused")
