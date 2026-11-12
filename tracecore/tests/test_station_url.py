"""NAV-07: địa chỉ Page trạm theo Số trạm (/app/station/<số>), link cũ ?station= vẫn chạy."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

URL = "public/js/tc_station_url.js"


def _read(*path):
	with open(frappe.get_app_path("tracecore", *path), encoding="utf-8") as handle:
		return handle.read()


class TestStationUrl(FrappeTestCase):
	def _js(self, body):
		return run_js(self, [URL], [["TcStationUrl"]], body)

	def test_path_uses_station_number_when_known(self):
		out = self._js(
			"""
			const p = TcStationUrl.path;
			emit([p("TR-001", 1), p("TR-001", "7"), p("TR-090", 0), p("TR 9", null), p("", 3), p(null, null)]);
			"""
		)
		self.assertEqual(
			out,
			[
				"/app/station/1",
				"/app/station/7",
				"/app/station?station=TR-090",
				"/app/station?station=TR%209",
				"/app/station/3",
				"/app/station",
			],
		)

	def test_parse_reads_number_or_legacy_code(self):
		out = self._js(
			"""
			const q = TcStationUrl.parse;
			emit([q("/app/station/1", ""), q("/app/station/12/", ""), q("/app/station", "?station=TR-001"),
				q("/app/station/2", "?station=TR-005"), q("/app/station/x", ""), q("/app/station", ""),
				q("/app/station/0", "")]);
			"""
		)
		self.assertEqual(
			out,
			[
				{"no": 1, "name": None},
				{"no": 12, "name": None},
				{"no": None, "name": "TR-001"},
				# mã trạm trên URL thắng số (link cũ có cả hai thì theo mã)
				{"no": 2, "name": "TR-005"},
				{"no": None, "name": None},
				{"no": None, "name": None},
				{"no": None, "name": None},
			],
		)

	def test_remembers_number_for_offline_kiosk(self):
		out = self._js(
			"""
			const store = {};
			const s = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }};
			const broken = {getItem: () => { throw new Error("x"); }, setItem: () => { throw new Error("x"); }};
			const before = TcStationUrl.recall(s, 1);
			TcStationUrl.remember(s, 1, "TR-001");
			TcStationUrl.remember(s, 0, "TR-090");
			emit([before, TcStationUrl.recall(s, 1), TcStationUrl.recall(s, 0), TcStationUrl.recall(broken, 1),
				TcStationUrl.remember(broken, 1, "TR-001") === undefined, TcStationUrl.recall(null, 1)]);
			"""
		)
		self.assertEqual(out, [None, "TR-001", None, None, True, None])

	def test_station_page_and_links_use_the_helper(self):
		station = _read("ui", "page", "station", "station.js")
		self.assertIn("TcStationUrl.parse(", station)
		self.assertIn("station_no: this.stationNo", station)
		self.assertIn("TcStationUrl.path(", station)
		self.assertIn("TcStationUrl.remember(", station)
		self.assertNotIn("/app/station?station=", station)
		for path in (("ui", "page", "tracecore", "tracecore.js"), ("public", "js", "station_help.js")):
			source = _read(*path)
			self.assertIn("TcStationUrl.path(", source, path)
			self.assertNotIn("/app/station?station=", source, path)
		bundle = _read("public", "js", "tracecore.bundle.js")
		self.assertIn('import "./tc_station_url.js"', bundle)

	def test_missing_station_message_mentions_new_address(self):
		vi = _read("translations", "vi.csv")
		self.assertIn("The kiosk address has no station number (/app/station/1).", vi)
