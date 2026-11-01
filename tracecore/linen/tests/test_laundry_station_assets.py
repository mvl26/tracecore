"""Màn lô giặt SCR-17 trong trạm đồ vải (FEAT-034 Task 7): nối vào Page station, bản dịch, luật kiểm biểu mẫu.

Kiểm phần đọc được bằng Python/Node: file JS được nạp sau station_linen.js, trạm LIN dùng `LinenStation`, RPC
`tracecore.v1.laundry.*` khớp server, không chữ Việt/hex trong code, lỗi chặn hiện inline, và logic kiểm biểu mẫu (tải máy,
nhiệt độ + hóa chất khử khuẩn, thuê ngoài, bước sấy) cùng thanh chuyển tab chạy thật trong Node.
"""

import json
import os
import re
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore import hooks
from tracecore.tests.test_station_page import JS_STRING, other_app_translations, vi_translations

APP_PATH = frappe.get_app_path("tracecore")
JS_DIR = os.path.join(APP_PATH, "public", "js")
WEIGH_JS = os.path.join(JS_DIR, "tc_weigh_line.js")
LINEN_JS = os.path.join(JS_DIR, "station_linen.js")
LAUNDRY_JS = os.path.join(JS_DIR, "station_laundry.js")
ISSUE_JS = os.path.join(JS_DIR, "station_linen_issue.js")  # LinenStation c?ng t?o m?n C?p ph?t (FEAT-035)
STATION_JS = os.path.join(APP_PATH, "ui", "page", "station", "station.js")
STATION_CSS = os.path.join(APP_PATH, "ui", "page", "station", "station.css")
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
NODE = shutil.which("node")


def _read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def _node(script):
	"""Chạy `script` trong Node với ba file JS đã nạp (không DOM); in một dòng JSON, trả về giá trị đó."""
	prelude = f"""
const fs = require('fs');
const __ = (text, args) => args ? text.replace(/\\{{(\\d+)\\}}/g, (m, i) => String(args[i])) : text;
const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
globalThis.tcErrorTitle = (notice) => (notice && notice.title) || '';
globalThis.tcGuideButton = () => '';
const uuid4 = () => 'key';
const clientTs = () => '2026-10-29T09:00:00+07:00';
const load = (path, names, deps) => new Function(...Object.keys(deps),
	fs.readFileSync(path, 'utf8') + '; return {{' + names.join(',') + '}};')(...Object.values(deps));
const TcWeighLine = load({json.dumps(WEIGH_JS)}, ['TcWeighLine'], {{ __, esc }}).TcWeighLine;
const linenDeps = {{ __, esc, uuid4, clientTs, TcWeighLine }};
const LinenCollect = load({json.dumps(LINEN_JS)}, ['LinenCollect'], linenDeps).LinenCollect;
const {{ linenTabs }} = load({json.dumps(LAUNDRY_JS)}, ['linenTabs'], {{ ...linenDeps, LinenCollect }});
const LinenIssue = load({json.dumps(ISSUE_JS)}, ['LinenIssue'], {{ ...linenDeps, LinenCollect, linenTabs }}).LinenIssue;
const {{ LaundryBatch, LinenStation }} = load(
	{json.dumps(LAUNDRY_JS)}, ['LaundryBatch', 'LinenStation'], {{ ...linenDeps, LinenCollect, LinenIssue }});
function stationStub() {{
	const states = [];
	return {{
		result: {{}}, input: {{ setAttribute() {{}}, value: '' }}, listen() {{}}, session: {{}}, sessionVersion: 1,
		station: 'TR-LIN', states, form: {{ classList: {{ toggle() {{}} }} }}, focus() {{}},
		renderLoading() {{ states.push('loading'); }}, setState(state) {{ states.push(state); }},
		rpc() {{ return new Promise(() => {{}}); }}, setOffline() {{}},
	}};
}}
const CTX = {{
	washers: [{{ name: 'TB-1', equipment_name: 'Giặt 1', capacity_kg: 30 }}],
	dryers: [{{ name: 'TB-2', equipment_name: 'Sấy 1' }}],
	programs: [
		{{ name: 'HOT', equipment: 'TB-1', temperature: 75, norms: [{{ item: 'DET', qty_per_load: 1, qty_per_kg: 0.5 }}] }},
		{{ name: 'COLD', equipment: 'TB-1', temperature: 40, norms: [{{ item: 'DET', qty_per_load: 0, qty_per_kg: 0.1 }}] }},
		{{ name: 'COLD-DIS', equipment: 'TB-1', temperature: 40, norms: [{{ item: 'DIS', qty_per_load: 0, qty_per_kg: 0.1 }}] }},
	],
	chemicals: [{{ name: 'DET', item_name: 'Det', tc_is_disinfectant: 0 }}, {{ name: 'DIS', item_name: 'Dis', tc_is_disinfectant: 1 }}],
	running: [{{ name: 'LG-1', weight_kg: 10, contaminated: 1, batch_type: 'In-house' }},
		{{ name: 'LG-2', weight_kg: 5, contaminated: 0, batch_type: 'Outsourced' }}],
}};
function laundry() {{
	const lau = new LaundryBatch(stationStub());
	lau.ctx = CTX;
	return lau;
}}
"""
	completed = subprocess.run(
		[NODE, "-e", prelude + script],
		capture_output=True,
		text=True,
		timeout=30,
		check=False,
	)
	assert completed.returncode == 0, completed.stderr
	return json.loads(completed.stdout.strip().splitlines()[-1])


