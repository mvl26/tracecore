"""Desk SCR-28 (FEAT-045 Task 5): form Cost Rate Version, danh sách và bản dịch.

Kiểm phần đọc được bằng Python: mọi chuỗi qua __() có dòng vi.csv, không chữ Việt/hex trong code, nút A1 chỉ hiện ở bản Nháp,
mọi nhãn trường/lựa chọn của ba DocType và chuỗi Python mới có bản dịch, danh sách hiện chữ cho mọi trạng thái.
"""

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.costing.tests.test_cost_entry_desk_assets import VIETNAMESE, _read, _translated
from tracecore.tests.test_station_page import JS_STRING, other_app_translations, vi_translations

DOCTYPE_DIR = os.path.join(frappe.get_app_path("tracecore"), "costing", "doctype")
FORM_JS = os.path.join(DOCTYPE_DIR, "cost_rate_version", "cost_rate_version.js")
LIST_JS = os.path.join(DOCTYPE_DIR, "cost_rate_version", "cost_rate_version_list.js")
JSONS = tuple(
	os.path.join(DOCTYPE_DIR, name, f"{name}.json")
	for name in ("cost_rate_version", "cost_rate_line", "cost_norm_line")
)
PYTHON_STRINGS = (
	"Row {0}: choose the item of this unit price.",
	"Row {0}: a {1} price has no item. Clear the item.",
	"Row {0}: {1} already has a price in this version.",
	"Row {0}: the unit price cannot be negative.",
	"Row {0}: the unit price of {1} is 0.",
	"Row {0}: pack type {1} already has a norm for {2}.",
	"Row {0}: the quantity per pack cannot be negative.",
	"Row {0}: the norm of {1} for pack type {2} is 0.",
	"These active programs have no consumption norm, so their loads cannot be costed: {0}",
	"Add at least one unit price before approving the price list.",
	"Price list {0} is already approved from {1}, so a version starting {2} would overlap it. Choose a date after {1}.",
	"Effective dates overlap",
	"Price list {0} starts later and replaces this one. Cancel {0} first.",
	"Only a draft price list can take prices from stock.",
	"date must be a date in YYYY-MM-DD form.",
	"Labor",
	"Electricity",
	"Tap Water",
	"RO Water",
	"Steam",
)


class TestCostRateVersionDeskAssets(FrappeTestCase):
	def test_strings_translated_and_no_hard_coded_text_or_colour(self):
		ours, others = vi_translations(), other_app_translations()
		for path in (FORM_JS, LIST_JS):
			script = _read(path)
			strings = sorted({match[1] for match in JS_STRING.findall(script)})
			missing = [s for s in strings if not _translated(s, ours, others, "Cost Rate Version")]
			self.assertFalse(missing, f"{os.path.basename(path)}: thiếu dòng vi.csv {missing}")
			for number, line in enumerate(script.splitlines(), 1):
				code = line.split("//", 1)[0]
				self.assertFalse(VIETNAMESE.search(code), f"{number}: {line}")
				self.assertNotRegex(code, r"#[0-9a-fA-F]{3,6}\b", f"{number}: {line}")

	def test_doctype_labels_and_options_are_translated(self):
		ours, others = vi_translations(), other_app_translations()
		missing = []
		for path in JSONS:
			meta = json.loads(_read(path))
			texts = [meta["name"]]
			for field in meta["fields"]:
				texts += [field.get("label"), field.get("description")]
				if field["fieldtype"] == "Select":
					texts.extend((field.get("options") or "").split("\n"))
			missing += [text for text in texts if text and not _translated(text, ours, others, meta["name"])]
		self.assertFalse(sorted(set(missing)), "thiếu dòng vi.csv")

	def test_python_strings_are_translated(self):
		ours, others = vi_translations(), other_app_translations()
		missing = [text for text in PYTHON_STRINGS if not _translated(text, ours, others)]
		self.assertFalse(missing, f"thiếu dòng vi.csv {missing}")

	def test_fill_button_only_on_draft_and_calls_the_form_method(self):
		script = _read(FORM_JS)
		self.assertIn("frm.doc.docstatus === 0", script)
		self.assertIn('method: "fill_from_stock"', script)

	def test_list_indicator_has_text_for_every_state(self):
		script = _read(LIST_JS)
		for state in ("Draft", "Approved", "Cancelled"):
			self.assertIn(f'__("{state}", null, "Cost Rate Version")', script)
