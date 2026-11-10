"""Màn SCR-61 Điều tra ổ dịch & khai báo — WEB trong Page tc-ksnk, banner cụm ca SCR-58, Cổng khoa, Print Format
(FEAT-069; UC-53, UC-50; A-131, A-150)."""

import os

import frappe
from frappe.utils import add_to_date, now_datetime, today

from tracecore.microbiology import notifiable, outbreaks
from tracecore.microbiology.tests import outbreak_fixtures as of
from tracecore.tests.factories import make_user
from tracecore.tests.js_harness import run_js
from tracecore.tests.utils import IsolatedTestCase
from tracecore.ui import ksnk

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR61 = "public/js/ksnk/scr_61_o_dich.js"
SCR58 = "public/js/ksnk/scr_58_bao_cao_nkbv.js"

DATA = """
const data = {
	ok: true, can_own: true, can_work: true, rules_configured: true, rule_form: "/app/cluster-alert-rule",
	disease_form: "/app/communicable-disease", settings_form: "/app/ic-program-settings", can_cancel_report: true,
	print_outbreak: "/printview?doctype=Outbreak%20Investigation&format=TC%20Outbreak%20Investigation&name=",
	departments: [{name: "D1", label: "Hồi sức tích cực"}], case_states: ["Confirmed", "Suspected", "Excluded"],
	diseases: [{name: "DENGUE", disease_name: "Sốt xuất huyết Dengue", disease_group: "B"}], missing_groups: ["C"],
	alerts: [{name: "CCA-2026-00001", department: "D1", department_name: "Hồi sức tích cực", case_count: 3,
		key_label: "VAP", window_days: 14, min_cases: 3, window_start: "2026-10-21", window_end: "2026-11-03"}],
	summary: [{name: "OD-2026-003", title: "Cụm CRE <b>", organism_or_disease: "CRE", department: "D1",
		department_name: "Hồi sức tích cực", start_date: "2026-11-03", case_count: 4, days: 8, status: "Investigating"}],
	current: {name: "OD-2026-003", title: "Cụm CRE tại Hồi sức tích cực", status: "Investigating",
		organism_or_disease: "Klebsiella pneumoniae — CRE", department: "D1", department_name: "Hồi sức tích cực",
		departments: [], opened_by_name: "Nguyễn Thị Hạnh", opened_at: "2026-11-03 08:00:00", source: "Cluster Alert",
		case_definition: "CRE từ 18/10",
		cases: [
			{row: "r1", ref: "CA-2026-00079", patient_code_masked: "***2031", onset_date: "2026-10-20", state: "Confirmed"},
			{row: "r2", ref: "CA-2026-00087", patient_code_masked: "***4821", onset_date: "2026-11-02", state: "Excluded",
			 excluded_at_source: true},
			{row: "r3", ref: null, patient_code_masked: "***7730", onset_date: "2026-11-02", state: "Suspected"}],
		curve: {from: "2026-10-18", to: "2026-11-03", max: 2, days: [
			{date: "2026-10-20", confirmed: 1, suspected: 0, excluded: 0},
			{date: "2026-11-02", confirmed: 0, suspected: 1, excluded: 1}]},
		actions: [{description: "Cách ly tiếp xúc", responsible_name: "ĐD trưởng", due_date: "2026-11-03",
			state: "Done", incident: "NC-2026-00010"},
			{description: "Lấy mẫu môi trường", responsible: "a@b.c", due_date: "2026-11-01", state: "Overdue",
			incident: "NC-2026-00010"}],
		incidents: [{row: "c1", incident: "NC-2026-00010", status: "CAPA", closed: false}]},
	reports: [
		{name: "KB-2026-00021", patient_code_masked: "***0001", disease_name: "Sốt xuất huyết Dengue",
		 disease_group: "B", department_name: "Nhiễm", diagnosed_on: "2026-11-02 15:40:00",
		 due_by: "2026-11-03 15:40:00", state: "Awaiting report", remaining_minutes: 95},
		{name: "KB-2026-00019", patient_code_masked: "***0002", disease_name: "Tay chân miệng", disease_group: "B",
		 diagnosed_on: "2026-10-29 08:00:00", due_by: "2026-10-30 08:00:00", state: "Reported late",
		 report_ref: "SGS-9"}],
	report_summary: {"Awaiting report": 1, "Reported late": 1},
};
const esc = TcKsnk.esc;
"""


