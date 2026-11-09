"""Màn SCR-48 Kế hoạch KSNK năm, văn bản nội bộ, họp Hội đồng (FEAT-058 AC-13; FR-M11-04..08; A-131)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "public/js/ksnk/ksnk_shell.js"
SCR48 = "public/js/ksnk/scr_48_ke_hoach.js"

DATA = """
const plan = {
	name: "KH-2026-01", year: 2026, docstatus: 1, created_by: "Nguyễn Thị Hạnh", approved_by: "BS. Trần Văn Minh",
	approved_on: "2026-01-20 09:00:00", total_budget_vnd: 486000000, activities_total: 34, activities_completed: 21,
	overdue: 1, pending_amendment: null,
	indicators: [
		{indicator: "HH", indicator_name: "Hand <b>hygiene", kind: "Percentage", direction: "Higher is better",
		 baseline: 71, target: 80, latest: 78.4, latest_period: "2026-10", latest_status: "Not met"},
		{indicator: "HAI", indicator_name: "HAI rate", kind: "Rate per 1000", direction: "Lower is better",
		 baseline: 3.4, target: 3, latest: null, latest_period: null, latest_status: ""},
	],
	activities: [
		{name: "r1", activity: "VST training", measure_group: "Hand Hygiene", responsible: "Vũ Thị Lan",
		 department: "", due_date: "2026-10-31", budget_vnd: 12000000, status: "Planned", display_status: "overdue",
		 status_label: "Overdue", evidence: "", can_update: true},
		{name: "r2", activity: "Swab test", measure_group: "Environmental Hygiene", responsible: "Hùng",
		 department: "OR", due_date: "2026-09-30", budget_vnd: 24000000, status: "Completed",
		 display_status: "completed", status_label: "Completed", evidence: "XN-2026-00118", can_update: false},
	],
};
const data = {
	year: 2026, plan: plan, documents_attention: 2,
	documents: [
		{name: "QTK-00012", doc_code: "QT-VST", title: "Hand hygiene", version_no: 3, review_due: "2027-03-12",
		 status: "Effective", status_key: "effective", days_left: 120},
		{name: "QTK-00007", doc_code: "QT-CL", title: "Isolation", version_no: 2, review_due: "2026-11-20",
		 status: "Review Needed", status_key: "review", days_left: 17},
		{name: "QTK-00004", doc_code: "QT-PN", title: "Sharps", version_no: 1, review_due: "2026-09-01",
		 status: "Review Needed", status_key: "overdue", days_left: -60},
	],
	meeting: {name: "HH-2026-003", meeting_date: "2026-10-08", resolutions: [
		{content: "Add pharmacy", responsible: "TCCB", due_date: "2026-11-30", display_status: "in_progress",
		 status_label: "In Progress"},
		{content: "VAP bundle", responsible: "BS. Tâm", due_date: "2026-10-31", display_status: "overdue",
		 status_label: "Overdue"}]},
	open_resolutions: [{meeting: "HH-2026-002", content: "Old item", responsible: "A", due_date: "2026-08-01"}],
	can_approve: false, can_amend: true, can_create_plan: false, can_record_meeting: true,
};
const esc = TcKsnk.esc;
const ctx = (tab, readOnly) => ({esc, filters: {tab}, readOnly: !!readOnly,
	state: (kind, message) => TcKsnk.stateHtml(kind, message)});
