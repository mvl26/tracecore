"""Hành vi màn phiếu giám sát FEAT-060 chạy trong Node: PDA SCR-52 (Page station) và SCR-50, SCR-53 (Page tc-ksnk)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
from tracecore.ui import ksnk

AUD = "public/js/station_audit.js"
SCR50 = "public/js/ksnk/scr_50_mau_phieu.js"
SCR53 = "public/js/ksnk/scr_53_tuan_thu.js"

FAKE = """
const html = [];
const queued = [];
const sent = [];
const template = {
	name: "MP-PNC-V2", title: "PPE", scoring_method: "Weighted Score", pass_threshold: null,
	items: [
		{item_code: "A", question: "Hand hygiene", answer_type: "Pass/Fail", weight: 2, is_critical: 1},
		{item_code: "B", question: "Gown", answer_type: "Pass/Fail", weight: 1, is_critical: 0},
		{item_code: "C", question: "Gloves", answer_type: "Pass/Fail", weight: 1, is_critical: 0},
	],
};
const context = {
	ok: true, function: "AUDIT", observer: "EMP-OBS", observer_name: "Observer",
	templates: [template], departments: [{name: "Ward A", department_name: "Ward A"}],
	professions: ["Doctor", "Nurse"],
};
let offline = false;
const station = {
	result: element(), input: element(), session: {token: "t"}, sessionVersion: 1, station: "TR-090",
	offlineData: context,
	isOffline: () => offline, focus() {},
	setState(state, body) { html.push({state, body}); },
	rpcRead: async () => context,
	rpc: async (method, args, key) => { sent.push({method, args, key}); return {ok: true, name: "GS-2026-00001", result: "Fail", critical_failed: 1, score_pct: 50}; },
	queueCall: async (method, args, key, ts) => { queued.push({method, args, key, ts}); },
	failureCause: () => "x",
};
const act = (action, data = {}) => form.onAction(action, {dataset: data});
const last = () => html[html.length - 1];
"""


class TestAuditPdaScreen(FrappeTestCase):
	def run_form(self, body):
		start = "const form = new AuditForm(station);\nif (!offline) await form.loadContext();\n"
		return run_js(self, [AUD], [["AuditForm", "TcAudit"]], FAKE + start + body)

	def test_provisional_score_follows_server_rules(self):
		out = self.run_form(
			"""
			const t = template;
			emit({
				weighted: TcAudit.provisional(t, {A: "Pass", B: "Fail", C: "N/A"}),
				critical: TcAudit.provisional(t, {A: "Fail", B: "Pass", C: "Pass"}),
				none: TcAudit.provisional(t, {A: "N/A"}),
				bundle: TcAudit.provisional({...t, scoring_method: "All or None"}, {A: "Pass", B: "Fail"}),
				threshold: TcAudit.provisional({...t, pass_threshold: 90}, {A: "Pass", B: "Fail", C: "Pass"}),
				missing: TcAudit.missing(t, {A: "Pass"}),
			});
			"""
		)
		self.assertEqual(out["weighted"], {"score": 66.7, "result": "Pass", "critical": False})
		self.assertEqual(out["critical"], {"score": 50, "result": "Fail", "critical": True})
		self.assertEqual(out["none"]["result"], None)
		self.assertEqual(out["bundle"]["result"], "Fail")
		self.assertEqual(out["threshold"]["result"], "Fail")
		self.assertEqual(out["missing"], ["B", "C"])

	def test_three_text_buttons_per_item_and_critical_label(self):
		out = self.run_form(
			"""
			form.show(); await Promise.resolve();
			act("aud-department", {department: "Ward A"});
			act("aud-template", {template: "MP-PNC-V2"});
			emit(last());
			"""
		)
		body = out["body"]
		self.assertEqual(body.count('data-action="aud-answer"'), 9)
		for label in ("Pass", "Fail", "N/A", "Critical", "Post audit"):
			self.assertIn(label, body)
		self.assertIn("tc-aud-post", body)

	def test_self_observation_blocked_inline(self):
		out = self.run_form(
			"""
			act("aud-department", {department: "Ward A"});
			act("aud-template", {template: "MP-PNC-V2"});
			form.form.subject_employee = "EMP-OBS";
			act("aud-submit");
			emit({state: last().state, body: last().body, sent: sent.length, queued: queued.length});
			"""
		)
		self.assertEqual(out["state"], "error")
		self.assertIn('role="alert"', out["body"])
		self.assertIn("Cannot audit yourself", out["body"])
		self.assertEqual((out["sent"], out["queued"]), (0, 0))

	def test_failed_item_needs_note_then_posts_once(self):
		out = self.run_form(
			"""
			act("aud-department", {department: "Ward A"});
			act("aud-template", {template: "MP-PNC-V2"});
			act("aud-answer", {item: "A", answer: "Fail"});
			act("aud-answer", {item: "B", answer: "Pass"});
			act("aud-answer", {item: "C", answer: "N/A"});
			act("aud-submit");
			const blocked = last().body.includes("Note required");
			form.notes.A = "No hand rub";
			act("aud-submit");
			for (let i = 0; i < 20; i++) await Promise.resolve();
			emit({blocked, sent, body: last().body});
			"""
		)
		self.assertTrue(out["blocked"])
		self.assertEqual(len(out["sent"]), 1)
		args = out["sent"][0]["args"]
		self.assertEqual(args["department"], "Ward A")
		self.assertEqual(args["session_uuid"], out["sent"][0]["key"])
		self.assertIn("No hand rub", args["answers"])
		self.assertIn("GS-2026-00001", out["body"])

	def test_offline_queues_with_session_uuid_as_key(self):
		out = self.run_form(
			"""
			offline = true;
			act("aud-department", {department: "Ward A"});
			act("aud-template", {template: "MP-PNC-V2"});
			["A", "B", "C"].forEach((code) => act("aud-answer", {item: code, answer: "Pass"}));
			act("aud-submit");
			for (let i = 0; i < 20; i++) await Promise.resolve();
			emit({queued, sent: sent.length, body: last().body});
			"""
		)
		self.assertEqual(out["sent"], 0)
		self.assertEqual(len(out["queued"]), 1)
		self.assertEqual(out["queued"][0]["method"], "tracecore.v1.audit.submit_session")
		self.assertEqual(out["queued"][0]["key"], out["queued"][0]["args"]["session_uuid"])
		self.assertIn("kept on this device", out["body"])

	def test_wired_into_station_shell_and_outbox(self):
		root = frappe.get_app_path("tracecore")
		with open(os.path.join(root, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			shell = handle.read()
		with open(os.path.join(root, "public", "js", "tc_outbox.js"), encoding="utf-8") as handle:
			outbox = handle.read()
		self.assertIn('case "audit"', shell)
		self.assertIn('"AUDIT"', shell)
		self.assertIn('"tracecore.v1.audit.submit_session"', outbox)
		self.assertIn("public/js/station_audit.js", frappe.get_hooks("page_js")["station"])


class TestKsnkAuditScreens(FrappeTestCase):
	def test_registered_in_compliance_group(self):
		screens = {screen["slug"]: screen for screen in ksnk.SCREENS}
		self.assertEqual(
			(screens["mau-phieu"]["scr"], screens["mau-phieu"]["group"]), ("SCR-50", "compliance")
		)
		self.assertEqual((screens["tuan-thu"]["scr"], screens["tuan-thu"]["group"]), ("SCR-53", "compliance"))
		self.assertNotIn("TC R12", screens["tuan-thu"]["roles"])

	def test_scr50_status_and_coverage_text(self):
		out = run_js(
			self,
			[SCR50],
			[["TcKsnkScr50"]],
			"""
			const s = TcKsnkScr50;
			emit({
				ok: s.statusBadge("Approved"), draft: s.statusBadge("Draft"), old: s.statusBadge("Superseded"),
				future: s.statusBadge("Scheduled"),
				coverage: s.coverageText({coverage_pct: 40, coverage: [{label: "12/30"}, {label: "0/30"}]}),
				locked: s.detailHtml({name: "MP-X-V1", status: "Approved", can_edit: false, items: [
					{item_code: "X-1", question: "Q", answer_type: "Pass/Fail", weight: 2, is_critical: 1}]}, {}, esc),
			});
			""",
		)
		self.assertEqual(out["ok"], {"cls": "is-pass", "label": "Approved"})
		self.assertEqual(out["draft"]["label"], "Draft")
		self.assertEqual(out["old"]["label"], "Superseded")
		self.assertEqual(out["future"]["label"], "Not yet effective")
		self.assertEqual(out["coverage"], "40 % (12/30 · 0/30)")
		self.assertIn("approved and locked", out["locked"])
		self.assertNotIn('data-action="add-item"', out["locked"])

	def test_scr53_labels_are_text_not_color(self):
		out = run_js(
			self,
			[SCR53],
			[["TcKsnkScr53"]],
			"""
			const s = TcKsnkScr53;
			emit({
				small: s.noteBadge({sample_note: "Insufficient sample", scored: 8, min_sample: 20}),
				none: s.noteBadge({sample_note: "Not calculated", scored: 0}),
				fine: s.noteBadge({sample_note: "", scored: 30}),
				critical: s.resultBadge({result: "Fail", critical_failed: 1}),
				pass: s.resultBadge({result: "Pass"}),
				rate: s.percent(78.4), nc: s.percent(null),
				range: s.range("2026-02"),
				pending: s.pendingHtml({can_decide: true, pending: [{name: "GS-1", department: "A",
					failed_items: [{question: "Recap", note: ""}]}]}, esc),
				readonly: s.pendingHtml({can_decide: false, pending: []}, esc),
			});
			""",
		)
		self.assertEqual(out["small"]["label"], "Insufficient sample (n = 8, needs 20)")
		self.assertEqual(out["none"]["label"], "Not calculated")
		self.assertEqual(out["fine"]["label"], "n = 30")
		self.assertEqual(out["critical"], {"cls": "is-fail", "label": "Fail — critical item"})
		self.assertEqual(out["pass"]["label"], "Pass")
		self.assertEqual((out["rate"], out["nc"]), ("78,4 %", "Not calculated"))
		self.assertEqual(out["range"], {"from_date": "2026-02-01", "to_date": "2026-02-28"})
		self.assertIn('data-action="open-nc"', out["pending"])
		self.assertIn('data-action="dismiss"', out["pending"])
		self.assertEqual(out["readonly"], "")

	def test_scripts_use_rpc_names_and_no_raw_colors(self):
		root = frappe.get_app_path("tracecore")
		for path in (SCR50, SCR53, AUD):
			with open(os.path.join(root, *path.split("/")), encoding="utf-8") as handle:
				script = handle.read()
			self.assertNotIn("frappe.call(", script, path)
			self.assertIsNone(re.search(r"#[0-9A-Fa-f]{6}\b", script), path)
		with open(os.path.join(root, *SCR53.split("/")), encoding="utf-8") as handle:
			self.assertIn('"tracecore.v1.audit.compliance_board"', handle.read())
