"""Desk SCR-27 (FEAT-044 Task 6): Client Script của Cost Entry, báo cáo Cost by Target và bản dịch.

Kiểm phần đọc được bằng Python/Node: mọi chuỗi qua __() có dòng vi.csv, không chữ Việt/hex trong code, lỗi chặn ghi sổ hiện
kết quả → lý do → hành động ngay trên form, mọi nhãn trường/lựa chọn của DocType (và chuỗi Python mới) có bản dịch, tổng
tỷ lệ tính cùng luật server, danh sách hiện chữ cho mọi trạng thái.
"""

import json
import os
import re
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.costing import setup
from tracecore.tests.test_station_page import JS_STRING, other_app_translations, vi_translations

APP_PATH = frappe.get_app_path("tracecore")
DOCTYPE_DIR = os.path.join(APP_PATH, "costing", "doctype")
FORM_JS = os.path.join(DOCTYPE_DIR, "cost_entry", "cost_entry.js")
LIST_JS = os.path.join(DOCTYPE_DIR, "cost_entry", "cost_entry_list.js")
REPORT_JS = os.path.join(APP_PATH, "costing", "report", "cost_by_target", "cost_by_target.js")
JSONS = tuple(
	os.path.join(DOCTYPE_DIR, name, f"{name}.json")
	for name in ("cost_entry", "cost_allocation", "cost_category", "cost_settings")
)
# chuỗi nguồn của dịch vụ/controller/báo cáo mới (Python), kèm ngữ cảnh dịch nếu có
PYTHON_STRINGS = (
	("Add at least one allocation target before submitting the cost entry.", None),
	("The source document {0} {1} is not submitted, so this cost entry cannot be submitted.", None),
	("Cost category {0} is not active.", None),
	("Amount cannot be negative.", None),
	("Opening Reading", None),
	("Closing Reading", None),
	("{0} is required for a meter source.", None),
	("{0} cannot be negative.", None),
	("Closing Reading cannot be less than Opening Reading.", None),
	("Period To cannot be before Period From.", None),
	("Row {0}: choose the target type and the target.", None),
	("Row {0}: percent must be greater than 0 and at most 100.", None),
	("Row {0}: {1} {2} is already allocated in this entry.", None),
	("The allocation percentages total {0} %, but must total 100 %. Adjust the rows and save again.", None),
	(
		"The cost period starting {0} is closed (locked until {1}). Ask the Head of Department to move the lock date back in Cost Settings.",
		None,
	),
	("Period Closed", None),
	("System cost category {0} cannot be renamed.", None),
	(
		"No cost entry was created because the cost period is closed. Move the lock date back in Cost Settings and enter the cost manually.",
		None,
	),
	("From {0} {1} ({2}).", None),
	("{0} x {1} = {2}", None),
	("Parts: {0}", None),
	("Preventive", "Maintenance Record"),
	("Inspection", "Maintenance Record"),
	("Calibration", "Maintenance Record"),
	("Incident", "Maintenance Record"),
	("Maintenance Record", None),
	("Target Type", None),
	("Target", None),
	("Category", None),
	("Amount", None),
	("Total Cost (VND)", None),
	("From Date", None),
	("To Date", None),
	("From Date and To Date are required.", None),
	("To Date cannot be before From Date.", None),
	("Equipment", None),
	("Zone Station", None),
	("Process Program", None),
)
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)


def _read(path):
	with open(path, encoding="utf-8") as handle:
		return handle.read()


def _function(script, name):
	match = re.search(rf"function {name}\(.*?\n}}\n", script, re.S)
	assert match, name
	return match.group(0)


def _translated(text, ours, others, context=None):
	return bool(ours.get(text) or (context and ours.get(f"{text}:{context}")) or others.get(text))


class TestCostEntryDeskAssets(FrappeTestCase):
	def test_strings_translated_and_no_hard_coded_text_or_colour(self):
		ours, others = vi_translations(), other_app_translations()
		for path in (FORM_JS, LIST_JS, REPORT_JS):
			script = _read(path)
			strings = sorted({match[1] for match in JS_STRING.findall(script)})
			missing = [s for s in strings if not _translated(s, ours, others, "Cost Entry")]
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
		missing = [text for text, context in PYTHON_STRINGS if not _translated(text, ours, others, context)]
		self.assertFalse(missing, f"thiếu dòng vi.csv {missing}")

	def test_system_category_names_are_translated_for_link_display(self):
		ours = vi_translations()
		self.assertTrue(json.loads(_read(JSONS[2])).get("translated_doctype"))
		missing = [name for name in setup.SYSTEM_CATEGORIES if not ours.get(name)]
		self.assertFalse(missing, f"thiếu dòng vi.csv {missing}")

	def test_blocking_error_is_inline_result_reason_action(self):
		script = _read(FORM_JS)
		self.assertIn("alert alert-danger", script)
		for key in ("error.title", "error.reason", "error.action"):
			self.assertIn(key, script)
		self.assertIn("frappe.validated = false", script)
		self.assertNotIn("frappe.msgprint", script)
		self.assertNotIn("frappe.show_alert", script)

	def test_list_indicator_has_text_for_every_state(self):
		script = _read(LIST_JS)
		for state in ("Draft", "Submitted", "Cancelled"):
			self.assertIn(f'__("{state}", null, "Cost Entry")', script)

	def test_allocation_total_and_submit_problem_follow_the_server_rule(self):
		node = shutil.which("node")
		if not node:
			self.skipTest("node not installed")
		script = _read(FORM_JS)
		source = "const TC_COST_TOTAL = 100;\n" + _function(script, "tc_cost_allocation_total")
		source += _function(script, "tc_cost_submit_problem")
		cases = [
			([], "missing"),
			([50, 49], "total"),
			([60, 41], "total"),
			([33.33, 33.33, 33.34], None),
			([100], None),
		]
		program = (
			"const flt = (v, p) => (p === undefined ? Number(v) || 0 : Number((Number(v) || 0).toFixed(p)));\n"
			"const __ = (text, args) => text.replace(/{(\\d+)}/g, (_m, i) => args[i]);\n"
			+ source
			+ "\nconst cases = "
			+ json.dumps(cases)
			+ ";\n"
			+ "const out = cases.map(([percents]) => {\n"
			+ "  const problem = tc_cost_submit_problem({ allocations: percents.map((percent) => ({ percent })) });\n"
			+ "  if (!problem) return null;\n"
			+ "  return problem.title.includes('missing') ? 'missing' : 'total';\n"
			+ "});\nconsole.log(JSON.stringify(out));\n"
		)
		output = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True).stdout
		self.assertEqual(json.loads(output), [expected for _percents, expected in cases])
