"""Desk SCR-24 (FEAT-041 Task 5): Client Script của Item / Stock Entry nối qua hook, chuỗi qua ``__()`` có bản dịch.

Hành vi trên trình duyệt kiểm bằng Playwright (Task 6); ở đây kiểm phần đọc được bằng Python: hook, file script,
chuỗi hiển thị, CSS chỉ dùng token, danh sách nhóm bắt buộc hạn dùng khớp server.
"""

import csv
import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.inventory import items

APP_PATH = frappe.get_app_path("tracecore")
SCRIPTS = ("item.js", "stock_entry.js", "stock_entry_list.js")
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
# __("text") hoặc __("text", args, "Context"); chuỗi nằm trên một dòng, nháy kép
TRANSLATED = re.compile(r'__\(\s*"((?:[^"\\]|\\.)*)"(?:\s*,\s*[^,()]*(?:\([^)]*\))?\s*,\s*"([^"]*)")?')


def _read(*parts):
	with open(os.path.join(APP_PATH, *parts), encoding="utf-8") as handle:
		return handle.read()


def _code(name):
	"""Nội dung script bỏ chú thích (// và /* */)."""
	text = re.sub(r"/\*.*?\*/", "", _read("public", "js", name), flags=re.S)
	return re.sub(r"(^|\s)//[^\n]*", r"\1", text)


def _vi_keys():
	with open(os.path.join(APP_PATH, "translations", "vi.csv"), encoding="utf-8", newline="") as handle:
		rows = [row for row in csv.reader(handle) if len(row) >= 2]
	return {(row[0], row[2] if len(row) > 2 else "") for row in rows}, {row[0] for row in rows}


class TestDeskInventory(FrappeTestCase):
	def test_hooks_register_stock_entry_scripts(self):
		self.assertIn("public/js/item.js", frappe.get_hooks("doctype_js").get("Item", []))
		self.assertIn("public/js/stock_entry.js", frappe.get_hooks("doctype_js").get("Stock Entry", []))
		self.assertIn(
			"public/js/stock_entry_list.js", frappe.get_hooks("doctype_list_js").get("Stock Entry", [])
		)
		for name in SCRIPTS:
			self.assertTrue(os.path.exists(os.path.join(APP_PATH, "public", "js", name)), name)

	def test_scripts_use_translated_strings_and_no_vietnamese_literals(self):
		for name in SCRIPTS:
			for number, line in enumerate(_code(name).splitlines(), 1):
				self.assertFalse(VIETNAMESE.search(line), f"{name}:{number}: {line}")
		for name in ("stock_entry.js", "stock_entry_list.js"):
			self.assertIn("__(", _code(name), name)

	def test_vi_csv_has_all_new_strings(self):
		with_context, plain = _vi_keys()
		missing = []
		for name in SCRIPTS:
			for text, context in TRANSLATED.findall(_code(name)):
				text = text.replace('\\"', '"')
				if (text, context) not in with_context and text not in plain:
					missing.append(f"{name}: {text!r}")
		self.assertFalse(missing, "\n".join(missing))

	def test_custom_field_labels_and_options_have_context_translation(self):
		"""Desk dịch nhãn và lựa chọn Select với context = tên DocType; dòng context khác (Pack, Process Program…) không áp."""
		cases = []
		for fieldname in ("tc_item_group_cssd", "tc_compatible_method"):
			options = frappe.get_meta("Item").get_field(fieldname).options.split("\n")
			cases += [("Item", option) for option in options if option]
		for doctype in ("Item", "Stock Entry", "Stock Entry Detail"):
			cases += [
				(doctype, field.label)
				for field in frappe.get_meta(doctype).fields
				if field.fieldname.startswith("tc_") and field.label
			]
		same_in_vietnamese = {"Plasma"}  # thuật ngữ giữ nguyên
		frappe.local.lang = "vi"
		try:
			untranslated = sorted(
				f"{doctype}: {text}"
				for doctype, text in cases
				if text not in same_in_vietnamese and frappe._(text, context=doctype) == text
			)
		finally:
			frappe.local.lang = "en"
		self.assertFalse(untranslated, "\n".join(untranslated))
		# "Expiry Date" đã có dòng context Pack: Stock Entry Detail cần dòng riêng
		self.assertIn(("Expiry Date", "Stock Entry Detail"), _vi_keys()[0])

	def test_scripts_use_tokens_only(self):
		"""R4: không hex/px trong script (kể cả chuỗi CSS chèn từ JS); màu và cỡ chỉ qua biến --tc-*."""
		literal = re.compile(r"(?<!&)#[0-9a-fA-F]{3,8}\b|(?<![\w-])\d+(?:\.\d+)?px\b")
		for name in SCRIPTS:
			for number, line in enumerate(_code(name).splitlines(), 1):
				self.assertFalse(literal.search(line), f"{name}:{number}: {line}")
		self.assertIn("var(--tc-fail", _code("stock_entry_list.js"))
		self.assertIn("var(--tc-warn", _code("stock_entry_list.js"))

	def test_item_js_keeps_roll_buttons(self):
		script = _code("item.js")
		self.assertIn('__("Issue roll codes")', script)
		self.assertIn('__("Print roll labels")', script)
		self.assertIn("tracecore.codes.issue_rolls_dialog(frm)", script)
		self.assertIn("tracecore.codes.roll_labels_dialog(frm)", script)

	def test_item_js_expiry_groups_match_server(self):
		"""JS chỉ phản chiếu để người dùng thấy ngay; server (inventory.items) mới quyết định. Hai danh sách phải trùng."""
		script = _code("item.js")
		block = re.search(r"TC_EXPIRY_REQUIRED_GROUPS\s*=\s*\[(.*?)\]", script, re.S)
		self.assertTrue(block, "TC_EXPIRY_REQUIRED_GROUPS not found")
		self.assertEqual(set(re.findall(r'"([^"]+)"', block.group(1))), set(items.EXPIRY_REQUIRED_GROUPS))
		self.assertIn(items.VALUATION_METHOD, script)

	def test_excel_dialog_uses_import_rpcs_with_fresh_key_per_write(self):
		script = _code("stock_entry_list.js")
		for method in (
			"tracecore.v1.inventory.receipt_template",
			"tracecore.v1.inventory.receipt_check",
			"tracecore.v1.inventory.receipt_import",
		):
			self.assertIn(f'"{method}"', script, method)
		# ghi: một lần ghi = một request (khóa X-Idempotency-Key); bấm lại cùng lần ghi giữ nguyên request
		self.assertIn("tracecore.codes.new_request(", script)
		self.assertIn("tracecore.codes.send(", script)
		# lỗi chặn inline, không toast/modal
		self.assertNotIn("frappe.msgprint", script)
		self.assertNotIn("frappe.show_alert", script)
		self.assertIn("alert-error", script)
		self.assertIn("RATE_ZERO", script)
