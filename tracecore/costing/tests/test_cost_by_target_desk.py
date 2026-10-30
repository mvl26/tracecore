"""Báo cáo Cost by Target trên Desk (FEAT-044, FR-M7-02.3): ô Đối tượng gợi ý theo Loại đối tượng, tiêu đề có bản dịch,
tiền VND không lẻ (CLAUDE.md: "VND không lẻ")."""

import json
import os
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.costing.report.cost_by_target import cost_by_target
from tracecore.tests.test_station_page import vi_translations

APP_PATH = frappe.get_app_path("tracecore")
REPORT_JS = os.path.join(APP_PATH, "costing", "report", "cost_by_target", "cost_by_target.js")
COST_ENTRY_JSON = os.path.join(APP_PATH, "costing", "doctype", "cost_entry", "cost_entry.json")


class TestCostByTargetDesk(FrappeTestCase):
	def test_target_filter_takes_its_doctype_from_the_target_type_filter(self):
		# Frappe tìm <input data-fieldname="target_type"> nhưng Loại đối tượng là <select>: phải có get_options riêng
		node = shutil.which("node")
		if not node:
			self.skipTest("node not installed")
		program = (
			"const __ = (t) => t; const frappe = { datetime: { month_start: () => '', month_end: () => '' },"
			" query_reports: {}, query_report: { get_filter_value: (f) => (f === 'target_type' ? 'Equipment' : null) } };\n"
			+ open(REPORT_JS, encoding="utf-8").read()
			+ "\nconst target = frappe.query_reports['Cost by Target'].filters.find((f) => f.fieldname === 'target');"
			+ "\nconsole.log(JSON.stringify(target.get_options ? target.get_options() : null));"
		)
		output = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True).stdout
		self.assertEqual(json.loads(output), "Equipment")

	def test_report_title_is_translated(self):
		self.assertTrue(vi_translations().get("Cost by Target"))

	def test_amounts_have_no_decimals(self):
		columns = cost_by_target._columns()
		amount = next(c for c in columns if c["fieldname"] == "amount")
		self.assertEqual(amount.get("precision"), 0)
		summary = cost_by_target.execute({"from_date": "2031-01-01", "to_date": "2031-01-31"})[4][0]
		self.assertEqual(summary["datatype"], "Int")
		self.assertIn("VND", summary["label"])
		field = next(
			f
			for f in json.load(open(COST_ENTRY_JSON, encoding="utf-8"))["fields"]
			if f["fieldname"] == "amount"
		)
		self.assertEqual(str(field.get("precision")), "0")
