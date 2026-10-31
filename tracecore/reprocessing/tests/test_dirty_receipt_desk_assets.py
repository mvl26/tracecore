"""Form Desk Dirty Receipt: xác nhận thành phần theo bộ (FR-M2-23, UC-05). Luật hiển thị chạy thật trong Node."""

import csv
import json
import os
import re
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

FORM_JS = frappe.get_app_path("tracecore", "reprocessing", "doctype", "dirty_receipt", "dirty_receipt.js")
VI_CSV = frappe.get_app_path("tracecore", "translations", "vi.csv")
NODE = shutil.which("node")
VIETNAMESE = re.compile(r"[àáảãạăắằẳẵặâấầẩẫậđèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]", re.I)

DOC = """
const doc = {
	docstatus: 1,
	items: [
		{ set_unit: 'SET-B', set_name: 'Bo B', needs_review: 0 },
		{ set_unit: 'SET-A', set_name: 'Bo A', needs_review: 1, abnormal_note: 'Gay <kep>' },
	],
	confirm_lines: [
		{ set_unit: 'SET-A', instrument: 'I-3', instrument_name: 'Keo', qty: 2, position: 3, confirmed: 0 },
		{ set_unit: 'SET-A', instrument: 'I-1', instrument_name: 'Kep', qty: 1, position: 1, confirmed: 1 },
		{ set_unit: 'SET-B', instrument: 'I-2', instrument_name: 'Nhip', qty: 5, position: 1, confirmed: 1 },
	],
};
"""


def _node(script):
	prelude = f"""
const handlers = {{}};
const __ = (text, args) => args ? text.replace(/\\{{(\\d+)\\}}/g, (m, i) => String(args[i])) : text;
const frappe = {{
	ui: {{ form: {{ on: (doctype, events) => {{ handlers[doctype] = events; }} }} }},
	utils: {{ escape_html: (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }},
}};
const cint = (value) => parseInt(value, 10) || 0;
function holder() {{
	const element = {{ html(value) {{ element.content = value; return element; }}, on(event, selector, fn) {{ element.click = fn; return element; }}, insertBefore() {{ return element; }} }};
	return element;
}}
const $ = () => holder();
const fs = require('fs');
const exported = new Function('__', 'frappe', 'cint', '$', fs.readFileSync({json.dumps(FORM_JS)}, 'utf8') +
	'; return {{ tc_receipt_groups, tc_receipt_total_text, tc_receipt_sets_html, tc_receipt_render }};')(__, frappe, cint, $);
const {{ tc_receipt_groups, tc_receipt_total_text, tc_receipt_sets_html, tc_receipt_render }} = exported;
function form(name) {{
	const frm = {{
		doc: {{ ...doc, name }}, docname: name, hidden: [],
		fields_dict: {{ confirm_lines: {{ wrapper: {{}} }} }},
		set_df_property(field, property, value) {{ frm.hidden.push([field, property, value]); }},
	}};
	return frm;
}}
{DOC}
"""
	completed = subprocess.run(
		[NODE, "-e", prelude + script], capture_output=True, text=True, timeout=30, check=False
	)
	assert completed.returncode == 0, completed.stderr
	return json.loads(completed.stdout.strip().splitlines()[-1])


