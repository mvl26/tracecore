"""Màn SCR-65 ATTP & truyền thông người bệnh trong Page tc-ksnk, phiếu ATTP trên PDA (SCR-52) và mẫu thực phẩm (SCR-62)
(FEAT-073; UC-56; FR-M17-01..06; A-131, A-151)."""

import os
import uuid

import frappe
from frappe.utils import add_days, today

from tracecore.compliance_audit import pda
from tracecore.compliance_audit.tests import factories as af
from tracecore.environmental_hygiene import seed as env_seed
from tracecore.environmental_hygiene import zones
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.food_safety import audits as food_audits
from tracecore.food_safety import events, handlers
from tracecore.food_safety.tests import factories as ff
from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.ui import ksnk
from tracecore.v1 import food_safety as api

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR65 = "public/js/ksnk/scr_65_attp.js"
STATION_AUDIT = "public/js/station_audit.js"

DATA = """
const data = {
	summary_only: false, can_decide: true, can_publish: true, outbreak_ready: true, threshold: 3,
	kpis: {handlers_total: 3, handlers_overdue: 1, handlers_due_soon: 1, handlers_unfit: 0, events_pending: 1,
		food_audits_failed: 0, food_samples_failed: 1},
	quarter: {label: "Q4/2026", sessions: 9, attendees: 247,
		rows: [{audience: "Patient Families", topic: "Hand Hygiene", sessions: 2, attendees: 40}]},
	pending_events: [{name: "NDTP-2026-002", event_date: "2026-11-02", location: "Căng tin <b>", affected_count: 4,
		suspected_food: "Cơm gà", description: "Đau bụng sau bữa trưa", nc_status: "Suggested",
		outbreak_status: "Suggested", threshold_applied: 3}],
	handlers: [{name: "SKTP-2026-00001", full_name: "Nhân viên bếp 1", unit: "Khoa Dinh dưỡng",
		checked_on: "2025-11-15", next_due: "2026-11-22", state: "Due Soon", days_left: 12, fit_for_work: "Fit"},
		{name: "SKTP-2026-00002", full_name: "Nhân viên bếp 2", unit: "Khoa Dinh dưỡng", checked_on: "2025-10-20",
		next_due: "2026-10-20", state: "Overdue", days_left: -21, fit_for_work: "Fit"},
		{name: "SKTP-2026-00003", full_name: "Nhân viên suất ăn 1", unit: "Công ty suất ăn D", checked_on: "2026-06-05",
		next_due: "2027-06-05", state: "Valid", days_left: 207, fit_for_work: "Unfit"}],
	overdue_by_unit: [{unit: "Khoa Dinh dưỡng", handlers: [{full_name: "Nhân viên bếp 2", next_due: "2026-10-20"}]}],
	sessions: [{name: "GDS-2026-00001", session_date: "2026-11-01", department_name: "Nhi", audience: "Patient Families",
		title: "Vệ sinh tay khi chăm trẻ", attendee_count: 26}],
	materials: [{name: "QTK-00011", doc_code: "TL-VST", title: "Vệ sinh tay đúng cách cho người nhà", version_no: 2,
		status: "Effective", issued_on: "2026-09-15", url: "https://bv/tai-lieu/TL-VST", qr: "data:image/png;base64,AAA"},
		{name: "QTK-00012", doc_code: "TL-THAM", title: "Quy định thăm người bệnh cách ly", version_no: 1,
		status: "Draft", issued_on: null, url: "https://bv/tai-lieu/TL-THAM", qr: "data:image/png;base64,BBB"}],
	food_audits: [{unit: "Công ty suất ăn D", last_date: "2026-11-03", last_result: "Pass", last_score: 92.5,
		passed: 2, total: 2}],
	food_samples: [{name: "XN-2026-00140", environment_zone_name: "Bếp chính", sampled_on: "2026-11-04",
		result_value: 120, unit: "CFU/g", limit_applied: "NG-TP-V1 · ≤ 100", result: "Fail"}],
};
const esc = TcKsnk.esc;
"""