def _read(path):
	with open(os.path.join(frappe.get_app_path("tracecore"), *path.split("/")), encoding="utf-8") as handle:
		return handle.read()


class TestKsnkScr61(IsolatedTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR61], [["TcKsnk"], ["TcKsnkScr61"]], DATA + code)

	def test_registered_in_micro_group(self):
		screen = next(item for item in ksnk.SCREENS if item["slug"] == "o-dich")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-61", "UC-53", "micro"))
		self.assertEqual(set(screen["roles"]), {"TC R01", "TC R11", "TC R13", "System Manager"})
		self.assertTrue(os.path.exists(os.path.join(frappe.get_app_path("tracecore"), *SCR61.split("/"))))

	def test_detail_curve_cases_actions(self):
		out = self._run("emit({html: TcKsnkScr61.detailHtml(data, esc)});")
		html = out["html"]
		self.assertIn("OD-2026-003 · SCR-61 · UC-53", html)
		self.assertIn('class="tc-od-cell is-confirmed"', html)
		self.assertIn(">✓<", html)
		self.assertIn(">?<", html)
		self.assertIn(">\u00d7<", html)  # dấu nhân: ca loại trừ
		self.assertIn("Case excluded in HAI surveillance", html)
		self.assertIn("***7730", html)
		self.assertIn("Overdue", html)
		self.assertIn('data-action="end"', html)
		self.assertIn('data-action="controlled"', html)
		self.assertIn("TC%20Outbreak%20Investigation&amp;name=OD-2026-003", html)

	def test_r11_has_no_owner_buttons_and_r13_only_summary(self):
		out = self._run("""emit({
			r11: TcKsnkScr61.detailHtml(Object.assign({}, data, {can_own: false}), esc),
			r13: TcKsnkScr61.pageHtml(Object.assign({}, data, {can_own: false, can_work: false, current: null,
				alerts: [], reports: []}), esc, false)});""")
		self.assertNotIn('data-action="end"', out["r11"])
		self.assertIn('data-action="add-action"', out["r11"])
		self.assertNotIn("***", out["r13"])
		self.assertIn("Cụm CRE &lt;b&gt;", out["r13"])
		self.assertNotIn('<a href="/app/tc-ksnk/o-dich?outbreak', out["r13"])
		self.assertIn("Awaiting report", out["r13"])

	def test_alert_banner_open_form_and_reports(self):
		out = self._run("""emit({
			alerts: TcKsnkScr61.alertsHtml(data, esc),
			none: TcKsnkScr61.alertsHtml(Object.assign({}, data, {alerts: [], rules_configured: false}), esc),
			form: TcKsnkScr61.openFormHtml(Object.assign({}, data, {prefill: {alert: "CCA-2026-00001",
				department: "D1", title: "Cụm VAP", organism_or_disease: "VAP", source_label: "3 cases / 14 days",
				cases: [{}, {}, {}]}}), esc, false),
			hidden: TcKsnkScr61.openFormHtml(data, esc, false),
			reports: TcKsnkScr61.reportsHtml(data, esc)});""")
		self.assertIn("3 cases of VAP in 14 days (threshold 3 cases / 14 days)", out["alerts"])
		self.assertIn('data-action="open-from-alert"', out["alerts"])
		self.assertIn("No cluster alert threshold is configured", out["none"])
		self.assertIn('value="Cụm VAP"', out["form"])
		self.assertIn("3 cases of the alert are linked", out["form"])
		self.assertEqual(out["hidden"], "")
		self.assertIn("1 h 35 min left", out["reports"])
		self.assertIn("Reported late", out["reports"])
		self.assertIn("disease group C", out["reports"])
		self.assertIn('data-action="reported" data-name="KB-2026-00021"', out["reports"])
		self.assertNotIn('data-action="reported" data-name="KB-2026-00019"', out["reports"])

	def test_scr58_cluster_banner(self):
		out = run_js(
			self,
			[SHELL, SCR58],
			[["TcKsnk"], ["TcKsnkClusterBanner"]],
			"""const b = {configured: true, can_review: true, open_link: "/app/tc-ksnk/o-dich",
				alerts: [{name: "CCA-1", department_name: "HSTC", case_count: 3, key_label: "VAP", window_days: 14,
				min_cases: 3, window_start: "2026-10-21", window_end: "2026-11-03"}]};
			emit({html: TcKsnkClusterBanner.html(b, TcKsnk.esc),
				r13: TcKsnkClusterBanner.html(Object.assign({}, b, {can_review: false}), TcKsnk.esc),
				none: TcKsnkClusterBanner.html({configured: false, rule_form: "/app/cluster-alert-rule"}, TcKsnk.esc)});""",
		)
		self.assertIn("/app/tc-ksnk/o-dich?alert=CCA-1", out["html"])
		self.assertIn("Mark as reviewed", out["html"])
		self.assertNotIn("Mark as reviewed", out["r13"])
		self.assertIn("/app/cluster-alert-rule", out["none"])

	def test_tokens_only_in_css(self):
		css = _read("www/ksnk_khoa/khai_bao.css") + _read("ui/page/tc_ksnk/tc_ksnk.css").split("FEAT-069")[-1]
		self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b")
		self.assertNotRegex(css, r"\d+px")


