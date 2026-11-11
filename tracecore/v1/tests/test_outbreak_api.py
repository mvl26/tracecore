"""RPC tracecore.v1.outbreak.* — SCR-61, banner SCR-58, Cổng khoa khai báo (FEAT-069; FR-M14-09, FR-M14-10, FR-M13-13;
UC-53, UC-50; A-150)."""

import json
import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

from tracecore.microbiology import clusters, notifiable, outbreaks
from tracecore.microbiology.tests import outbreak_fixtures as of
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import outbreak as api

TS = "2026-11-10T09:00:00+07:00"


class OutbreakApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.icu = of.make_clinical("ODA Hồi sức")
		self.ward = of.make_clinical("ODA Khoa Nội")
		frappe.db.delete(notifiable.DOCTYPE, {"department": ["in", [self.icu, self.ward]]})
		self.r01 = make_user("oda-r01@example.com", ["TC R01"])
		self.r11 = make_user("oda-r11@example.com", ["TC R11"])
		self.r13 = make_user("oda-r13@example.com", ["TC R13"])
		self.r12 = of.make_dept_user("oda-r12@example.com", "TC R12", self.icu)
		self.disease = of.make_disease("T-LAO", "Lao phổi", "B")
		of.set_hours(a=12, b=24)

	def call(self, fn, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
			return fn(client_ts=TS, **kwargs)

	def open(self):
		frappe.set_user(self.r01)
		result = self.call(
			api.open_outbreak,
			title="Cụm CRE",
			organism_or_disease="CRE",
			department=self.icu,
			departments=json.dumps([self.ward]),
			start_date=today(),
		)
		self.assertTrue(result["ok"], result)
		return result["outbreak"]["name"]


class TestOutbreakApi(OutbreakApiCase):
	def test_open_add_case_action_end_flow(self):
		name = self.open()
		frappe.set_user(self.r11)
		result = self.call(
			api.add_case, outbreak=name, source_type="Manual", patient_code="BN0004821", onset_date=today()
		)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["outbreak"]["cases"][0]["patient_code_masked"], "***4821")
		self.assertNotIn("BN0004821", json.dumps(result, default=str))
		result = self.call(
			api.add_action,
			outbreak=name,
			description="Cách ly",
			responsible=self.r11,
			due_date=add_days(today(), 2),
		)
		self.assertEqual(len(result["outbreak"]["actions"]), 1)
		frappe.set_user(self.r01)
		self.assertEqual(
			self.call(api.set_controlled, outbreak=name)["outbreak"]["status"], outbreaks.CONTROLLED
		)
		blocked = self.call(api.end_outbreak, outbreak=name, summary="Kết thúc")
		self.assertFalse(blocked["ok"])
		self.assertEqual(blocked["error"]["code"], "OUTBREAK_CAPA_OPEN")
		row = result["outbreak"]["incidents"][0]["row"]
		ended = self.call(
			api.end_outbreak,
			outbreak=name,
			summary="Kết thúc",
			open_reasons=json.dumps({row: "Còn giám sát VST"}),
		)
		self.assertEqual(ended["outbreak"]["status"], outbreaks.ENDED)

	def test_open_requires_r01_and_fields(self):
		frappe.set_user(self.r11)
		with self.assertRaises(frappe.PermissionError):
			self.call(
				api.open_outbreak, title="x", organism_or_disease="y", department=self.icu, start_date=today()
			)
		frappe.set_user(self.r01)
		result = self.call(
			api.open_outbreak, title="", organism_or_disease="y", department=self.icu, start_date=today()
		)
		self.assertEqual(result["error"]["code"], "OUTBREAK_FIELDS_REQUIRED")

	def test_overview_r01_and_r13(self):
		name = self.open()
		data = api.overview(outbreak=name)
		self.assertTrue(data["can_own"])
		self.assertEqual(data["current"]["name"], name)
		frappe.set_user(self.r13)
		data = api.overview(outbreak=name)
		self.assertIsNone(data["current"])
		self.assertEqual(data["reports"], [])
		self.assertIn(name, [row["name"] for row in data["summary"]])
		self.assertFalse(data["can_work"])

	def test_department_user_cannot_open_screen(self):
		frappe.set_user(self.r12)
		with self.assertRaises(frappe.PermissionError):
			api.overview()

	def test_candidates_lists_unlinked_masked(self):
		name = self.open()
		case = of.make_case(self.icu, today(), "BN-0000002031")
		frappe.set_user(self.r11)
		rows = api.candidates(outbreak=name, source_type="HAI Case")["rows"]
		self.assertIn(case, [row["name"] for row in rows])
		self.call(api.add_case, outbreak=name, source_type="HAI Case", ref=case)
		rows = api.candidates(outbreak=name, source_type="HAI Case")["rows"]
		self.assertNotIn(case, [row["name"] for row in rows])
		isolate = of.make_isolate(self.ward, "ODA-1", "BN-0000005517", today())
		rows = api.candidates(outbreak=name, source_type="Microbiology Isolate")["rows"]
		self.assertIn(isolate, [row["name"] for row in rows])


