"""Mã lệnh ở màn trạm (A-119, FEAT-083, FR-M9-23): ô quét nhận mã lệnh, form Zone Station in tờ mã lệnh."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

APP_PATH = frappe.get_app_path("tracecore")


def read(*parts):
	with open(os.path.join(APP_PATH, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestStationCommandAssets(FrappeTestCase):
	def test_scan_box_runs_commands_before_handing_the_scan_to_the_screen(self):
		script = read("ui", "page", "station", "station.js")
		self.assertIn("handleCommandScan", script)
		self.assertIn("tracecore.v1.station.commands", script)
		self.assertIn("COMMAND_NOT_AVAILABLE", script)
		# trong `scan`: lệnh được xử lý trước khi mã đi tiếp cho màn hoặc tra bộ
		scan = script[script.index("async scan(raw") :]
		self.assertLess(
			scan.index("await this.handleCommandScan(raw)"), scan.index('"tracecore.v1.set_unit.get"')
		)
		# chỉ bấm nút đang hiện và bật; tab theo khóa màn; trạm qua đường đổi trạm có sẵn
		self.assertIn("!element.disabled", script)
		self.assertIn('[data-action="tc-screen"]', script)
		self.assertIn("this.switchStation(match[1]", script)

	def test_scanner_without_enter_runs_complete_commands_after_a_short_wait(self):
		script = read("ui", "page", "station", "station.js")
		self.assertIn("CMD-(?:DO|TAB)-", script)
		self.assertIn("150", script)

	def test_old_complete_load_code_stays_with_the_screens(self):
		self.assertIn("HOAN-THANH-NAP", read("public", "js", "station_t2.js"))
		self.assertIn("HOAN-THANH-NAP", read("public", "js", "station_t5.js"))
		self.assertNotIn(
			'"HOAN-THANH-NAP"', read("ui", "page", "station", "station.js")
		)  # khung không đọc mã này

	def test_zone_station_form_prints_the_sheet(self):
		script = read("public", "js", "zone_station.js")
		self.assertIn("tracecore.v1.station.command_sheet", script)
		self.assertIn("tcPrintPdfAndTell", script)
		self.assertEqual(frappe.get_hooks()["doctype_js"]["Zone Station"], ["public/js/zone_station.js"])

	def test_commands_map_every_selector_to_a_real_button(self):
		# mỗi bộ chọn trong bảng lệnh phải trỏ tới data-action có trong một file màn trạm
		from tracecore.core import command_codes

		screens = (
			"".join(
				read("public", "js", name)
				for name in (
					"station_t1.js",
					"station_t2.js",
					"station_t3.js",
					"station_t4.js",
					"station_t5.js",
					"station_t5b.js",
					"station_t6.js",
					"station_t7.js",
					"station_t8.js",
				)
			)
			+ read("ui", "page", "station", "station.js")
			+ read("ui", "page", "station", "station.html")
		)
		for key, command in command_codes.COMMANDS.items():
			for selector in command["selectors"]:
				action = selector.split('data-action="', 1)[1].split('"', 1)[0]
				self.assertTrue(
					f'"{action}"' in screens or f"{action}" in screens,
					f"{key}: không thấy data-action {action}",
				)