class TestLaundryStationWiring(FrappeTestCase):
	def test_js_is_loaded_after_the_linen_screen(self):
		files = hooks.page_js["station"]
		self.assertLess(
			files.index("public/js/station_linen.js"), files.index("public/js/station_laundry.js")
		)

	def test_station_routes_the_lin_step_to_the_linen_station(self):
		source = _read(STATION_JS)
		self.assertIn('if (typeof LinenStation !== "undefined") return LinenStation;', source)
		self.assertIn(
			'return typeof LinenCollect !== "undefined" ? LinenCollect : null;', source
		)  # còn dự phòng khi thiếu station_laundry.js
		self.assertIn('method.startsWith("tracecore.v1.laundry.")', source)  # RPC gắn token phiên thẻ

	def test_rpc_names_match_the_server(self):
		source = _read(LAUNDRY_JS)
		for name in ("context", "start", "complete"):
			self.assertIn(f'"tracecore.v1.laundry.{name}"', source)
			self.assertTrue(frappe.get_attr(f"tracecore.v1.laundry.{name}"))

	def test_strings_translated_and_no_hard_coded_text_or_colour(self):
		ours, others = vi_translations(), other_app_translations()
		script = _read(LAUNDRY_JS)
		strings = sorted({match[1] for match in JS_STRING.findall(script)})
		missing = [s for s in strings if not (ours.get(s) or others.get(s))]
		self.assertFalse(missing, f"station_laundry.js: thiếu dòng vi.csv {missing}")
		for number, line in enumerate(script.splitlines(), 1):
			code = line.split("//", 1)[0]
			self.assertFalse(VIETNAMESE.search(code), f"{number}: {line}")
			self.assertNotRegex(code, r"(?<![&\w])#[0-9a-fA-F]{3,6}\b", f"{number}: {line}")

	def test_blocking_error_is_inline_result_reason_action(self):
		source = _read(LAUNDRY_JS) + _read(LINEN_JS)
		for part in ("tc-alert-title", "tc-alert-reason", "tc-alert-action"):
			self.assertIn(part, source)
		self.assertNotIn("frappe.msgprint", source)
		self.assertNotIn("frappe.show_alert", source)

	def test_css_uses_tokens_only(self):
		css = _read(STATION_CSS)
		block = css[css.index("Lô giặt (SCR-17") :]
		self.assertNotRegex(block, r"#[0-9a-fA-F]{3,6}\b")
		self.assertNotRegex(re.sub(r"@media[^{]*", "", block), r"\b\d+px\b")


