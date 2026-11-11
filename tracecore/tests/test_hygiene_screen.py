"""SCR-51 phiếu vệ sinh tay theo cơ hội trên PDA chạy trong Node (FEAT-061 AC-2, AC-6, AC-9; FR-M12-04, FR-M12-10;
NFR-USAB-03, NFR-AVAIL-05) và khối vệ sinh tay của SCR-53."""

import csv
import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore import hooks
from tracecore.tests.js_harness import run_js

AUD = "public/js/station_audit.js"
HH = "public/js/station_hand_hygiene.js"
SCR53 = "public/js/ksnk/scr_53_tuan_thu.js"

FAKE = """
const html = [];
const queued = [];
const sent = [];
let counter = 0;
globalThis.uuid4 = () => "u" + (++counter);
const vst = {
	name: "MP-VST-V2", title: "Hand hygiene", scoring_method: "By Opportunity", items: [],
	moments: [
		{moment: "1", label: "Before touching a patient"}, {moment: "2", label: "Before a clean procedure"},
		{moment: "3", label: "After body fluid risk"}, {moment: "4", label: "After touching a patient"},
		{moment: "5", label: "After touching surroundings"},
	],
};
const context = {
	ok: true, function: "AUDIT", observer: "EMP-OBS", observer_name: "Observer",
	templates: [], opportunity_templates: [vst],
	departments: [{name: "ICU", department_name: "ICU"}],
	professions: ["Doctor", "Nurse", "Orderly", "Other"],
};
let offline = false;
let reject = null;
const station = {
	result: element(), input: element(), session: {token: "t"}, sessionVersion: 1, station: "TR-091",
	offlineData: context,
	isOffline: () => offline, focus() {},
	setState(state, body) { html.push({state, body}); },
	rpcRead: async () => context,
	rpc: async (method, args, key) => {
		sent.push({method, args, key});
		if (reject) return reject;
		if (method.endsWith("submit_session")) return {ok: true, name: "GS-2026-00007", score_pct: 66.7, result: null};
		return {ok: true, name: "GS-2026-00007", opportunities: sent.length};
	},
	queueCall: async (method, args, key, ts) => { queued.push({method, args, key, ts}); },
	failureCause: () => "x",
};
const act = (action, data = {}) => form.onAction(action, {dataset: data});
const last = () => html[html.length - 1];
const settle = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const open = async () => {
	await form.loadContext();
	act("aud-department", {department: "ICU"});
	act("aud-template", {template: "MP-VST-V2"});
};
const record = async (role, moment, action) => {
	if (form.hygiene.role !== role) act("hh-role", {role}); // chip nhớ nghề nghiệp: chạm lại sẽ bỏ chọn
	act("hh-moment", {moment});
	act("hh-action", {actionValue: action});
	await settle();
};
"""


