"""Tài sản màn T8 quét sử dụng (FEAT-027, SCR-37): nối vào Page station, chuỗi có bản dịch, không hex/px cứng."""

import csv
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore import hooks

T8_JS = ("public", "js", "station_t8.js")
STATION_JS = ("ui", "page", "station", "station.js")


def _read(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


class TestStationT8Assets(FrappeTestCase):
	def test_t8_script_is_included_in_station_page(self):
		self.assertIn("public/js/station_t8.js", hooks.page_js["station"])
		station = _read(*STATION_JS)
		self.assertIn("T8Usage", station)
		self.assertIn('method.startsWith("tracecore.v1.usage.")', station)  # RPC cần token phiên thẻ

	def test_every_string_has_a_vietnamese_translation(self):
		with open(
			frappe.get_app_path("tracecore", "translations", "vi.csv"), encoding="utf-8", newline=""
		) as handle:
			translated = {row[0] for row in csv.reader(handle) if row}
		sources = re.findall(r'__\(\s*"((?:[^"\\]|\\.)*)"', _read(*T8_JS))
		self.assertTrue(sources)
		self.assertEqual([text for text in sources if text not in translated], [])

	def test_no_hard_coded_colours_or_pixels_and_no_hover_only_ui(self):
		script = _read(*T8_JS)
		self.assertIsNone(
			re.search(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b", script)
		)  # &#10005; là ký tự HTML, không phải màu
		self.assertIsNone(re.search(r"\d+px", script))
		self.assertNotIn("mouseover", script)
		self.assertNotIn("contextmenu", script)

	def test_blocking_errors_are_inline_alerts_not_modals(self):
		script = _read(*T8_JS)
		self.assertRegex(script, r'role="\$\{\s*variant === "error" \? "alert" : "status"\s*\}"')
		self.assertNotIn("frappe.msgprint", script)
		self.assertNotIn("frappe.show_alert", script)
		self.assertNotIn("new frappe.ui.Dialog", script)

	def test_patient_code_is_never_written_to_logs_or_storage(self):
		script = _read(*T8_JS)
		self.assertNotIn("console.", script)
		self.assertNotIn("localStorage", script)
		self.assertNotIn("sessionStorage", script)
		# ô mã bệnh nhân là ô mật khẩu: không hiện rõ trên màn, trình duyệt không gợi ý lại
		self.assertIn('type: "password"', script)
		self.assertIn('id="tc-t8-late-code" type="password"', script)