class TestLaundryFormRules(FrappeTestCase):
	def setUp(self):
		if not NODE:
			self.skipTest("Cần Node để chạy mã JS của màn trạm.")

	def check(self, setup, call="lau.startProblems()"):
		return _node(f"const lau = laundry(); {setup}\nconsole.log(JSON.stringify({call}));")

	def fill(self, extra=""):
		return "Object.assign(lau.form, {equipment: 'TB-1', program: 'HOT', kg: '10'});" + extra

	def test_empty_form_lists_the_missing_values(self):
		self.assertEqual(self.check(""), ["Enter the weight in kg of the linen.", "Choose the washer."])

	def test_program_is_required_once_the_washer_is_chosen(self):
		self.assertEqual(
			self.check("Object.assign(lau.form, {equipment: 'TB-1', kg: '10'});"), ["Choose the program."]
		)

	def test_complete_in_house_form_has_no_problem(self):
		self.assertEqual(self.check(self.fill()), [])

	def test_weight_over_machine_capacity_is_flagged(self):  # FR-M3-03.3
		self.assertEqual(
			self.check(self.fill("lau.form.kg = '31,5';")),
			["The load is over the machine capacity of 30 kg."],
		)

	def test_contaminated_cool_program_needs_a_disinfectant(self):  # FR-M3-03.2
		message = "Contaminated linen below 71 C needs a disinfectant chemical."
		cold = "lau.form.program = 'COLD';"
		self.assertEqual(self.check(self.fill(cold)), [message])
		# đồ sạch không bị luật nhiệt độ; hóa chất khử khuẩn trong định mức hoặc do người dùng chọn thì qua
		self.assertEqual(self.check(self.fill(cold + "lau.form.contaminated = false;")), [])
		self.assertEqual(self.check(self.fill("lau.form.program = 'COLD-DIS';")), [])
		self.assertEqual(
			self.check(self.fill(cold + "lau.form.chemicals.push({item: 'DIS', qty: '1'});")), []
		)
		self.assertEqual(
			self.check(self.fill(cold + "lau.form.chemicals.push({item: 'DET', qty: '1'});")), [message]
		)

	def test_outsourced_needs_vendor_and_price_but_no_machine(self):  # UC-17 A2
		base = "Object.assign(lau.form, {batch_type: 'Outsourced', kg: '10'});"
		self.assertEqual(self.check(base), ["Type the name of the vendor.", "Enter the price per kg."])
		self.assertEqual(self.check(base + "Object.assign(lau.form, {vendor: 'ABC', price: '12000'});"), [])

	def test_payload_maps_the_form_to_the_rpc(self):
		out = self.check(
			self.fill(
				"Object.assign(lau.form, {contaminated: false, note: ' ghi chú ', redo_of: 'LG-0'});"
				"lau.form.chemicals.push({item: 'DET', qty: '2,5'}, {item: '', qty: ''});"
			),
			"lau.startPayload()",
		)
		self.assertEqual(
			out,
			{
				"station": "TR-LIN",
				"batch_type": "In-house",
				"loads": [{"kg": 10, "contaminated": 0}],
				"equipment": "TB-1",
				"program": "HOT",
				"chemicals": [{"item": "DET", "qty": 2.5}],
				"redo_of": "LG-0",
				"note": "ghi chú",
			},
		)

	def test_outsourced_payload_carries_vendor_and_price_only(self):
		out = self.check(
			"Object.assign(lau.form, {batch_type: 'Outsourced', kg: '10', vendor: ' ABC ', price: '12000'});",
			"lau.startPayload()",
		)
		self.assertEqual(
			out,
			{
				"station": "TR-LIN",
				"batch_type": "Outsourced",
				"loads": [{"kg": 10, "contaminated": 1}],
				"vendor": "ABC",
				"price_per_kg": 12000,
			},
		)

	def test_finish_needs_dryer_drying_data_and_both_results(self):  # UC-17 bước 4-5
		out = self.check("lau.finish = lau.blankFinish('LG-1');", "lau.finishProblems()")
		self.assertEqual(
			out,
			[
				"Choose the dryer.",
				"Enter the drying temperature in C.",
				"Enter the drying time in minutes.",
				"Record whether the linen is clean.",
				"Record whether the linen is dry.",
			],
		)

	def test_outsourced_finish_needs_only_the_results(self):
		out = self.check("lau.finish = lau.blankFinish('LG-2');", "lau.finishProblems()")
		self.assertEqual(out, ["Record whether the linen is clean.", "Record whether the linen is dry."])

	def test_finish_is_complete_with_all_values(self):
		out = self.check(
			"Object.assign(lau.finish, {batch: 'LG-1', dryer: 'TB-2', dry_temp: '70', dry_minutes: '40', clean_ok: '1', dry_ok: '0'});",
			"({items: lau.finishProblems()})",
		)
		self.assertEqual(out, {"items": []})

	def test_a_failed_batch_offers_to_wash_again(self):
		out = _node(
			"const lau = laundry(); lau.done = {name: 'LG-9', status: 'Failed', weight_kg: 12.5, contaminated: 0,"
			" cost_total: 0, cost_per_kg: 0};\n"
			"lau.mode = 'done'; const html = lau.doneHtml(); lau.redo();\n"
			"console.log(JSON.stringify({again: html.includes('data-action=\"redo\"'), redo_of: lau.form.redo_of,"
			" kg: lau.form.kg, contaminated: lau.form.contaminated, mode: lau.mode}));"
		)
		self.assertEqual(
			out, {"again": True, "redo_of": "LG-9", "kg": "12,5", "contaminated": False, "mode": "start"}
		)

	def test_a_passed_batch_has_no_wash_again_button(self):
		out = _node(
			"const lau = laundry(); lau.done = {name: 'LG-9', status: 'Passed', weight_kg: 10, cost_total: 100, cost_per_kg: 10};\n"
			"console.log(JSON.stringify({again: lau.doneHtml().includes('data-action=\"redo\"')}));"
		)
		self.assertEqual(out, {"again": False})


