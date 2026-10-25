"""Tài sản màn SCR-23 test hằng ngày (FEAT-040): nối vào Page station, chuỗi có bản dịch, không hex/px cứng."""

import csv
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore import hooks

DT_JS = ("public", "js", "station_daily_test.js")
T5_JS = ("public", "js", "station_t5.js")
T2_JS = ("public", "js", "station_t2.js")
STATION_JS = ("ui", "page", "station", "station.js")


def _read(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


class TestStationDailyTestAssets(FrappeTestCase):
	def test_script_is_included_after_t5_and_t2_and_wired(self):
		scripts = hooks.page_js["station"]
		position = scripts.index("public/js/station_daily_test.js")
		self.assertGreater(position, scripts.index("public/js/station_t5.js"))
		self.assertGreater(position, scripts.index("public/js/station_t2.js"))
		self.assertIn('method.startsWith("tracecore.v1.daily_test.")', _read(*STATION_JS))
		self.assertIn('"t5-daily-test": () => this.openDailyTest()', _read(*T5_JS))
		self.assertIn('"t2-daily-test": () => this.openDailyTest()', _read(*T2_JS))
		script = _read(*DT_JS)
		self.assertIn("T5Load.prototype.openDailyTest", script)
		self.assertIn("T2Wash.prototype.openDailyTest", script)

	def test_every_string_has_a_vietnamese_translation(self):
		path = frappe.get_app_path("tracecore", "translations", "vi.csv")
		with open(path, encoding="utf-8", newline="") as handle:
			translated = {row[0] for row in csv.reader(handle) if row}
		sources = re.findall(r'__\(\s*"((?:[^"\\]|\\.)*)"', _read(*DT_JS))
		self.assertTrue(sources)
		self.assertEqual([text for text in sources if text not in translated], [])

	def test_single_required_test_is_preselected_and_back_label_fits_t2_and_t5(self):
		# máy chỉ có một loại test (máy rửa: test làm sạch) thì chọn sẵn, đỡ một chạm; nút quay lại dùng chung cho
		# màn nạp lô T2 và nạp mẻ T5 nên không gọi riêng là "nạp mẻ"
		script = _read(*DT_JS)
		self.assertIn("machine.required.length === 1", script)
		path = frappe.get_app_path("tracecore", "translations", "vi.csv")
		with open(path, encoding="utf-8", newline="") as handle:
			rows = {row[0]: row[1] for row in csv.reader(handle) if row and len(row) > 1}
		self.assertEqual(rows["Back to loading"], "Quay lại màn nạp")

	def test_no_hard_coded_colours_or_pixels_and_no_hover_only_ui(self):
		script = _read(*DT_JS)
		self.assertIsNone(re.search(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b", script))
		self.assertIsNone(re.search(r"\d+px", script))
		self.assertNotIn("mouseover", script)
		self.assertNotIn("contextmenu", script)

	def test_blocking_errors_are_inline_alerts(self):
		script = _read(*DT_JS)
		self.assertRegex(script, r'role="\$\{\s*variant === "error" \? "alert" : "status"\s*\}"')
		for forbidden in ("frappe.msgprint", "frappe.show_alert", "new frappe.ui.Dialog", "console."):
			self.assertNotIn(forbidden, script)