class TestClusterApi(OutbreakApiCase):
	def test_banner_and_dismiss(self):
		frappe.db.delete(clusters.ALERT_DOCTYPE)
		frappe.db.delete(clusters.RULE_DOCTYPE)
		self.assertFalse(api.cluster_alerts()["configured"])
		of.make_rule(infection_site="Ventilator-associated Pneumonia", min_cases=2)
		of.make_case(self.icu, add_days(today(), -2), "BN-1")
		of.make_case(self.icu, add_days(today(), -1), "BN-2")
		with patch("tracecore.core.notification.emit"):
			alert = clusters.run_daily(getdate(today()))[0]
		frappe.set_user(self.r11)
		banner = api.cluster_alerts()
		self.assertTrue(banner["configured"] and banner["can_review"])
		self.assertEqual(banner["alerts"][0]["name"], alert)
		self.assertEqual(api.overview(alert=alert)["prefill"]["department"], self.icu)
		blocked = self.call(api.dismiss_alert, alert=alert, reason="")
		self.assertEqual(blocked["error"]["code"], "CLUSTER_REASON_REQUIRED")
		self.assertEqual(
			self.call(api.dismiss_alert, alert=alert, reason="Khác chủng")["status"], clusters.DISMISSED
		)
		frappe.set_user(self.r13)
		self.assertFalse(api.cluster_alerts()["can_review"])


class TestReportApi(OutbreakApiCase):
	def test_department_portal_create_and_record(self):
		frappe.set_user(self.r12)
		diagnosed = add_to_date(now_datetime(), hours=-3).strftime("%Y-%m-%dT%H:%M")
		result = self.call(
			api.create_report,
			department=self.icu,
			patient_code="BN0001234",
			disease=self.disease,
			diagnosed_on=diagnosed,
		)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["report"]["state"], notifiable.STATE_WAITING)
		blocked = self.call(
			api.create_report,
			department=self.ward,
			patient_code="BN1",
			disease=self.disease,
			diagnosed_on=diagnosed,
		)
		self.assertEqual(blocked["error"]["code"], "NOTIFIABLE_NOT_ALLOWED")
		context = api.portal_context()
		self.assertEqual([row["name"] for row in context["departments"]], [self.icu])
		self.assertEqual(len(context["reports"]), 1)
		reported = add_to_date(now_datetime(), hours=-1).strftime("%Y-%m-%dT%H:%M")
		done = self.call(
			api.record_reported, report=result["report"]["name"], reported_on=reported, report_ref=""
		)
		self.assertEqual(done["report"]["state"], notifiable.STATE_MISSING_REF)
		self.assertTrue(done["warnings"])
		with self.assertRaises(frappe.PermissionError):
			self.call(api.cancel_report, report=result["report"]["name"], reason="nhầm")
		frappe.set_user(self.r11)
		cancelled = self.call(api.cancel_report, report=result["report"]["name"], reason="nhầm")
		self.assertEqual(cancelled["report"]["state"], notifiable.STATE_CANCELLED)

	def test_guest_portal_denied(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.portal_context()