"""


def _read(path):
	with open(os.path.join(frappe.get_app_path("tracecore"), *path.split("/")), encoding="utf-8") as handle:
		return handle.read()


class TestKsnkScr48(FrappeTestCase):
	def _run(self, code):
		return run_js(self, [SHELL, SCR48], [["TcKsnk"], ["TcKsnkScr48"]], DATA + code)

	def test_number_formats_vietnamese(self):
		out = self._run(
			"""
			const s = TcKsnkScr48;
			emit({vnd: s.vnd(486000000), pct: s.num(78.4, "Percentage"), rate: s.num(2.1, "Rate per 1000"),
				whole: s.num(80, "Percentage"), none: s.num(null), date: s.date("2026-01-20 09:00:00"),
				target: s.target(plan.indicators[0]), lower: s.target(plan.indicators[1])});
			"""
		)
		self.assertEqual(out["vnd"], "486.000.000")
		self.assertEqual(out["pct"], "78,4 %")
		self.assertEqual(out["rate"], "2,1 ‰")
		self.assertEqual(out["whole"], "80 %")
		self.assertEqual(out["none"], "—")
		self.assertEqual(out["date"], "20/01/2026")
		self.assertEqual(out["target"], "≥ 80 %")
		self.assertEqual(out["lower"], "≤ 3 ‰")

	def test_badges_always_have_text_and_class(self):
		out = self._run(
			"""
			const s = TcKsnkScr48;
			emit({over: s.badgeHtml("overdue", "Overdue", esc), soon: s.badgeClass("due_soon"),
				done: s.badgeClass("completed"), info: s.badgeClass("in_progress"), x: s.badgeHtml("zzz", "", esc)});
			"""
		)
		self.assertIn('class="tc-ksnk-badge is-fail"', out["over"])
		self.assertIn("Overdue", out["over"])
		self.assertEqual((out["soon"], out["done"], out["info"]), ("is-warn", "is-pass", "is-info"))
		self.assertIn("—", out["x"])

	def test_plan_tab_info_indicators_activities(self):
		out = self._run("""emit({html: TcKsnkScr48.pageHtml(data, ctx("plan"))});""")
		html = out["html"]
		self.assertIn("KH-2026-01", html)
		self.assertIn("21/34 completed", html)
		self.assertIn("486.000.000 VND", html)
		self.assertIn("BRU-ICP-004", html)
		self.assertIn("Hand &lt;b&gt;hygiene", html)
		self.assertNotIn("Hand <b>hygiene", html)
		self.assertIn("78,4 %", html)
		self.assertIn("1 overdue", html)
		self.assertIn('data-action="save-activity"', html)  # r1 cập nhật được
		self.assertIn("XN-2026-00118", html)
		self.assertIn('aria-selected="true" data-tab="plan"', html)

	def test_documents_and_meeting_tabs(self):
		out = self._run(
			"""emit({docs: TcKsnkScr48.pageHtml(data, ctx("documents")),
				meet: TcKsnkScr48.pageHtml(data, ctx("meeting")), none: TcKsnkScr48.pageHtml(
					Object.assign({}, data, {plan: null}), ctx("plan"))});"""
		)
		self.assertIn("QTK-00007", out["docs"])
		self.assertIn("17 days left", out["docs"])
		self.assertIn("Review overdue", out["docs"])
		self.assertIn("v3", out["docs"])
		self.assertIn("HH-2026-003", out["meet"])
		self.assertIn("08/10/2026", out["meet"])
		self.assertIn("HH-2026-002", out["meet"])
		self.assertIn("No annual plan for 2026 yet.", out["none"])

	def test_actions_follow_rights(self):
		out = self._run(
			"""
			const s = TcKsnkScr48;
			emit({r01: s.actionsHtml(data, false, esc), ro: s.actionsHtml(data, true, esc),
				r13: s.actionsHtml(Object.assign({}, data, {can_approve: true, can_amend: false}), true, esc)});
			"""
		)
		self.assertIn('data-action="amend"', out["r01"])
		self.assertIn("/app/ic-committee-meeting/new", out["r01"])
		self.assertIn("TC%20IC%20Annual%20Summary", out["r01"])
		self.assertNotIn('data-action="amend"', out["ro"])
		self.assertIn('data-action="approve"', out["r13"])  # R13 chỉ đọc nhưng vẫn ghi sổ kế hoạch

	def test_block_alert_order(self):
		out = self._run(
			"""emit({html: TcKsnkScr48.blockHtml({title: "Not approved", reason: "R13 only", action: "Ask"}, esc)});"""
		)
		html = out["html"]
		self.assertIn('role="alert"', html)
		self.assertLess(html.index("Not approved"), html.index("R13 only"))
		self.assertLess(html.index("R13 only"), html.index("Ask"))

	def test_script_registers_and_uses_desk_helpers(self):
		script = _read(SCR48)
		self.assertIn('window.TcKsnkScreens["ke-hoach"]', script)
		for method in ("status", "approve_plan", "make_amendment", "update_activity"):
			self.assertIn(f'"tracecore.v1.ksnk_plan.{method}"', script)
		self.assertNotIn("frappe.call(", script)
		self.assertNotIn("msgprint", script)
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", script))
		self.assertIn('"tab"', _read(SHELL))

	def test_css_tokens_only(self):
		css = _read("ui/page/tc_ksnk/tc_ksnk.css")
		block = css[css.index("FEAT-058 SCR-48") :]
		self.assertIn(".tc-ksnk .tc-ksnk-tab.is-active", block)
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", block))
		self.assertIsNone(re.search(r"\d+(px|rem|em)\b", block.replace("900px", "")))