class TestScr65Screen(IsolatedTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR65], [["TcKsnk"], ["TcKsnkScr65"]], DATA + code)

	def test_registered_in_environment_group(self):
		screen = next(item for item in ksnk.SCREENS if item["slug"] == "attp")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-65", "UC-56", "environment"))
		self.assertEqual(set(screen["roles"]), {"TC R01", "TC R11", "TC R13", "System Manager"})
		self.assertTrue(os.path.exists(os.path.join(frappe.get_app_path("tracecore"), *SCR65.split("/"))))

	def test_page_shows_event_alert_handlers_sessions_and_materials(self):
		html = self._run("emit(TcKsnkScr65.pageHtml(data, esc));")
		self.assertIn("NDTP-2026-002 — suspected food poisoning:", html)
		self.assertIn("Căng tin &lt;b&gt;", html)
		self.assertIn('data-action="open-nc" data-name="NDTP-2026-002"', html)
		self.assertIn('data-action="open-outbreak" data-name="NDTP-2026-002"', html)
		self.assertIn("12 days left", html)
		self.assertIn("✕ Overdue", html)
		self.assertIn("✓ Valid", html)
		self.assertIn("Unfit", html)
		self.assertIn("Q4/2026: 9 sessions · 247 attendees", html)
		self.assertIn("Vệ sinh tay khi chăm trẻ", html)
		self.assertIn("Current v2", html)
		self.assertIn('data-action="print-qr" data-name="QTK-00011"', html)
		self.assertIn('data-action="publish" data-name="QTK-00012"', html)
		self.assertIn("Not issued — the QR code is not active yet.", html)
		self.assertIn("✕ Fail", html)
		self.assertIn("Công ty suất ăn D", html)

	def test_viewer_without_decision_rights_has_no_action_buttons(self):
		html = self._run(
			"emit(TcKsnkScr65.pageHtml(Object.assign({}, data, {can_decide: false, can_publish: false,"
			" outbreak_ready: false}), esc));"
		)
		for action in ("open-nc", "open-outbreak", "publish", "withdraw"):
			self.assertNotIn(f'data-action="{action}"', html)

	def test_summary_only_view_has_no_names(self):
		html = self._run("emit(TcKsnkScr65.pageHtml(Object.assign({}, data, {summary_only: true}), esc));")
		self.assertIn("Q4/2026: 9 sessions · 247 attendees", html)
		self.assertNotIn("Nhân viên bếp", html)
		self.assertNotIn("NDTP-2026-002", html)


