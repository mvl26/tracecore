"""Màn trạm đồ vải SCR-16 và component tc-weigh-line (FEAT-033 Task 6): nối vào Page station, bản dịch, luật tính cùng server.

Kiểm phần đọc được bằng Python/Node: file JS được nạp sau station.js, RPC `tracecore.v1.linen.*` gắn token phiên, không chữ
Việt/hex trong code, lỗi chặn hiện inline, và logic kiểm biểu mẫu (cân nhập tay phải xác nhận, lệch 15 % cần ghi chú, cân tổng)
chạy thật trong Node.
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
STATION_JS = os.path.join(APP_PATH, "ui", "page", "station", "station.js")
STATION_CSS = os.path.join(APP_PATH, "ui", "page", "station", "station.css")
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
NODE = shutil.which("node")


def _read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def _node(script):
	"""Chạy `script` trong Node với hai file JS đã nạp (không DOM); in một dòng JSON, trả về giá trị đó."""
	prelude = f"""
const fs = require('fs');
const __ = (text, args) => args ? text.replace(/\\{{(\\d+)\\}}/g, (m, i) => String(args[i])) : text;
const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const uuid4 = () => 'key';
const clientTs = () => '2026-10-29T09:00:00+07:00';
const load = (path, name, deps) => new Function(...Object.keys(deps),
	fs.readFileSync(path, 'utf8') + '; return ' + name + ';')(...Object.values(deps));