class TestLinenStationTabs(FrappeTestCase):
	def setUp(self):
		if not NODE:
			self.skipTest("Cần Node để chạy mã JS của màn trạm.")

	def test_tabs_switch_the_active_screen_and_delegate_other_actions(self):
		out = _node(
			"const st = stationStub(); const lin = new LinenStation(st);\n"
			"const first = lin.active === lin.collect;\n"
			"lin.onAction('linen-mode', {dataset: {mode: 'laundry'}});\n"
			"const second = lin.active === lin.laundry;\n"
			"lin.laundry.busy = null; // RPC tải danh mục đã trả lời\n"
			"lin.onAction('linen-mode', {dataset: {mode: 'collect'}});\n"
			"const third = lin.active === lin.collect;\n"
			"const unknown = lin.onAction('no-such-action', {dataset: {}});\n"
			"console.log(JSON.stringify({first, second, third, unknown}));"
		)
		self.assertEqual(out, {"first": True, "second": True, "third": True, "unknown": False})

	def test_busy_screen_ignores_a_tab_switch(self):
		out = _node(
			"const lin = new LinenStation(stationStub()); lin.collect.busy = 'x';\n"
			"lin.onAction('linen-mode', {dataset: {mode: 'laundry'}});\n"
			"console.log(JSON.stringify({collect: lin.active === lin.collect, busy: lin.busy}));"
		)
		self.assertEqual(out, {"collect": True, "busy": "x"})

	def test_clear_session_returns_to_the_collection_screen(self):
		out = _node(
			"const lin = new LinenStation(stationStub());\n"
			"lin.onAction('linen-mode', {dataset: {mode: 'laundry'}}); lin.clearSession();\n"
			"console.log(JSON.stringify({collect: lin.active === lin.collect}));"
		)
		self.assertEqual(out, {"collect": True})

	def test_tab_bar_marks_the_active_tab_with_text_and_aria(self):
		out = _node(
			"const html = linenTabs('laundry');\n"
			'console.log(JSON.stringify({pressed: (html.match(/aria-pressed="true"/g) || []).length,'
			" both: html.includes('Collection') && html.includes('Laundry batch')}));"
		)
		self.assertEqual(out, {"pressed": 1, "both": True})

	def test_rpc_token_covers_the_laundry_methods(self):
		self.assertIn('method.startsWith("tracecore.v1.laundry.")', _read(STATION_JS))
