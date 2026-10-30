"""RPC tracecore.v1.station.config (FEAT-018 Task 9, D11): cấu hình máy in của trạm cho Station Agent."""

import uuid

import frappe

from tracecore.setup.provision import agent_user_email
from tracecore.tests.factories import deactivate_printers, make_label_items, make_printer, make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import station as station_api

# Printer liên kết Item (nhãn đang lắp) của ERPNext; site CI mới chưa chạy Setup Wizard (xem factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

TS = "2026-10-20T09:00:00+07:00"


def call(station, **kwargs):
	with request_headers({"X-Idempotency-Key": str(uuid.uuid4()), "X-TC-Station": "TR-004"}):
		return station_api.config(station=station, client_ts=TS, **kwargs)


class TestStationConfig(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.get_doc("User", "Administrator").add_roles("TC R10")
		deactivate_printers("TR-004")
		deactivate_printers("TR-005")
		self.steam_label, self.plasma_label = make_label_items()
		# các máy in tạo khi còn là Administrator; agent không có quyền ghi Printer
		self.agent = make_user(agent_user_email("TR-004"), roles=["TC Agent"])
		self.addCleanup(frappe.set_user, "Administrator")

	def test_station_config_for_agent(self):
		mine = make_printer("TR-004", self.steam_label, host="192.168.1.50", name="Máy hấp")
		make_printer("TR-005", self.plasma_label, name="Máy trạm khác")
		frappe.set_user(self.agent)
		result = call("TR-004")
		self.assertEqual(result["station"]["name"], "TR-004")
		self.assertEqual(
			result["printers"],
			[
				{
					"name": mine,
					"host": "192.168.1.50",
					"port": 9100,
					"language": "ZPL",
					"label_type": self.steam_label,
					"method": "Steam",
				}
			],
		)

	def test_station_config_lists_only_active_printers(self):
		active = make_printer("TR-004", self.steam_label, name="Máy chạy")
		inactive = make_printer("TR-004", self.plasma_label, name="Máy nghỉ")
		frappe.db.set_value("Printer", inactive, "is_active", 0)
		frappe.set_user(self.agent)
		self.assertEqual([printer["name"] for printer in call("TR-004")["printers"]], [active])

	def test_station_config_without_printers_is_empty(self):
		frappe.set_user(self.agent)
		self.assertEqual(call("TR-004")["printers"], [])

	def test_agent_of_another_station_is_forbidden(self):
		frappe.set_user(self.agent)
		with self.assertRaises(frappe.PermissionError):
			call("TR-005")

	def test_station_config_requires_agent_role(self):
		frappe.set_user(make_user("config-not-agent@example.com", roles=["TC R04"]))
		with self.assertRaises(frappe.PermissionError):
			call("TR-004")

	def test_unknown_station_is_rejected(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			call("TR-999")

	def test_system_manager_may_read_any_station(self):
		frappe.set_user("Administrator")
		self.assertEqual(call("TR-005")["station"]["name"], "TR-005")

	def test_station_config_includes_station_and_active_peripherals(self):
		station = frappe.get_doc("Zone Station", "TR-004")
		station.peripherals = []
		station.append(
			"peripherals", {"peripheral_type": "Scanner", "model": "Zebra DS2208", "connection": "USB HID"}
		)
		station.append(
			"peripherals",
			{
				"peripheral_type": "Scale",
				"model": "Ohaus",
				"connection": "Serial",
				"serial_port": "COM3",
				"baud_rate": 9600,
			},
		)
		station.append(
			"peripherals",
			{
				"peripheral_type": "Scanner",
				"model": "Old",
				"connection": "TCP",
				"host": "10.0.0.9",
				"port": 23,
				"is_active": 0,
			},
		)
		station.save()
		frappe.set_user(self.agent)
		result = call("TR-004")
		self.assertEqual(
			result["station"],
			{
				"name": "TR-004",
				"label": "T4 Packing",
				"zone": station.parent_zone,
				"zone_type": "Clean",
				"step": "T4",
				"is_active": 1,
			},
		)
		self.assertEqual(
			[(row["peripheral_type"], row["model"], row["connection"]) for row in result["peripherals"]],
			[("Scanner", "Zebra DS2208", "USB HID"), ("Scale", "Ohaus", "Serial")],
		)
		scale = result["peripherals"][1]
		self.assertEqual((scale["serial_port"], scale["baud_rate"]), ("COM3", 9600))
		self.assertEqual(
			set(scale), {"peripheral_type", "model", "connection", "host", "port", "serial_port", "baud_rate"}
		)

	def test_station_config_of_inactive_station_is_409_rejection(self):
		frappe.db.set_value("Zone Station", "TR-004", "is_active", 0)
		frappe.local.response.pop("http_status_code", None)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		frappe.set_user(self.agent)
		result = call("TR-004")
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["code"], "STATION_INACTIVE")
		self.assertEqual(result["error"]["http_status"], 409)
		self.assertIn("TR-004", result["error"]["reason"])
		self.assertEqual(frappe.local.response.get("http_status_code"), 409)
		self.assertNotIn("printers", result)
