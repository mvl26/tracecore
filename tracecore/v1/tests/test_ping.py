from datetime import datetime, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase

import tracecore
from tracecore import v1
from tracecore.tests.utils import IsolatedTestCase


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
		station = result["station"]
		self.assertEqual(
			(
				station["name"],
				station["label"],
				station["functions"],
				station["station_no"],
				station["zone_type"],
			),
			("TR-004", "T4 Packing", ["PACK"], 4, "Clean"),
		)
		self.assertEqual(station["zone_color"], "clean")
		self.assertEqual(station["gate_labels"]["T4"], "Packing")
		self.assertTrue(station["screens"])
		self.assertIsNone(result["station_error"])

	def test_ping_unknown_station(self):
		for station in ("TR-999", "ZONE-CLEAN"):
			result = v1.ping(station=station)
			self.assertIsNone(result["station"], msg=station)
			self.assertEqual(result["station_error"]["code"], "STATION_NOT_FOUND", msg=station)
			self.assertIn(station, result["station_error"]["reason"])


class TestPingInactiveStation(IsolatedTestCase):
	def test_ping_inactive_station(self):
		frappe.db.set_value("Zone Station", "TR-004", "is_active", 0)
		result = v1.ping(station="TR-004")
		self.assertIsNone(result["station"])
		error = result["station_error"]
		self.assertEqual(error["code"], "STATION_INACTIVE")
		for key in ("title", "reason", "action"):
			self.assertTrue(error[key], msg=key)
		self.assertIn("TR-004", error["reason"])


class TestPingByStationNumber(FrappeTestCase):
	"""NAV-07: kiosk mở /app/station/<số trạm>; ping đổi số trạm thành mã trạm."""

	def test_number_resolves_to_station(self):
		result = v1.ping(station_no="4")
		self.assertEqual(result["station"]["name"], "TR-004")
		self.assertEqual(result["station"]["station_no"], 4)
		self.assertIsNone(result["station_error"])

	def test_code_wins_over_number(self):
		result = v1.ping(station="TR-004", station_no=1)
		self.assertEqual(result["station"]["name"], "TR-004")

	def test_unknown_number_is_a_blocking_error(self):
		for number in (987, "abc", 0):
			result = v1.ping(station_no=number)
			self.assertIsNone(result["station"], number)
			error = result["station_error"]
			self.assertEqual(error["code"], "STATION_NOT_FOUND", number)
			for key in ("title", "reason", "action"):
				self.assertTrue(error[key], msg=key)

	def test_duplicate_number_is_a_blocking_error(self):
		from unittest.mock import patch

		with patch("frappe.get_all", return_value=["TR-004", "TR-099"]):
			result = v1.ping(station_no=4)
		self.assertIsNone(result["station"])
		self.assertEqual(result["station_error"]["code"], "STATION_NUMBER_DUPLICATE")
		self.assertIn("TR-099", result["station_error"]["reason"])
