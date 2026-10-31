"""Màn cấp phát đồ vải SCR-18 (FEAT-035 Task 5): nối vào màn trạm LIN, RPC đúng tên, luật tính chạy thật trong Node.

Kiểm phần đọc được bằng Python/Node: file JS nạp sau station_linen.js (lớp con), không chữ Việt/hex trong code, và logic
form (cảnh báo vượt tối đa không chặn, kiểm biểu mẫu, quét thẻ người nhận ghi sổ bằng thẻ, ký cảm ứng cần nét vẽ).
"""

import json
import os
import re
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore import hooks
from tracecore.linen.tests.test_linen_station_assets import (
	APP_PATH,
	JS_DIR,
	LINEN_JS,
	NODE,
	STATION_CSS,
	VIETNAMESE,
	WEIGH_JS,
	_read,
)

ISSUE_JS = os.path.join(JS_DIR, "station_linen_issue.js")
LAUNDRY_JS = os.path.join(JS_DIR, "station_laundry.js")


def _node(script):
	prelude = f"""
const fs = require('fs');
const __ = (text, args) => args ? text.replace(/\\{{(\\d+)\\}}/g, (m, i) => String(args[i])) : text;
const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
globalThis.tcErrorTitle = (notice) => (notice && notice.title) || '';
globalThis.tcGuideButton = () => '';
const uuid4 = () => 'key';
const clientTs = () => '2026-10-29T09:00:00+07:00';
const load = (path, name, deps) => new Function(...Object.keys(deps),
	fs.readFileSync(path, 'utf8') + '; return ' + name + ';')(...Object.values(deps));
const TcWeighLine = load({json.dumps(WEIGH_JS)}, 'TcWeighLine', {{ __, esc }});
const LinenCollect = load({json.dumps(LINEN_JS)}, 'LinenCollect', {{ __, esc, uuid4, clientTs, TcWeighLine }});
const lauDeps = {{ __, esc, uuid4, clientTs, TcWeighLine, LinenCollect }};
const linenTabs = load({json.dumps(LAUNDRY_JS)}, 'linenTabs', lauDeps);
const LinenIssue = load({json.dumps(ISSUE_JS)}, 'LinenIssue', {{ ...lauDeps, linenTabs }});
const LinenStation = load({json.dumps(LAUNDRY_JS)}, 'LinenStation', {{ ...lauDeps, LinenIssue }});
const types = [{{ name: 'Sheet', std_weight_kg: 0.5 }}, {{ name: 'Gown', std_weight_kg: 1 }}];
function screen() {{
	const calls = [];
	const input = {{ setAttribute() {{}}, value: '' }};
	const station = {{
		result: {{ querySelector: () => null, dataset: {{}} }}, input, listen() {{}}, session: {{}}, sessionVersion: 1,
		station: 'TR-LIN', focus() {{}}, form: {{ classList: {{ toggle() {{}} }} }},
		setState(state, html) {{ station.state = state; station.html = html; }}, renderLoading() {{}},
		rpc: async (method, args, key) => {{ calls.push({{ method, args, key }}); return {{ ok: true, issue: {{ lines: [], balance: [] }} }}; }},
	}};
	const issue = new LinenIssue(station);
	issue.catalog = {{ types, departments: [{{ name: 'D1', department_name: 'Khoa 1' }}] }};
	return {{ issue, calls, station }};
}}
"""
	completed = subprocess.run(
		[NODE, "-e", prelude + script], capture_output=True, text=True, timeout=30, check=False
	)
	assert completed.returncode == 0, completed.stderr
	return json.loads(completed.stdout.strip().splitlines()[-1])


class TestLinenIssueWiring(FrappeTestCase):
	def test_issue_js_is_loaded_after_the_collect_screen(self):
		files = hooks.page_js["station"]
		self.assertLess(
			files.index("public/js/station_linen.js"), files.index("public/js/station_linen_issue.js")
		)

	def test_rpc_names_match_the_server(self):
		source = _read(ISSUE_JS)
		self.assertIn('"tracecore.v1.linen.balance"', source)
		self.assertIn('"tracecore.v1.linen.issue"', source)
		from tracecore.v1 import linen as api

		self.assertTrue(callable(api.balance) and callable(api.issue))

	def test_print_uses_the_issue_format(self):
		source = _read(ISSUE_JS)
		self.assertIn('format: "TC Linen Issue Receipt"', source)
		self.assertTrue(frappe.db.exists("Print Format", "TC Linen Issue Receipt"))

	def test_no_vietnamese_text_or_hex_colours_in_the_code(self):
		source = _read(ISSUE_JS)
		self.assertIsNone(VIETNAMESE.search(re.sub(r"//.*", "", source)))
		self.assertIsNone(
			re.search(
				r"(?<![&\w])#[0-9a-fA-F]{3,8}\b", re.sub(r"//.*", "", source).replace('"#tc-lin-pad"', "")
			)
		)
		self.assertTrue(os.path.exists(STATION_CSS))
		self.assertTrue(APP_PATH)


