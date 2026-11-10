"""Màn SCR-62 Vệ sinh môi trường & cơ sở hạ tầng trong Page tc-ksnk và phiếu VSMT/hạ tầng trên PDA (SCR-52) (FEAT-070;
UC-54; FR-M15-01..07; A-131, A-148 f)."""

import os
import uuid

import frappe

from tracecore.compliance_audit import pda
from tracecore.environmental_hygiene import zones
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.factories import make_user
from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.ui import ksnk
from tracecore.v1 import environment as api

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR62 = "public/js/ksnk/scr_62_moi_truong.js"
STATION_AUDIT = "public/js/station_audit.js"

DATA = """
const data = {
	month: "2026-10", summary_only: false, can_decide: true, chemicals_litres: 12.5,
	kpis: {high_risk_passed: 13, high_risk_total: 14, samples_failed: 2, samples_total: 46, samples_overdue: 3,
		infra_due_soon: 4, infra_overdue: 1, zones_short: 1},
	rates: {by_risk: [{key: "Rất cao", label: "Rất cao", passed: 13, total: 14}], by_department: [],
		by_party: [{key: "NCC-A", label: "Công ty A <b>", passed: 3, total: 4}]},
	infra_by_category: [{key: "Ventilation", total: 2, on_time: 1}],
	pending_nc: [{name: "XN-2026-00131", environment_zone: "VV-0001", environment_zone_name: "Phòng mổ 3",
		sample_type: "Air", result_value: 24, unit: "CFU/m3", limit_applied: "NG-PM-KK-V2 · ≤ 10"}],
	samples: [{name: "XN-2026-00131", environment_zone_name: "Phòng mổ 3", sample_type: "Air",
		sampled_on: "2026-10-30", result_value: 24, unit: "CFU/m3", limit_applied: "NG-PM-KK-V2 · ≤ 10",
		result: "Fail"},
		{name: "XN-2026-00129", environment_zone_name: "Phòng mổ 1", sample_type: "Surface",
		sampled_on: "2026-10-29", result_value: 2, unit: "CFU/25 cm2", limit_applied: "NG-PM-BM-V1 · ≤ 5",
		result: "Pass", is_resample_of: "XN-2026-00100"}],
	zones: [{zone: "VV-0001", area_name: "Phòng mổ 3", department_name: "Gây mê", risk_level: "Rất cao",
		responsible_party: "Outsourced Vendor", supplier_name: "Công ty A", required: 4, done: 1, short: true,
		awaiting_resample: 1}],
	infrastructure: [{title: "Hệ thống lọc khí HEPA", area_name: "Phòng mổ 3", last_on: "2026-05-05",
		next_due: "2026-11-05", days_left: 2, status: "Due Soon"},
		{title: "Chênh áp", area_name: "Bệnh nhiệt đới", last_on: "2026-10-01", next_due: "2026-11-01",
		days_left: -9, status: "Overdue"}],
	limits: [{name: "NG-PM-KK-V2", title: "Không khí phòng mổ", sample_type: "Air", snapshot: "NG-PM-KK-V2 · ≤ 10",
		effective_from: "2026-11-01"}],
	limit_drafts: 3,
	plans: [{name: "KLM-2026-001", title: "Không khí phòng mổ", sample_type: "Air", frequency: "Monthly",
		assignee_name: "Lan", zones: [{environment_zone_name: "Phòng mổ 3", next_due: "2026-11-05"}]}],
	overdue_samples: [{zone: "VV-0002", area_name: "Lọc máu", sample_type: "Clinical Water", next_due: "2026-10-01",
		days_late: 40}],
};
const esc = TcKsnk.esc;
"""


class TestScr62Screen(IsolatedTestCase):
	def _run(self, code, files=(SHELL, SCR62), names=(["TcKsnk"], ["TcKsnkScr62"])):
		return run_js(self, list(files), list(names), DATA + code)

	def test_registered_in_environment_group(self):
		screen = next(item for item in ksnk.SCREENS if item["slug"] == "moi-truong")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-62", "UC-54", "environment"))
		self.assertEqual(set(screen["roles"]), {"TC R01", "TC R02", "TC R11", "TC R13", "System Manager"})
		self.assertTrue(os.path.exists(os.path.join(frappe.get_app_path("tracecore"), *SCR62.split("/"))))

	def test_overview_kpis_failed_sample_alert_and_text_status(self):
		out = self._run(
			"""TcKsnkScr62.tab = "overview"; emit({html: TcKsnkScr62.pageHtml(data, esc),
			viewer: TcKsnkScr62.pendingHtml(Object.assign({}, data, {can_decide: false}), esc)});"""
		)
		html = out["html"]
		self.assertIn("92,9 %", html)
		self.assertIn("2/46", html)
		self.assertIn("XN-2026-00131 failed — Phòng mổ 3, Air:", html)
		self.assertIn('data-action="open-nc" data-name="XN-2026-00131"', html)
		self.assertIn("is_resample_of=XN-2026-00131", html)
		self.assertIn("✕ Fail", html)
		self.assertIn("Resample of XN-2026-00100", html)
		self.assertIn("! Short", html)
		self.assertIn("Awaiting resample", html)
		self.assertIn("2 days left", html)
		self.assertIn("✕ Overdue", html)
		self.assertNotIn("open-nc", out["viewer"])

	def test_tabs_limits_plans_and_overdue_samples(self):
		out = self._run('TcKsnkScr62.tab = "limits"; emit(TcKsnkScr62.pageHtml(data, esc));')
		self.assertIn("NG-PM-KK-V2 · ≤ 10", out)
		self.assertIn("3 draft limit(s)", out)
		self.assertIn("Lọc máu — Clinical Water: due 01/10/2026, 40 days late", out)
		self.assertIn("KLM-2026-001", out)
		self.assertIn('aria-selected="true" data-tab="limits"', out)

	def test_summary_only_view_has_no_rows(self):
		out = self._run("emit(TcKsnkScr62.pageHtml(Object.assign({}, data, {summary_only: true}), esc));")
		self.assertIn("Pass rate by risk level", out)
		self.assertIn("Công ty A &lt;b&gt;", out)
		self.assertNotIn("XN-2026-00131", out)
		self.assertNotIn("data-tab", out)


