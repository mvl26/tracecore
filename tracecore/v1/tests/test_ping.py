from datetime import datetime, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase

import tracecore
from tracecore import v1


class TestPing(FrappeTestCase):
	def test_ping_fields(self):
		result = v1.ping()
		self.assertEqual(result["app"], "tracecore")
		self.assertEqual(result["version"], tracecore.__version__)
		self.assertEqual(result["site"], frappe.local.site)
		self.assertEqual(result["time_zone"], "Asia/Ho_Chi_Minh")
		server_time = datetime.fromisoformat(result["server_time"])
		self.assertEqual(server_time.utcoffset(), timedelta(hours=7))
		self.assertIsNone(result["station"])
		self.assertIsNone(result["station_error"])
		self.assertIsNone(result["agent"])

	def test_ping_station_info(self):
		result = v1.ping(station="TR-004")
		self.assertEqual(
			result["station"], {"name": "TR-004", "label": "T4 Packing", "step": "T4", "zone_type": "Clean"}
		)
		self.assertIsNone(result["station_error"])

	def test_ping_unknown_station(self):
		for station in ("TR-999", "ZONE-CLEAN"):
			result = v1.ping(station=station)
			self.assertIsNone(result["station"], msg=station)
			self.assertEqual(result["station_error"]["code"], "STATION_NOT_FOUND", msg=station)
			self.assertIn(station, result["station_error"]["reason"])