class TestLinenIssueLogic(FrappeTestCase):
	def setUp(self):
		if not NODE:
			self.skipTest("node is not installed")

	def test_station_has_the_issue_tab_and_switches_to_it(self):
		out = _node(
			"""
const { station } = screen();
const linen = new LinenStation(station);
const tabs = linenTabs('collect').includes('data-mode="issue"');
const handled = linen.onAction('linen-mode', { dataset: { mode: 'issue' } });
console.log(JSON.stringify({ tabs, handled, issue: linen.active === linen.issue }));
"""
		)
		self.assertEqual(out, {"tabs": True, "handled": True, "issue": True})

	def test_issue_screen_shows_the_tabs(self):
		out = _node(
			"""
const { issue, station } = screen();
issue.show();
console.log(JSON.stringify({ tabs: station.html.includes('data-mode="collect"') }));
"""
		)
		self.assertTrue(out["tabs"])

	def test_over_max_quota_warns_without_blocking(self):  # FR-M3-05.2
		out = _node(
			"""
const { issue } = screen();
issue.balance = [{ linen_type: 'Sheet', stock: 8, min_qty: 2, max_qty: 12 }];
issue.form.lines = [{ id: '1', linen_type: 'Sheet', qty: '5', weight: '', variance_note: '' }];
issue.form.department = 'D1';
console.log(JSON.stringify({ warnings: issue.warnings().length, problems: issue.problems().length }));
"""
		)
		self.assertEqual(out, {"warnings": 1, "problems": 0})

	def test_form_needs_department_and_a_line_with_numbers(self):  # BRU-LIN-001
		out = _node(
			"""
const { issue } = screen();
const empty = issue.problems().length;
issue.form.department = 'D1';
issue.form.lines = [{ id: '1', linen_type: 'Sheet', qty: '', weight: '', variance_note: '' }];
const noNumbers = issue.problems().length;
issue.form.lines[0].qty = '4';
console.log(JSON.stringify({ empty, noNumbers, ok: issue.problems().length }));
"""
		)
		self.assertGreaterEqual(out["empty"], 2)
		self.assertEqual((out["noNumbers"], out["ok"]), (1, 0))

	def test_weight_over_tolerance_needs_a_note(self):  # FR-M3-01.4 dùng chung
		out = _node(
			"""
const { issue } = screen();
issue.form.department = 'D1';
issue.form.lines = [{ id: '1', linen_type: 'Sheet', qty: '10', weight: '8', variance_note: '' }];
const without = issue.problems().length;
issue.form.lines[0].variance_note = 'Ướt';
console.log(JSON.stringify({ without, withNote: issue.problems().length }));
"""
		)
		self.assertEqual(out, {"without": 1, "withNote": 0})

	def test_card_scan_in_sign_phase_records_with_the_card(self):  # FR-M3-05.1
		out = _node(
			"""
(async () => {
	const { issue, calls } = screen();
	issue.form.department = 'D1';
	issue.form.lines = [{ id: '1', linen_type: 'Sheet', qty: '4', weight: '', variance_note: '' }];
	issue.phase = 'sign';
	await issue.scan('CARD-1');
	const call = calls.find((row) => row.method === 'tracecore.v1.linen.issue');
	console.log(JSON.stringify({ args: call.args, key: call.key }));
})();
"""
		)
		args = out["args"]
		self.assertEqual(
			(args["recipient_card"], args["sign_method"], args["kind"], args["department"]),
			("CARD-1", "Card", "Return", "D1"),
		)
		self.assertEqual(args["lines"], [{"linen_type": "Sheet", "qty": 4}])

	def test_touch_signature_needs_a_stroke(self):
		out = _node(
			"""
const { issue, calls } = screen();
issue.form.department = 'D1';
issue.form.lines = [{ id: '1', linen_type: 'Sheet', qty: '4', weight: '', variance_note: '' }];
issue.signMode = 'Touch';
issue.recipientCard = 'CARD-1';
issue.strokes = 0;
issue.confirmTouch();
console.log(JSON.stringify({ title: issue.notice.title, sent: calls.length }));
"""
		)
		self.assertEqual(out, {"title": "Signature is empty", "sent": 0})

	def test_session_end_clears_the_issue_form(self):
		out = _node(
			"""
const { station } = screen();
const linen = new LinenStation(station);
linen.issue.form.department = 'D1';
linen.issue.phase = 'sign';
linen.active = linen.issue;
linen.clearSession();
console.log(JSON.stringify({ department: linen.issue.form.department, phase: linen.issue.phase, mode: linen.active === linen.collect }));
"""
		)
		self.assertEqual(out, {"department": "", "phase": "form", "mode": True})