class TestNotifiablePortal(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = of.make_clinical("KBP Khoa Nhiễm")
		frappe.db.delete(notifiable.DOCTYPE, {"department": self.ward})

	def test_route_rule_nav_and_assets(self):
		rules = frappe.get_hooks("website_route_rules")
		self.assertIn({"from_route": "/ksnk-khoa/khai-bao", "to_route": "ksnk_khoa/khai_bao"}, rules)
		html = frappe.render_template("templates/includes/ksnk_khoa_nav.html", {"ksnk_nav": "khai-bao"})
		self.assertIn('href="/ksnk-khoa/khai-bao" aria-current="page"', html)
		script = _read("www/ksnk_khoa/khai_bao.js")
		self.assertIn("X-Idempotency-Key", script)
		self.assertIn("tracecore.v1.outbreak.create_report", script)

	def test_context_login_redirect_and_department_scope(self):
		from tracecore.www.ksnk_khoa import khai_bao as page

		r11 = make_user("kbp-r11@example.com", ["TC R11"])
		user = of.make_dept_user("kbp-r08@example.com", "TC R08", self.ward)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			page.get_context(frappe._dict())
		self.assertIn("/login?redirect-to=", frappe.local.flags.redirect_location)
		frappe.set_user(r11)
		with self.assertRaises(frappe.Redirect):
			page.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/app/tc-ksnk/o-dich")
		frappe.set_user(user)
		context = page.get_context(frappe._dict())
		self.assertEqual([row["name"] for row in context.boot["data"]["departments"]], [self.ward])
		self.assertIn("states", context.boot["labels"])


class TestPrintFormats(IsolatedTestCase):
	def test_print_formats_show_masked_code_only(self):
		of.set_hours(b=24)
		ward = of.make_clinical("PF Khoa Nhiễm")
		report = notifiable.create_report(
			{
				"department": ward,
				"patient_code": "BN0009876",
				"disease": of.make_disease("T-PF", "Bệnh in", "B"),
				"diagnosed_on": add_to_date(now_datetime(), hours=-1),
			}
		)
		html = frappe.get_print(notifiable.DOCTYPE, report.name, print_format="TC Notifiable Disease Report")
		self.assertIn("***9876", html)
		self.assertNotIn("BN0009876", html)
		r01 = make_user("pf-r01@example.com", ["TC R01"])
		frappe.set_user(r01)
		doc = outbreaks.open_outbreak(
			{"title": "Ổ dịch in", "organism_or_disease": "CRE", "department": ward, "start_date": today()}
		)
		outbreaks.add_case(doc.name, "Manual", patient_code="BN0005555", onset_date=today())
		frappe.set_user("Administrator")
		html = frappe.get_print(outbreaks.DOCTYPE, doc.name, print_format="TC Outbreak Investigation")
		self.assertIn("***5555", html)
		self.assertNotIn("BN0005555", html)