class TestDirtyReceiptFormGrouping(FrappeTestCase):
	def setUp(self):
		if not NODE:
			self.skipTest("node is not installed")

	def test_sets_follow_the_items_order_and_lines_follow_position(self):
		out = _node(
			"""
console.log(JSON.stringify(tc_receipt_groups(doc).map((group) => [
	group.item.set_unit, group.lines.map((line) => line.position), group.confirmed, group.lines.length,
])));
"""
		)
		self.assertEqual(out, [["SET-B", [1], 1, 1], ["SET-A", [1, 3], 1, 2]])

	def test_total_counts_sets_and_instruments(self):
		out = _node("console.log(JSON.stringify(tc_receipt_total_text(tc_receipt_groups(doc))));")
		self.assertEqual(out, "2 sets, 2/3 instruments confirmed")

	def test_full_set_is_green_and_short_set_is_orange(self):
		out = _node(
			"""
const html = tc_receipt_sets_html(doc);
const [full, short] = html.split('<details').slice(1);
console.log(JSON.stringify({
	full: full.includes('1/1 confirmed') && full.includes('--tc-pass'),
	short: short.includes('1/2 confirmed') && short.includes('--tc-warn-fill'),
}));
"""
		)
		self.assertEqual(out, {"full": True, "short": True})

	def test_a_set_without_lines_is_not_shown_as_complete(self):
		out = _node(
			"""
const html = tc_receipt_sets_html({ items: [{ set_unit: 'SET-C', set_name: 'Bo C' }], confirm_lines: [] });
console.log(JSON.stringify({ orange: html.includes('--tc-warn-fill'), green: html.includes('--tc-pass') }));
"""
		)
		self.assertEqual(out, {"orange": True, "green": False})

	def test_review_label_and_note_only_on_the_flagged_set(self):
		out = _node(
			"""
const [clean, flagged] = tc_receipt_sets_html(doc).split('<details').slice(1);
console.log(JSON.stringify({
	clean: clean.includes('Needs Review'),
	flagged: flagged.includes('Needs Review') && flagged.includes('--tc-fail'),
	note: flagged.includes('Gay &lt;kep&gt;'),
}));
"""
		)
		self.assertEqual(out, {"clean": False, "flagged": True, "note": True})

	def test_rows_show_position_name_code_quantity_and_a_mark(self):
		out = _node(
			"""
const flagged = tc_receipt_sets_html(doc).split('<details')[2];
const rows = flagged.split('<tr').slice(2);
console.log(JSON.stringify({
	first: ['>1<', 'Kep', 'I-1', '>1<', '✓'].every((part) => rows[0].includes(part)),
	second: ['>3<', 'Keo', 'I-3', '>2<', '✗', 'Missing'].every((part) => rows[1].includes(part)),
	order: rows[0].includes('Kep') && rows[1].includes('Keo'),
}));
"""
		)
		self.assertEqual(out, {"first": True, "second": True, "order": True})


class TestDirtyReceiptFormView(FrappeTestCase):
	def setUp(self):
		if not NODE:
			self.skipTest("node is not installed")

	def test_opens_by_set_and_hides_the_original_grid(self):
		out = _node(
			"""
const frm = form('RC-1');
tc_receipt_render(frm);
console.log(JSON.stringify({ hidden: frm.hidden.at(-1), html: frm.tc_receipt.holder.content.includes('<details') }));
"""
		)
		self.assertEqual(out, {"hidden": ["confirm_lines", "hidden", 1], "html": True})

	def test_toggle_shows_the_original_grid_with_the_total_kept(self):
		out = _node(
			"""
const frm = form('RC-1');
tc_receipt_render(frm);
frm.tc_receipt.holder.click();
const combined = { hidden: frm.hidden.at(-1), sets: frm.tc_receipt.holder.content.includes('<details'),
	total: frm.tc_receipt.holder.content.includes('2/3 instruments confirmed'),
	label: frm.tc_receipt.holder.content.includes('View by set') };
frm.tc_receipt.holder.click();
console.log(JSON.stringify({ combined, back: frm.hidden.at(-1), label: frm.tc_receipt.holder.content.includes('View combined list') }));
"""
		)
		self.assertEqual(
			out,
			{
				"combined": {
					"hidden": ["confirm_lines", "hidden", 0],
					"sets": False,
					"total": True,
					"label": True,
				},
				"back": ["confirm_lines", "hidden", 1],
				"label": True,
			},
		)

	def test_another_receipt_opens_by_set_again(self):
		out = _node(
			"""
const frm = form('RC-1');
tc_receipt_render(frm);
frm.tc_receipt.holder.click();
frm.docname = 'RC-2';
tc_receipt_render(frm);
console.log(JSON.stringify(frm.hidden.at(-1)));
"""
		)
		self.assertEqual(out, ["confirm_lines", "hidden", 1])

	def test_refresh_is_wired_on_the_form(self):
		out = _node("console.log(JSON.stringify(handlers['Dirty Receipt'].refresh === tc_receipt_render));")
		self.assertTrue(out)


class TestDirtyReceiptFormAssets(FrappeTestCase):
	def _source(self):
		with open(FORM_JS, encoding="utf-8") as handle:
			return re.sub(r"//.*", "", handle.read())

	def test_no_vietnamese_text_or_hex_colours_in_the_code(self):
		source = self._source()
		self.assertIsNone(VIETNAMESE.search(source))
		self.assertIsNone(re.search(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b", source))

	def test_every_string_has_a_vietnamese_translation(self):
		with open(VI_CSV, encoding="utf-8", newline="") as handle:
			rows = [(row[0], row[2] if len(row) > 2 else "") for row in csv.reader(handle) if row]
		for text, context in re.findall(
			r'__\(\s*"([^"]+)"(?:,\s*(?:\[[^\]]*\]|null)(?:,\s*"([^"]+)")?)?', self._source()
		):
			self.assertIn((text, context), rows)