def read(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


class TestHygieneScreen(FrappeTestCase):
	def run_form(self, body):
		start = "const form = new AuditForm(station);\n"
		return run_js(
			self, [AUD, HH], [["AuditForm", "TcAudit"], ["HygieneView", "TcHygiene"]], FAKE + start + body
		)

	def test_provisional_rate_follows_bru_aud_002(self):
		out = self.run_form(
			"""
			const rows = (n, ok) => Array.from({length: n}, (_, i) => ({action: i < ok ? "Hand Rub" : "Missed"}));
			emit({fifty: TcHygiene.stats(rows(50, 41)), none: TcHygiene.stats([]), missed: TcHygiene.stats(rows(2, 0))});
			"""
		)
		self.assertEqual(out["fifty"], {"total": 50, "actioned": 41, "rate": 82})
		self.assertIsNone(out["none"]["rate"])
		self.assertEqual(out["missed"]["rate"], 0)

	def test_start_screen_lists_the_hand_hygiene_template(self):
		out = self.run_form(
			"await open(); form.template = null; form.hygiene = null; form.show(); emit(last().body);"
		)
		self.assertIn('data-template="MP-VST-V2"', out)

	def test_three_text_buttons_five_moments_from_template_and_post_button(self):
		out = self.run_form("await open(); emit(last().body);")
		self.assertEqual(out.count('data-action="hh-moment"'), 5)
		self.assertEqual(out.count('data-action="hh-action"'), 3)
		for label in ("Hand Rub", "Hand Wash", "Missed", "Post audit (0 opportunities)", "Nurse"):
			self.assertIn(label, out)
		self.assertIn("tc-aud-post", out)

	def test_moment_buttons_follow_the_template_not_a_fixed_five(self):
		out = self.run_form(
			"""
			vst.moments = vst.moments.slice(0, 3);
			await open();
			emit(last().body);
			"""
		)
		self.assertEqual(out.count('data-action="hh-moment"'), 3)

	def test_three_taps_record_one_opportunity_and_send_it_at_once(self):
		out = self.run_form(
			"""
			await open();
			act("hh-role", {role: "Nurse"});            // chạm 1
			act("hh-moment", {moment: "2"});            // chạm 2
			sent.length = 0;
			act("hh-action", {actionValue: "Hand Rub"}); // chạm 3: gửi ngay
			await settle();
			emit({sent, body: last().body});
			"""
		)
		self.assertEqual(len(out["sent"]), 1)
		call = out["sent"][0]
		self.assertEqual(call["method"], "tracecore.v1.audit.record_opportunity")
		self.assertEqual(call["key"], json_loads(call["args"]["opportunity"])["uuid"])
		opportunity = json_loads(call["args"]["opportunity"])
		self.assertEqual(
			(opportunity["subject_role"], opportunity["moment"], opportunity["action"]),
			("Nurse", "2", "Hand Rub"),
		)
		self.assertEqual((call["args"]["department"], call["args"]["audit_template"]), ("ICU", "MP-VST-V2"))
		self.assertTrue(call["args"]["session_uuid"])
		self.assertIn("Post audit (1 opportunities)", out["body"])

	def test_profession_is_remembered_so_the_next_opportunity_is_two_taps(self):
		out = self.run_form(
			"""
			await open();
			await record("Doctor", "1", "Hand Wash");
			act("hh-moment", {moment: "4"});
			act("hh-action", {actionValue: "Missed"});
			await settle();
			emit(sent.map((call) => JSON.parse(call.args.opportunity)).map((o) => [o.subject_role, o.moment, o.action]));
			"""
		)
		self.assertEqual(out, [["Doctor", "1", "Hand Wash"], ["Doctor", "4", "Missed"]])

	def test_running_counter_and_recent_list_use_text_labels(self):
		out = self.run_form(
			"""
			await open();
			for (const action of ["Hand Rub", "Hand Rub", "Missed", "Hand Wash"]) await record("Nurse", "1", action);
			emit(last().body);
			"""
		)
		self.assertIn(">4<", out)
		self.assertIn("75 %", out)
		self.assertIn("Just recorded", out)

	def test_action_without_profession_or_moment_is_an_inline_error(self):
		out = self.run_form(
			"""
			await open();
			act("hh-action", {actionValue: "Hand Rub"});
			await settle();
			emit({state: last().state, body: last().body, sent: sent.length, queued: queued.length});
			"""
		)
		self.assertEqual(out["state"], "error")
		self.assertIn('role="alert"', out["body"])
		self.assertIn("Profession and moment required", out["body"])
		self.assertEqual((out["sent"], out["queued"]), (0, 0))

	def test_observed_person_equal_to_observer_is_blocked_and_not_saved(self):
		out = self.run_form(
			"""
			await open();
			act("hh-role", {role: "Nurse"});
			act("hh-moment", {moment: "1"});
			form.hygiene.subject = "EMP-OBS";
			act("hh-action", {actionValue: "Hand Rub"});
			await settle();
			emit({state: last().state, body: last().body, sent: sent.length, queued: queued.length, rows: form.hygiene.rows.length});
			"""
		)
		self.assertEqual(out["state"], "error")
		self.assertIn("Cannot audit yourself", out["body"])
		self.assertEqual((out["sent"], out["queued"], out["rows"]), (0, 0, 0))

	def test_server_rejection_is_shown_inline_and_not_counted(self):
		out = self.run_form(
			"""
			await open();
			reject = {ok: false, error: {code: "AUDIT_OPPORTUNITY_INVALID", title: "Opportunity not valid", reason: "Moment 9", action: "Choose again"}};
			await record("Nurse", "1", "Hand Rub");
			emit({state: last().state, body: last().body, rows: form.hygiene.rows.length});
			"""
		)
		self.assertEqual(out["state"], "error")
		self.assertIn("Opportunity not valid", out["body"])
		self.assertEqual(out["rows"], 0)

	def test_offline_queues_each_opportunity_then_the_post_in_order(self):
		out = self.run_form(
			"""
			offline = true;
			await open();
			await record("Nurse", "1", "Hand Rub");
			await record("Nurse", "5", "Missed");
			act("hh-submit");
			await settle();
			emit({sent: sent.length, queued: queued.map((q) => [q.method, q.key, q.ts]), body: last().body});
			"""
		)
		self.assertEqual(out["sent"], 0)
		methods = [row[0].rsplit(".", 1)[1] for row in out["queued"]]
		self.assertEqual(methods, ["record_opportunity", "record_opportunity", "submit_session"])
		self.assertEqual(len({row[1] for row in out["queued"]}), 3)  # mỗi lệnh một khóa idempotent riêng
		self.assertIn("kept on this device", out["body"])

	def test_offline_rows_show_waiting_to_sync(self):
		out = self.run_form(
			"""
			offline = true;
			await open();
			await record("Nurse", "1", "Hand Rub");
			emit(last().body);
			"""
		)
		self.assertIn("Waiting to sync", out)

	def test_post_sends_submit_after_the_opportunities_with_the_same_session(self):
		out = self.run_form(
			"""
			await open();
			await record("Nurse", "1", "Hand Rub");
			await record("Doctor", "3", "Hand Wash");
			act("hh-submit");
			await settle();
			emit({methods: sent.map((s) => s.method.split(".").pop()), sessions: [...new Set(sent.map((s) => s.args.session_uuid))].length, body: last().body});
			"""
		)
		self.assertEqual(out["methods"], ["record_opportunity", "record_opportunity", "submit_session"])
		self.assertEqual(out["sessions"], 1)
		self.assertIn("GS-2026-00007", out["body"])
		self.assertIn("66,7", out["body"])

	def test_post_without_opportunities_is_blocked_inline(self):
		out = self.run_form(
			"""
			await open();
			act("hh-submit");
			await settle();
			emit({state: last().state, body: last().body, sent: sent.length});
			"""
		)
		self.assertEqual(out["state"], "error")
		self.assertIn("No opportunity recorded", out["body"])
		self.assertEqual(out["sent"], 0)

	def test_empty_state_when_no_hand_hygiene_template_is_approved(self):
		out = self.run_form(
			"""
			context.opportunity_templates = [];
			await form.loadContext();
			act("aud-department", {department: "ICU"});
			emit(last().body);
			"""
		)
		self.assertIn("No approved audit template", out)


class TestHygieneAssets(FrappeTestCase):
	def test_wired_into_station_page_and_outbox(self):
		self.assertIn(HH, hooks.page_js["station"])
		self.assertIn('"tracecore.v1.audit.record_opportunity"', read("public", "js", "tc_outbox.js"))

	def test_every_string_has_a_vietnamese_translation(self):
		with open(
			frappe.get_app_path("tracecore", "translations", "vi.csv"), encoding="utf-8", newline=""
		) as handle:
			translated = {row[0] for row in csv.reader(handle) if row}
		sources = re.findall(r'__\(\s*"((?:[^"\\]|\\.)*)"', read("public", "js", "station_hand_hygiene.js"))
		self.assertTrue(sources)
		self.assertEqual(sorted({text for text in sources if text not in translated}), [])

	def test_no_hard_coded_colours_pixels_hover_or_modal(self):
		script = read("public", "js", "station_hand_hygiene.js")
		self.assertIsNone(re.search(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b", script))
		self.assertIsNone(re.search(r"\d+px", script))
		for banned in (
			"mouseover",
			"contextmenu",
			"frappe.msgprint",
			"frappe.show_alert",
			"new frappe.ui.Dialog",
			"console.",
			"localStorage",
		):
			self.assertNotIn(banned, script)

	def test_css_uses_only_tokens_and_keeps_touch_sizes(self):
		css = read("ui", "page", "station", "station.css")
		block = css[css.index("FEAT-061 SCR-51") : css.index("/* thao tác nguy hiểm")]
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", block))
		self.assertIsNone(re.search(r"\d+px", block))
		self.assertIn("min-height: var(--tc-touch-station)", block)
		self.assertIn("minmax(var(--tc-touch-min)", block)


class TestScr53HygieneBlock(FrappeTestCase):
	def test_block_shows_rate_by_profession_and_moment_with_text_notes(self):
		out = run_js(
			self,
			[SCR53],
			[["TcKsnkScr53"]],
			"""
			const s = TcKsnkScr53;
			const row = {key: "Nurse", total: 8, actioned: 6, rate: 75, technique_rate: 50, rate_label: "75,0 % (n = 8, insufficient sample)"};
			emit({
				html: s.hygieneHtml({total: 8, profession: [row], moment: [{...row, key: "3"}]}, esc),
				empty: s.hygieneHtml({total: 0, profession: [], moment: []}, esc),
			});
			""",
		)
		self.assertIn("Nurse", out["html"])
		self.assertIn("insufficient sample", out["html"])
		self.assertIn("Moment", out["html"])
		self.assertEqual(out["empty"], "")

	def test_scr53_asset_is_still_token_only(self):
		self.assertIsNone(re.search(r"#[0-9A-Fa-f]{6}\b", read("public", "js", "ksnk", "scr_53_tuan_thu.js")))
		self.assertTrue(
			os.path.exists(frappe.get_app_path("tracecore", "public", "js", "ksnk", "scr_53_tuan_thu.js"))
		)


def json_loads(text):
	import json

	return json.loads(text)