class TestScr65Api(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		ff.set_threshold(3)
		self.event = ff.make_event(affected=5)
		self.check = ff.make_check("Bếp API", next_due=add_days(today(), -1))
		self.material = ff.make_material("TL-API", 1, status="Draft")

	def call(self, fn, **kwargs):
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
			return fn(client_ts="2026-11-10T09:00:00+07:00", **kwargs)

	def test_overview_for_r11(self):
		frappe.set_user(ff.make_user("attp-api-r11@example.com", [ff.R11]))
		data = api.overview()
		self.assertFalse(data["summary_only"])
		self.assertTrue(data["can_decide"])
		self.assertFalse(data["can_publish"])
		self.assertIn(self.event.name, [row["name"] for row in data["pending_events"]])
		self.assertIn(self.check.name, [row["name"] for row in data["handlers"]])
		self.assertTrue(any(row["name"] == self.material.name for row in data["materials"]))
		self.assertGreaterEqual(data["kpis"]["handlers_overdue"], 1)
		self.assertEqual(data["threshold"], 3)

	def test_r13_summary_only_r08_rejected(self):
		r13 = ff.make_user("attp-api-r13@example.com", [ff.R13])
		r08 = ff.make_user("attp-api-r08@example.com", [ff.R08])
		frappe.set_user(r13)
		data = api.overview()
		self.assertTrue(data["summary_only"])
		self.assertNotIn("handlers", data)
		self.assertNotIn("pending_events", data)
		frappe.set_user(r08)
		with self.assertRaises(frappe.PermissionError):
			api.overview()

	def test_decisions_through_rpc(self):
		frappe.set_user(ff.make_user("attp-api-r01@example.com", [ff.R01]))
		result = self.call(api.open_nc, event=self.event.name)
		self.assertTrue(result["ok"])
		blocked = self.call(api.dismiss_outbreak, event=self.event.name, reason="")
		self.assertEqual(blocked["error"]["code"], "REASON_REQUIRED")
		self.assertTrue(
			self.call(api.dismiss_outbreak, event=self.event.name, reason="Không cùng nguồn")["ok"]
		)
		self.assertEqual(api.outbreak_prefill(self.event.name)["source_name"], self.event.name)
		self.assertTrue(self.call(api.publish_material, name=self.material.name)["ok"])
		self.assertEqual(
			frappe.db.get_value("IC Procedure Document", self.material.name, "status"), "Effective"
		)
		self.assertTrue(self.call(api.withdraw_material, name=self.material.name, reason="Hết dùng")["ok"])
		qr = api.material_qr(self.material.name)
		self.assertTrue(qr["qr"].startswith("data:image/png;base64,"))
		self.assertTrue(qr["url"].endswith("/tai-lieu/TL-API"))

	def test_badges_for_r11(self):
		user = ff.make_user("attp-api-badge@example.com", [ff.R11])
		self.assertGreaterEqual(ksnk._badges(user).get("attp", 0), 2)
		self.assertIn("attp", [item["slug"] for group in ksnk.nav(user)["groups"] for item in group["items"]])


class TestFoodAuditsAndSamples(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.caterer = ff.make_caterer()
		self.kitchen = ff.make_department("ATTP Khoa Dinh dưỡng PDA")

	def test_attp_template_is_seeded_once_as_draft(self):
		env_seed.ensure_seed()
		env_seed.ensure_seed()
		rows = frappe.get_all(
			"Audit Template", filters={"template_code": "ATTP"}, fields=["audit_type", "docstatus"]
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].audit_type, "Food Safety")

	def test_pda_lists_caterers_and_links_audit_to_vendor(self):
		laundry = ff.factories.make_supplier("ATTP Công ty giặt là")
		frappe.db.set_value("Supplier", laundry, "tc_ic_service_type", "Laundry")
		names = [row["name"] for row in pda.context(None)["caterers"]]
		self.assertIn(self.caterer, names)
		self.assertNotIn(laundry, names)
		template = ef.make_env_template("T-ATTP-PDA", audit_type="Food Safety", effective_from=today()).name
		result = pda.submit(
			af.make_observer(),
			{
				"audit_template": template,
				"department": self.kitchen,
				"supplier": self.caterer,
				"answers": frappe.as_json(af.answers(**{"ENV-01": "Pass", "ENV-02": "Pass"})),
			},
			today(),
		)
		self.assertEqual(frappe.db.get_value("Audit Session", result.name, "supplier"), self.caterer)
		units = {row["unit"]: row for row in food_audits.unit_results(add_days(today(), -30), today())}
		self.assertEqual(units["ATTP Công ty suất ăn D"]["passed"], 1)
		internal = ef.make_session(template, self.kitchen, passed=False)
		units = {row["unit_key"]: row for row in food_audits.unit_results(add_days(today(), -30), today())}
		self.assertEqual(units[f"D:{self.kitchen}"]["last_result"], internal.result)

	def test_station_form_offers_vendor_for_food_safety_audits(self):
		source = open(
			os.path.join(frappe.get_app_path("tracecore"), *STATION_AUDIT.split("/")), encoding="utf-8"
		).read()
		self.assertIn('"aud-supplier"', source)
		self.assertIn("supplier: this.form.supplier", source)
		self.assertIn("Hospital kitchen", source)

	def test_food_sample_is_handled_like_environmental_sample(self):
		frappe.db.delete(zones.DOCTYPE, {"department": self.kitchen})
		zone = ef.make_zone(self.kitchen, area="Bếp chính ATTP").name
		ef.make_limit("T-TP-COLI", value=100, sample_type="Food", unit="CFU/g")
		sample = ef.make_sample(zone, 120, code="T-TP-COLI", sample_type="Food")
		self.assertEqual(sample.result, "Fail")
		self.assertEqual(frappe.db.get_value("Environmental Sample", sample.name, "nc_status"), "Suggested")
		self.assertEqual(frappe.db.get_value(zones.DOCTYPE, zone, "awaiting_resample"), 1)
		self.assertIn(sample.name, [row["name"] for row in food_audits.recent_samples()])


class TestHandlerAndEventHooks(IsolatedTestCase):
	def test_indicator_and_badges_registered(self):
		self.assertIn(
			"tracecore.food_safety.indicators.register", frappe.get_hooks("tracecore_ic_indicators")
		)
		self.assertIn("tracecore.food_safety.dashboard.badges", frappe.get_hooks("tracecore_ksnk_badges"))
		self.assertIn(
			"tracecore.food_safety.handlers.run_daily", frappe.get_hooks("scheduler_events")["daily"]
		)
		self.assertIn(
			"tracecore.reprocessing.incidents.on_food_safety_nc", frappe.get_hooks("tracecore_food_safety_nc")
		)
		self.assertEqual(handlers.DOCTYPE, "Food Handler Health Check")
		self.assertEqual(events.DOCTYPE, "Foodborne Event")

	def test_indicator_rate_of_handlers_with_valid_check(self):
		from tracecore.food_safety import indicators

		frappe.db.delete(handlers.DOCTYPE)
		ff.make_check("Chỉ số 1", checked_on="2026-01-10", next_due="2027-01-10")
		ff.make_check("Chỉ số 2", checked_on="2025-09-10", next_due="2026-09-10")
		ff.make_check("Chỉ số 3", checked_on="2026-02-10", next_due="2027-02-10", fit="Unfit")
		self.assertEqual(indicators.handler_health_valid("2026-10"), (1, 3, 3))
