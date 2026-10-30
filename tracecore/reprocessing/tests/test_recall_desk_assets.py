"""Desk SCR-14 (FEAT-029 Task 5): Client Script của Recall Order và nút lập lệnh trên Sterilization Load.

Kiểm phần đọc được bằng Python: mọi chuỗi qua __() và mọi nhãn/lựa chọn của DocType có dòng vi.csv, không chữ Việt/hex
trong code, lỗi chặn inline kết quả → lý do → hành động, nút gọi đúng RPC, danh sách hiện chữ cho mọi trạng thái.
"""

import json
import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.test_station_page import JS_STRING, other_app_translations, vi_translations

APP_PATH = frappe.get_app_path("tracecore")
DOCTYPE_DIR = os.path.join(APP_PATH, "reprocessing", "doctype")
FORM_JS = os.path.join(DOCTYPE_DIR, "recall_order", "recall_order.js")
LIST_JS = os.path.join(DOCTYPE_DIR, "recall_order", "recall_order_list.js")
LOAD_JS = os.path.join(DOCTYPE_DIR, "sterilization_load", "sterilization_load.js")
T5B_JS = os.path.join(APP_PATH, "public", "js", "station_t5b.js")
JSONS = (
	os.path.join(DOCTYPE_DIR, "recall_order", "recall_order.json"),
	os.path.join(DOCTYPE_DIR, "recall_order_pack", "recall_order_pack.json"),
)
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)


def _read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def _translated(text, ours, others, context=None):
	return bool(ours.get(text) or (context and ours.get(f"{text}:{context}")) or others.get(text))


class TestRecallDeskAssets(FrappeTestCase):
	def test_strings_translated_and_no_hard_coded_text_or_colour(self):
		ours, others = vi_translations(), other_app_translations()
		for path in (FORM_JS, LIST_JS, LOAD_JS, T5B_JS):
			script = _read(path)
			strings = sorted({match[1] for match in JS_STRING.findall(script)})
			missing = [s for s in strings if not _translated(s, ours, others, "Recall Order")]
			self.assertFalse(missing, f"{os.path.basename(path)}: thiếu dòng vi.csv {missing}")
			if path == T5B_JS:
				continue
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

	def test_blocking_error_is_inline_and_buttons_call_the_rpcs(self):
		script = _read(FORM_JS) + _read(LOAD_JS)
		self.assertIn("alert alert-danger", script)
		for key in ("error.title", "error.reason", "error.action"):
			self.assertIn(key, script)
		self.assertNotIn("frappe.msgprint", script)
		self.assertIn('"tracecore.v1.recall.create"', script)
		self.assertIn('TC_RECALL_API = "tracecore.v1.recall."', script)
		for method in ('"confirm_pack"', '"close"'):
			self.assertIn(method, script)

	def test_list_indicator_has_text_for_every_status(self):
		script = _read(LIST_JS)
		for status in ("Open", "Closed"):
			self.assertIn(f"{status}:", script)
		self.assertIn('__(doc.status, null, "Recall Order")', script)