class TestScr62Api(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = ef.make_department("MT Khoa Gây mê")
		frappe.db.delete(zones.DOCTYPE, {"department": self.ward})
		self.zone = ef.make_zone(self.ward, area="Phòng mổ MT").name
		ef.make_limit("T-PM-KK", value=10)
		self.failed = ef.make_sample(self.zone, 24)

	def test_overview_for_r11_lists_pending_nc_samples_and_zones(self):
		frappe.set_user(make_user("mt-r11@example.com", [ef.R11]))
		data = api.overview()
		self.assertFalse(data["summary_only"])
		self.assertTrue(data["can_decide"])
		self.assertIn(self.failed.name, [row["name"] for row in data["pending_nc"]])
		self.assertIn(self.zone, [row["zone"] for row in data["zones"]])
		self.assertGreaterEqual(data["kpis"]["samples_failed"], 1)
		self.assertTrue(any(row["name"] == "NG-T-PM-KK-V1" for row in data["limits"]))

	def test_r13_gets_summary_only_and_r08_is_rejected(self):
		r13 = make_user("mt-r13@example.com", [ef.R13])
		r08 = make_user("mt-r08@example.com", ["TC R08"])
		frappe.set_user(r13)
		data = api.overview("2026-10")
		self.assertTrue(data["summary_only"])
		self.assertNotIn("samples", data)
		self.assertEqual(data["month"], "2026-10")
		frappe.set_user(r08)
		with self.assertRaises(frappe.PermissionError):
			api.overview()

	def call(self, fn, **kwargs):
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
			return fn(client_ts="2026-11-10T09:00:00+07:00", **kwargs)

	def test_open_and_dismiss_nc_through_rpc(self):
		result = self.call(api.open_nc, sample=self.failed.name)
		self.assertTrue(result["ok"])
		other = ef.make_sample(self.zone, 30, is_resample_of=self.failed.name)
		self.assertEqual(frappe.db.get_value("Environmental Sample", other.name, "nc_status"), "Opened")
		third = ef.make_sample(ef.make_zone(self.ward, area="Hồi tỉnh MT").name, 50)
		blocked = self.call(api.dismiss_nc, sample=third.name, reason="")
		self.assertFalse(blocked["ok"])
		self.assertEqual(blocked["error"]["code"], "REASON_REQUIRED")
		self.assertTrue(self.call(api.dismiss_nc, sample=third.name, reason="Mẫu nhiễm khi vận chuyển")["ok"])


class TestPdaZones(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.ward = ef.make_department("PDA Khoa Gây mê")
		frappe.db.delete(zones.DOCTYPE, {"department": self.ward})
		self.zone = ef.make_zone(self.ward, area="Phòng mổ PDA").name
		self.template = ef.make_env_template("T-VSMT-PDA", effective_from=frappe.utils.today()).name

	def test_context_lists_zones_and_submit_links_zone(self):
		self.assertIn(self.zone, [row.name for row in pda.environment_zones()])
		self.assertIn("zones", pda.context(None))
		from tracecore.compliance_audit.tests import factories as af

		result = pda.submit(
			af.make_observer(),
			{
				"audit_template": self.template,
				"department": self.ward,
				"environment_zone": self.zone,
				"answers": frappe.as_json(af.answers(**{"ENV-01": "Pass", "ENV-02": "Pass"})),
			},
			frappe.utils.today(),
		)
		self.assertEqual(frappe.db.get_value("Audit Session", result.name, "environment_zone"), self.zone)

	def test_station_form_shows_zone_chips_and_blocks_without_zone(self):
		source = open(
			os.path.join(frappe.get_app_path("tracecore"), *STATION_AUDIT.split("/")), encoding="utf-8"
		).read()
		self.assertIn('"aud-zone"', source)
		self.assertIn("ENV_ZONE_REQUIRED", source)
		self.assertIn("environment_zone: this.form.environment_zone", source)
		self.assertIn('id="tc-aud-next-due"', source)
