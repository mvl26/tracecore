"""Mã vạch sang trạm kế tiếp ở màn trạm (A-117, FEAT-080, FR-M9-22): khung chung ở station.js, T1 và T3 gọi."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

APP_PATH = frappe.get_app_path("tracecore")


def read(*parts):
	with open(os.path.join(APP_PATH, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestStationNextAssets(FrappeTestCase):
	def test_shared_frame_in_station_js(self):
		script = read("ui", "page", "station", "station.js")
		self.assertIn("tracecore.v1.station.next_barcode", script)
		self.assertIn("handleNextStationScan", script)
		self.assertIn("^TR-\\d{3}$", script)
		self.assertIn("NEXT_STATION_MISMATCH", script)
		# quét mã trạm kế đi đường đổi trạm có sẵn (A-90/A-91), không tải lại trang
		self.assertIn("this.switchStation(code,", script)
		self.assertIn('data-action="tc-switch-station"', script)

	def test_t1_and_t3_offer_the_next_station(self):
		t1 = read("public", "js", "station_t1.js")
		self.assertIn('offerNextStation("RECEIVE"', t1)
		self.assertIn("this.station.nextStationHtml()", t1)
		t3 = read("public", "js", "station_t3.js")
		self.assertIn('offerNextStation("ASSEMBLE"', t3)
		self.assertNotIn("window.location.assign(`/app/station?station=", t3)

	def test_last_station_is_not_offered_anything(self):
		# T8 (USE) là trạm cuối: không màn nào xin mã sau bước USE
		for name in ("station_t8.js", "station_t7.js"):
			self.assertNotIn('offerNextStation("USE"', read("public", "js", name))

	def test_strings_are_translated(self):
		csv = read("translations", "vi.csv")
		for source in (
			"Scan to go to {0},",
			"This is not the next station,",
			"No station for the next step,",
		):
			self.assertIn(source, csv)
