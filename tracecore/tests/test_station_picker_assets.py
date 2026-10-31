"""Tài sản chọn tay trên trạm (A-68): nối vào Page station, chuỗi có bản dịch, token --tc-*, RPC quét mang cách nhập."""

import csv
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore import hooks
from tracecore.v1 import (
	assembly,
	issue,
	load,
	pack,
	putaway,
	receive,
	usage,
	wash,
)

PICKER_JS = ("public", "js", "station_picker.js")
STATION_JS = ("ui", "page", "station", "station.js")
STATION_HTML = ("ui", "page", "station", "station.html")
STATION_CSS = ("ui", "page", "station", "station.css")


def _read(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


class TestStationPickerAssets(FrappeTestCase):
	def test_picker_is_included_and_wired_into_the_shell(self):
		self.assertIn("public/js/station_picker.js", hooks.page_js["station"])
		station = _read(*STATION_JS)
		self.assertIn("new TcPicker(this)", station)
		self.assertIn('method.startsWith("tracecore.v1.lookup.")', station)  # lookup cần token phiên thẻ
		self.assertIn('entry_mode: "Manual"', station)
		self.assertIn('data-action="manual-pick"', _read(*STATION_HTML))

	def test_every_string_has_a_vietnamese_translation(self):
		with open(
			frappe.get_app_path("tracecore", "translations", "vi.csv"), encoding="utf-8", newline=""
		) as handle:
			translated = {row[0] for row in csv.reader(handle) if row}
		for parts in (PICKER_JS,):
			sources = re.findall(r'__\(\s*"((?:[^"\\]|\\.)*)"', _read(*parts))
			self.assertTrue(sources)
			self.assertEqual([text for text in sources if text not in translated], [], parts)
		self.assertIn("Choose by hand", translated)  # nút ở station.html

	def test_no_hard_coded_colours_or_pixels_and_no_hover_only_ui(self):
		for parts in (PICKER_JS,):
			script = _read(*parts)
			self.assertIsNone(re.search(r"(?<![&\w])#[0-9a-fA-F]{3,8}\b", script))
			self.assertIsNone(re.search(r"\d+px", script))
			for banned in (
				"mouseover",
				"contextmenu",
				"dragstart",
				"touchmove",
				"frappe.msgprint",
				"new frappe.ui.Dialog",
			):
				self.assertNotIn(banned, script)
		css = _read(*STATION_CSS).split("chọn tay thiết bị", 1)[1]
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", css))
		self.assertIsNone(re.search(r"\d+px", css))
		self.assertIn("var(--tc-touch-min)", css)

	def test_every_scan_method_listed_in_the_picker_accepts_entry_mode(self):
		listed = re.findall(r'"(tracecore\.v1\.[a-z_]+\.[a-z_]+)"', _read(*PICKER_JS))
		by_name = {
			"wash": wash,
			"load": load,
			"pack": pack,
			"putaway": putaway,
			"usage": usage,
			"receive": receive,
			"assembly": assembly,
			"issue": issue,
		}
		scan_methods = [m for m in listed if not m.startswith("tracecore.v1.lookup.")]
		self.assertEqual(len(scan_methods), 10)
		for method in scan_methods:
			_, _, module, name = method.split(".")
			fn = getattr(by_name[module], name)
			params = fn.__wrapped__ if hasattr(fn, "__wrapped__") else fn
			# station_session bọc hàm; tham số nằm ở hàm gốc
			while hasattr(params, "__wrapped__"):
				params = params.__wrapped__
			self.assertIn("entry_mode", params.__code__.co_varnames, method)