const TcWeighLine = load({json.dumps(WEIGH_JS)}, 'TcWeighLine', {{ __, esc }});
const LinenCollect = load({json.dumps(LINEN_JS)}, 'LinenCollect', {{ __, esc, uuid4, clientTs, TcWeighLine }});
function screen(types) {{
	const input = {{ setAttribute() {{}}, value: '' }};
	const station = {{ result: {{}}, input, listen() {{}}, session: {{}}, sessionVersion: 1, station: 'TR-LIN' }};
	const lin = new LinenCollect(station);
	lin.catalog = {{ types, departments: [] }};
	return lin;
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


class TestLinenStationWiring(FrappeTestCase):
	def test_js_files_are_loaded_after_station_js(self):
		files = hooks.page_js["station"]
		self.assertIn("public/js/tc_weigh_line.js", files)
		self.assertIn("public/js/station_linen.js", files)

	def test_station_routes_the_lin_step_to_linen_collect(self):
		source = _read(STATION_JS)
		self.assertIn('case "linen":', source)
		self.assertIn('return typeof LinenCollect !== "undefined" ? LinenCollect : null;', source)
		self.assertIn('method.startsWith("tracecore.v1.linen.")', source)  # RPC gắn token phiên thẻ

	def test_rpc_names_match_the_server(self):
		source = _read(LINEN_JS)
		self.assertIn('"tracecore.v1.linen.catalog"', source)
		self.assertIn('"tracecore.v1.linen.collect"', source)
		for name in ("catalog", "collect"):
			self.assertTrue(frappe.get_attr(f"tracecore.v1.linen.{name}"))

	def test_scale_url_is_the_station_agent(self):
		self.assertIn('"http://127.0.0.1:8765/scale"', _read(WEIGH_JS))

	def test_strings_translated_and_no_hard_coded_text_or_colour(self):
		ours, others = vi_translations(), other_app_translations()
		for path in (WEIGH_JS, LINEN_JS):
			script = _read(path)
			strings = sorted({match[1] for match in JS_STRING.findall(script)})
			missing = [s for s in strings if not (ours.get(s) or others.get(s))]
			self.assertFalse(missing, f"{os.path.basename(path)}: thiếu dòng vi.csv {missing}")
			for number, line in enumerate(script.splitlines(), 1):
				code = line.split("//", 1)[0]
				self.assertFalse(VIETNAMESE.search(code), f"{number}: {line}")
				self.assertNotRegex(
					code, r"(?<![&\w])#[0-9a-fA-F]{3,6}\b", f"{number}: {line}"
				)  # trừ &#10005; (HTML)

	def test_blocking_error_is_inline_result_reason_action(self):
		source = _read(LINEN_JS)
		self.assertIn("tc-alert-title", source)
		self.assertIn("tc-alert-reason", source)
		self.assertIn("tc-alert-action", source)
		self.assertNotIn("frappe.msgprint", source)
		self.assertNotIn("frappe.show_alert", source)

	def test_css_uses_tokens_only(self):
		css = _read(STATION_CSS)
		block = css[css.index("Thu gom đồ vải (SCR-16") :]
		self.assertNotRegex(block, r"#[0-9a-fA-F]{3,6}\b")
		self.assertNotRegex(re.sub(r"@media[^{]*", "", block), r"\b\d+px\b")


class TestWeighLine(FrappeTestCase):
	def setUp(self):
		if not NODE:
			self.skipTest("Cần Node để chạy mã JS của màn trạm.")

	def test_parse_accepts_comma_and_dot(self):
		out = _node(
			"console.log(JSON.stringify(['12,5','12.5',' 3 ','','abc','-3','1,2,3',null].map(v => TcWeighLine.parse(v))))"
		)
		self.assertEqual(out, [12.5, 12.5, 3, None, None, None, None, None])

	def test_format_uses_a_decimal_comma_and_three_digits(self):
		out = _node(
			"console.log(JSON.stringify([12.5, 3, 0.1234, null, ''].map(v => TcWeighLine.format(v))))"
		)
		self.assertEqual(out, ["12,5", "3", "0,123", "", ""])

	def test_read_returns_kg_from_the_agent(self):
		out = _node(
			"""(async () => {
	const ok = await TcWeighLine.read(async () => ({ ok: true, json: async () => ({ kg: 7.25 }) }));
	const zero = await TcWeighLine.read(async () => ({ ok: true, json: async () => ({ kg: 0 }) }));
	const down = await TcWeighLine.read(async () => ({ ok: false }));
	const broken = await TcWeighLine.read(async () => { throw new TypeError('offline'); });
	console.log(JSON.stringify([ok, zero, down, broken]));
})()"""
		)
		self.assertEqual(out, [{"ok": True, "kg": 7.25}, {"ok": False}, {"ok": False}, {"ok": False}])

	def test_read_gives_up_after_two_seconds(self):
		out = _node(
			"""(async () => {
	const started = Date.now();
	const hung = (url, options) => new Promise((resolve, reject) =>
		options.signal.addEventListener('abort', () => reject(new Error('aborted'))));
	const result = await TcWeighLine.read(hung);
	console.log(JSON.stringify([result, Date.now() - started]));
})()"""
		)
		self.assertEqual(out[0], {"ok": False})
		self.assertTrue(1900 <= out[1] < 4000, out[1])


class TestLinenFormRules(FrappeTestCase):
	TYPES = (
		"[{name: 'Săng', std_weight_kg: 0.5, unit_value: 0}, {name: 'Áo', std_weight_kg: 1, unit_value: 0}]"
	)

	def setUp(self):
		if not NODE:
			self.skipTest("Cần Node để chạy mã JS của màn trạm.")

	def check(self, setup):
		"""Chạy `setup` trên màn mới (biến `lin`) và trả danh sách lỗi `problems()` kèm payload."""
		return _node(
			f"const lin = screen({self.TYPES}); {setup}\n"
			"console.log(JSON.stringify({items: lin.problems(), errors: lin.errors}));"
		)

	def test_empty_form_lists_the_missing_values(self):
		out = self.check("")
		self.assertEqual(
			out["items"],
			[
				"Choose the department.",
				"Type the name of the person who hands the linen over.",
				"Add at least one linen type with pieces or weight.",
			],
		)

	def test_typed_weight_must_be_confirmed(self):  # NFR-AVAIL-04: nhập tay có xác nhận
		base = (
			"lin.form.department = 'K1'; lin.form.delivered_by = 'A';"
			"Object.assign(lin.form.lines[0], {linen_type: 'Săng', qty: '10', weight: '5', source: 'Manual'});"
		)
		self.assertEqual(self.check(base)["items"], ["Confirm the typed weight of Săng."])
		self.assertEqual(self.check(base + "lin.form.lines[0].confirmed = true;")["items"], [])

	def test_scale_reading_needs_no_confirmation(self):
		out = self.check(
			"lin.form.department = 'K1'; lin.form.delivered_by = 'A';"
			"Object.assign(lin.form.lines[0], {linen_type: 'Săng', qty: '10', weight: '5', source: 'Scale'});"
		)
		self.assertEqual(out["items"], [])

	def test_variance_over_fifteen_percent_needs_a_note(self):  # FR-M3-01.4
		base = (
			"lin.form.department = 'K1'; lin.form.delivered_by = 'A';"
			"Object.assign(lin.form.lines[0], {linen_type: 'Săng', qty: '10', weight: '8', source: 'Scale'});"
		)
		self.assertEqual(
			self.check(base)["items"], ["Săng: the weight differs by more than 15 %, enter a note."]
		)
		self.assertEqual(self.check(base + "lin.form.lines[0].variance_note = 'Ướt';")["items"], [])

	def test_exactly_fifteen_percent_needs_no_note(self):
		out = self.check(
			"lin.form.department = 'K1'; lin.form.delivered_by = 'A';"
			"Object.assign(lin.form.lines[0], {linen_type: 'Săng', qty: '10', weight: '5,75', source: 'Scale'});"
		)
		self.assertEqual(out["items"], [])

	def test_line_needs_pieces_or_weight_and_a_known_type(self):
		head = "lin.form.department = 'K1'; lin.form.delivered_by = 'A';"
		self.assertEqual(
			self.check(head + "lin.form.lines[0].linen_type = 'Săng';")["items"],
			["Enter the pieces or the weight of Săng."],
		)
		self.assertEqual(
			self.check(head + "lin.form.lines[0].qty = '3';")["items"],
			["Choose a linen type for a line without a linen type."],
		)

	def test_total_mode_needs_the_cart_weight_and_pieces(self):
		head = (
			"lin.form.department = 'K1'; lin.form.delivered_by = 'A'; lin.form.total_mode = true;"
			"lin.form.lines[0].linen_type = 'Săng';"
		)
		self.assertEqual(
			self.check(head)["items"],
			["Enter the total weight of the cart.", "Enter the pieces of Săng."],
		)
		self.assertEqual(
			self.check(head + "lin.form.lines[0].qty = '10'; lin.form.total_kg = '20';")["items"], []
		)

	def test_payload_maps_the_form_to_the_rpc(self):
		out = _node(
			f"""const lin = screen({self.TYPES});
lin.form.department = 'K1'; lin.form.delivered_by = ' Hộ lý ';
Object.assign(lin.form.lines[0], {{linen_type: 'Săng', qty: '10', weight: '5,1', source: 'Scale', contaminated: true}});
lin.form.lines.push(Object.assign(lin.blankLine('Áo'), {{qty: '2', weight: '2', source: 'Manual', contaminated: false, variance_note: ' Ướt '}}));
lin.form.lines.push(lin.blankLine());
console.log(JSON.stringify(lin.payload()));"""
		)
		self.assertEqual(
			out,
			{
				"station": "TR-LIN",
				"department": "K1",
				"delivered_by": "Hộ lý",
				"lines": [
					{
						"linen_type": "Săng",
						"contaminated": 1,
						"qty": 10,
						"weight_kg": 5.1,
						"weight_source": "Scale",
					},
					{
						"linen_type": "Áo",
						"contaminated": 0,
						"qty": 2,
						"weight_kg": 2,
						"weight_source": "Manual",
						"variance_note": "Ướt",
					},
				],
			},
		)

	def test_payload_in_total_mode_sends_the_cart_weight_without_line_weights(self):
		out = _node(
			f"""const lin = screen({self.TYPES});
lin.form.department = 'K1'; lin.form.delivered_by = 'A'; lin.form.total_mode = true; lin.form.total_kg = '12,5';
Object.assign(lin.form.lines[0], {{linen_type: 'Săng', qty: '10', weight: '9', source: 'Manual'}});
lin.form.note = ' Xe ướt ';
console.log(JSON.stringify(lin.payload()));"""
		)
		self.assertEqual(out["total_kg"], 12.5)
		self.assertEqual(out["note"], "Xe ướt")
		self.assertNotIn("weight_kg", out["lines"][0])

	def test_typed_weight_marks_the_source_manual_and_clears_the_confirmation(self):
		out = _node(
			f"""const lin = screen({self.TYPES});
const line = lin.form.lines[0];
lin.refreshHint = () => {{}}; lin.refreshWeigh = () => {{}};
Object.assign(line, {{linen_type: 'Săng', weight: '5', source: 'Scale', confirmed: true}});
const seen = [];
lin.onLineInput({{type: 'input'}}, line, 'weight_kg', '6');
seen.push([line.source, line.confirmed]);
lin.onLineInput({{type: 'input'}}, line, 'weight_kg', '');
seen.push([line.source, line.confirmed]);
console.log(JSON.stringify(seen));"""
		)
		self.assertEqual(out, [["Manual", False], ["", False]])
