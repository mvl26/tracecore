import json

import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

from tracecore.core import code_registry, zones
from tracecore.patches.v0_1 import activate_existing_stations, register_station_codes
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

test_ignore = ["User"]

FIXTURE_STATIONS = [f"TR-00{n}" for n in range(1, 8)]


def make_zone(zone_type="Clean", **kwargs):
	return frappe.get_doc(
		{
			"doctype": "Zone Station",
			"zone_station_name": "Test zone",
			"is_zone": 1,
			"zone_type": zone_type,
			**kwargs,
		}
	).insert()


def make_station(zone, *functions, **kwargs):
	return frappe.get_doc(
		{
			"doctype": "Zone Station",
			"zone_station_name": "Test station",
			"is_zone": 0,
			"parent_zone": zone,
			"functions": [{"station_function": function} for function in functions],
			**kwargs,
		}
	).insert()


class TestZoneStation(IsolatedTestCase):
	def test_fixture_zones(self):
		for zone, zone_type in (
			("ZONE-DIRTY", "Dirty"),
			("ZONE-CLEAN", "Clean"),
			("ZONE-STERILE", "Sterile"),
		):
			doc = frappe.get_doc("Zone Station", zone)
			self.assertEqual(doc.is_zone, 1)
			self.assertEqual(doc.zone_type, zone_type)

		station = frappe.get_doc("Zone Station", "TR-004")
		self.assertEqual(station.is_zone, 0)
		self.assertEqual(station.parent_zone, "ZONE-CLEAN")
		self.assertEqual(station.zone_type, "Clean")
		self.assertEqual([row.station_function for row in station.functions], ["PACK"])
		self.assertEqual(station.station_no, 4)
		self.assertEqual(station.is_active, 1)

	def test_is_zone_cannot_change_after_creation(self):
		"""F3: khu không thành trạm và ngược lại (set_only_once + chặn ở server)."""
		self.assertEqual(frappe.get_meta("Zone Station").get_field("is_zone").set_only_once, 1)
		zone = make_zone("Clean")
		station = make_station(zone.name, "PACK")
		for doc, value in ((zone, 0), (station, 1)):
			with self.subTest(doc=doc.name):
				doc.reload()
				doc.is_zone = value
				with self.assertRaises(frappe.ValidationError):
					doc.save()
				self.assertEqual(frappe.db.get_value("Zone Station", doc.name, "is_zone"), 1 - value)

	def test_is_zone_guard_in_controller(self):
		"""Chặn ở validate kể cả khi set_only_once của Frappe bị bỏ qua (ví dụ đổi meta)."""
		station = make_station("ZONE-CLEAN", "PACK")
		station.is_zone = 1
		with self.assertRaises(frappe.ValidationError) as raised:
			station.run_method("validate")
		self.assertIn(station.name, str(raised.exception))

	def test_station_form_links_printers(self):
		"""F4: form trạm hiện máy in của trạm (Printer.station)."""
		links = [(row.link_doctype, row.link_fieldname) for row in frappe.get_meta("Zone Station").links]
		self.assertIn(("Printer", "station"), links)

	def test_station_takes_zone_type_from_parent(self):
		doc = make_station("ZONE-STERILE", "PUTAWAY", zone_type="Dirty")
		self.assertTrue(doc.name.startswith("TR-"))
		self.assertEqual(doc.zone_type, "Sterile")

	def test_new_zone_named_zone_series(self):
		zone = make_zone("Department")
		self.assertRegex(zone.name, r"^ZONE-\d{2}$")
		self.assertEqual(frappe.db.get_value("Zone Station", "ZONE-DIRTY", "zone_type"), "Dirty")

	def test_zone_requires_zone_type(self):
		with self.assertRaises(frappe.ValidationError):
			make_zone(None)

	def test_station_requires_zone_parent(self):
		# không khu: lưu được nhưng không hoạt động (FR-M9-03.3)
		station = frappe.get_doc(
			{"doctype": "Zone Station", "zone_station_name": "Bad station", "is_zone": 0}
		).insert()
		self.assertEqual(station.is_active, 0)
		# khu cha là trạm: lỗi
		with self.assertRaises(frappe.ValidationError):
			make_station("TR-001")

	@bru("BRU-ID-006")
	def test_station_code_registered(self):
		station = make_station("ZONE-CLEAN", "PACK")
		row = frappe.db.get_value(
			"Code Registry", station.name, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
		)
		self.assertIsNotNone(row)
		self.assertEqual(
			(row.prefix, row.ref_doctype, row.ref_name, row.status),
			("TR", "Zone Station", station.name, "Active"),
		)

	def test_code_registration_idempotent(self):
		station = make_station("ZONE-CLEAN", "PACK")
		station.run_method("after_insert")
		self.assertEqual(frappe.db.count("Code Registry", {"code": station.name}), 1)

	def test_patch_registers_fixture_stations(self):
		frappe.db.delete("Code Registry", {"code": ("in", FIXTURE_STATIONS)})
		register_station_codes.execute()
		for name in FIXTURE_STATIONS:
			self.assertTrue(code_registry.is_issued(name), name)
			self.assertEqual(frappe.db.get_value("Code Registry", name, "prefix"), "TR")
		register_station_codes.execute()
		self.assertEqual(frappe.db.count("Code Registry", {"code": ("in", FIXTURE_STATIONS)}), 7)

	def test_station_without_zone_saved_inactive(self):
		station = frappe.get_doc(
			{"doctype": "Zone Station", "zone_station_name": "No zone", "is_zone": 0, "is_active": 1}
		).insert()
		self.assertEqual(station.is_active, 0)
		self.assertFalse(station.zone_type)

	def test_cannot_activate_station_without_zone(self):
		station = frappe.get_doc(
			{"doctype": "Zone Station", "zone_station_name": "No zone", "is_zone": 0}
		).insert()
		station.is_active = 1
		with self.assertRaises(frappe.ValidationError):
			station.save()
		# gán khu thì bật được
		station.reload()
		station.parent_zone = "ZONE-CLEAN"
		station.is_active = 1
		station.save()
		self.assertEqual(station.is_active, 1)

	@bru("BRU-FLOW-001")
	def test_station_step_must_match_zone(self):
		with self.assertRaises(frappe.ValidationError):
			make_station("ZONE-DIRTY", "PACK")
		make_station("ZONE-DIRTY", "WASH_LOAD")

	def test_moving_station_to_other_zone_type_checks_step(self):
		station = make_station("ZONE-CLEAN", "PACK")
		station.parent_zone = "ZONE-DIRTY"
		with self.assertRaises(frappe.ValidationError):
			station.save()

	def test_removing_zone_deactivates_station(self):
		station = make_station("ZONE-CLEAN", "PACK")
		self.assertEqual(station.is_active, 1)
		station.parent_zone = None
		station.save()
		station.reload()
		self.assertEqual(station.is_active, 0)
		self.assertFalse(station.zone_type)

	def test_zone_type_change_blocked_when_stations_conflict(self):
		zone = make_zone("Clean")
		station = make_station(zone.name, "PACK")
		zone.zone_type = "Dirty"
		with self.assertRaises(frappe.ValidationError):
			zone.save()
		# trạm không hoạt động thì không chặn
		station.is_active = 0
		station.save()
		zone.reload()
		zone.zone_type = "Dirty"
		zone.save()
		self.assertEqual(frappe.db.get_value("Zone Station", station.name, "zone_type"), "Dirty")
		# kích hoạt lại: bước phải được kiểm lại
		station.reload()
		station.is_active = 1
		with self.assertRaises(frappe.ValidationError):
			station.save()

	def test_zone_type_change_allowed_when_steps_valid(self):
		zone = make_zone("Dirty")
		make_station(zone.name, "RECEIVE")
		zone.zone_type = "Department"
		with self.assertRaises(frappe.ValidationError):
			zone.save()
		empty = make_zone("Dirty")
		child = make_station(empty.name)  # trạm chưa có bước
		empty.zone_type = "Sterile"
		empty.save()
		self.assertEqual(frappe.db.get_value("Zone Station", child.name, "zone_type"), "Sterile")
		log = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Zone Station", "ref_name": child.name, "action": "Update"},
			fields=["old_value", "new_value"],
		)
		self.assertEqual(len(log), 1)
		self.assertEqual(json.loads(log[0].old_value), {"zone_type": "Dirty"})
		self.assertEqual(json.loads(log[0].new_value), {"zone_type": "Sterile"})

	def test_station_no_unique_among_active_stations(self):
		with self.assertRaises(frappe.ValidationError) as raised:
			make_station("ZONE-CLEAN", "PACK", station_no=4)
		self.assertIn("TR-004", str(raised.exception))
		make_station("ZONE-CLEAN", "PACK", station_no=4, is_active=0)
		make_station("ZONE-CLEAN", "PACK", station_no=11)
		make_station("ZONE-CLEAN", "PACK")  # không đánh số: không trùng

	def test_two_stations_same_function_and_station_with_two_functions(self):
		first = make_station("ZONE-CLEAN", "ASSEMBLE", "PACK", station_no=12)
		second = make_station("ZONE-CLEAN", "ASSEMBLE", "PACK", station_no=13)
		self.assertLess(
			zones.stations_with_function("PACK").index(first.name),
			zones.stations_with_function("PACK").index(second.name),
		)
		with self.assertRaises(frappe.ValidationError):
			make_station("ZONE-CLEAN", "PACK", "PACK")

	def test_number_against_process_only_warns(self):
		frappe.clear_messages()
		station = make_station("ZONE-DIRTY", "RECEIVE", station_no=40)
		self.assertTrue(station.name)
		self.assertTrue(any("40" in str(message) for message in frappe.get_message_log()))

	@bru("BRU-FLOW-001")
	def test_new_zone_type_and_function_work_by_config_only(self):
		frappe.get_doc(
			{
				"doctype": "Zone Type",
				"type_name": "TEST Vùng đồ vải",
				"functions": [{"station_function": "LINEN"}, {"station_function": "RECEIVE"}],
			}
		).insert()
		zone = make_zone("TEST Vùng đồ vải", zone_station_name="Vùng đồ vải")
		station = make_station(zone.name, "LINEN", station_no=21)
		self.assertEqual(station.zone_type, "TEST Vùng đồ vải")
		with self.assertRaises(frappe.ValidationError):
			make_station(zone.name, "PACK")

	def test_zone_in_use_cannot_be_turned_off(self):
		zone = frappe.get_doc("Zone Station", "ZONE-CLEAN")
		zone.is_active = 0
		with self.assertRaises(frappe.ValidationError) as raised:
			zone.save()
		self.assertIn("TR-004", str(raised.exception))
		empty = make_zone("Clean")
		empty.is_active = 0
		empty.save()
		with self.assertRaises(frappe.ValidationError):
			make_station(empty.name, "PACK")

	def test_locations_follow_allowed_functions_of_zone_type(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{"doctype": "Sterile Location", "location_name": "Bad", "zone_station": "ZONE-CLEAN"}
			).insert()
		frappe.get_doc(
			{
				"doctype": "Zone Type",
				"type_name": "TEST Kho phụ",
				"functions": [{"station_function": "PUTAWAY"}],
			}
		).insert()
		zone = make_zone("TEST Kho phụ")
		frappe.get_doc({"doctype": "Sterile Location", "location_name": "Good", "zone_station": zone.name}).insert()

	@bru("BRU-ID-006")
	def test_zone_station_cannot_be_deleted(self):
		station = make_station("ZONE-CLEAN", "PACK")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Zone Station", station.name, force=True)
		self.assertTrue(frappe.db.exists("Zone Station", station.name))

	def test_creating_station_writes_audit_log(self):
		station = make_station("ZONE-CLEAN", "PACK")
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "Zone Station", "ref_name": station.name, "action": "Create"}
			)
		)

	def test_permissions_match_e8(self):
		validate_permissions_for_doctype("Zone Station")
		assert_permission_matrix(self, "Zone Station")
		perms = {p.role: p for p in frappe.get_meta("Zone Station").permissions if p.permlevel == 0}
		for role in ("TC R10",):
			for right in ("read", "write", "create", "report"):
				self.assertEqual(perms[role].get(right), 1, f"{role}.{right}")
		for role in ("TC R01", "TC R02", "TC R09"):
			self.assertEqual(perms[role].read, 1, role)
			self.assertFalse(perms[role].write or perms[role].create, role)
		# FEAT-004 A-37 d (FR-M9-16): chỉ R10 có delete (on_trash vẫn chặn danh mục đã có giao dịch)
		for p in perms.values():
			self.assertEqual(bool(p.delete), p.role == "TC R10", p.role)

	def test_patch_activates_existing_stations(self):
		frappe.db.set_value("Zone Station", "TR-004", "is_active", 0)
		frappe.db.set_value("Zone Station", "ZONE-CLEAN", "is_active", 0)
		orphan = frappe.get_doc(
			{"doctype": "Zone Station", "zone_station_name": "No zone", "is_zone": 0}
		).insert()
		activate_existing_stations.execute()
		self.assertEqual(frappe.db.get_value("Zone Station", "TR-004", "is_active"), 1)
		self.assertEqual(frappe.db.get_value("Zone Station", "ZONE-CLEAN", "is_active"), 1)
		self.assertEqual(frappe.db.get_value("Zone Station", orphan.name, "is_active"), 0)


def peripheral(**kwargs):
	row = {"peripheral_type": "Scanner", "connection": "USB HID", "is_active": 1}
	row.update(kwargs)
	return row


class TestStationPeripheral(IsolatedTestCase):
	def _station(self, *rows):
		station = make_station("ZONE-CLEAN", "PACK")
		for row in rows:
			station.append("peripherals", row)
		return station

	def test_hid_scanner_needs_nothing_else(self):
		station = self._station(peripheral())
		station.save()
		self.assertEqual(len(station.peripherals), 1)

	def test_tcp_requires_host_and_port(self):
		for row in (
			peripheral(connection="TCP", port=9100),
			peripheral(connection="TCP", host="  ", port=9100),
			peripheral(connection="TCP", host="10.0.0.5"),
			peripheral(connection="TCP", host="10.0.0.5", port=0),
			peripheral(connection="TCP", host="10.0.0.5", port=65536),
		):
			with self.subTest(row=row), self.assertRaises(frappe.ValidationError):
				self._station(row).save()
		station = self._station(peripheral(connection="TCP", host=" 10.0.0.5 ", port=65535))
		station.save()
		self.assertEqual(station.peripherals[0].host, "10.0.0.5")

	def test_serial_requires_port_and_defaults_baud(self):
		with self.assertRaises(frappe.ValidationError):
			self._station(peripheral(connection="Serial")).save()
		station = self._station(peripheral(connection="Serial", serial_port="COM3"))
		station.save()
		self.assertEqual(station.peripherals[0].baud_rate, 9600)
		station.peripherals[0].baud_rate = 115200
		station.save()
		self.assertEqual(station.peripherals[0].baud_rate, 115200)

	def test_duplicate_endpoint_rejected(self):
		tcp = {"connection": "TCP", "host": "10.0.0.5", "port": 9100}
		with self.assertRaises(frappe.ValidationError):
			self._station(peripheral(**tcp), peripheral(**{**tcp, "host": "10.0.0.5 "})).save()
		with self.assertRaises(frappe.ValidationError):
			self._station(
				peripheral(**{**tcp, "host": "Scale.Local"}), peripheral(**{**tcp, "host": "scale.local"})
			).save()
		com = {"connection": "Serial", "serial_port": "COM3"}
		with self.assertRaises(frappe.ValidationError):
			self._station(peripheral(**com), peripheral(**{**com, "serial_port": "com3"})).save()
		# khác cổng, hoặc dòng không hoạt động: hợp lệ
		self._station(peripheral(**tcp), peripheral(**{**tcp, "port": 9101})).save()
		self._station(peripheral(**tcp), peripheral(**tcp, is_active=0)).save()

	def test_fields_of_other_connections_are_cleared(self):
		"""F5: đổi kiểu kết nối thì bỏ host/port (không phải TCP) và cổng serial/baud (không phải Serial)."""
		station = self._station(
			peripheral(connection="TCP", host="10.0.0.5", port=9100, serial_port="COM3", baud_rate=9600),
			peripheral(connection="Serial", serial_port="COM4", baud_rate=19200, host="10.0.0.6", port=9101),
			peripheral(host="10.0.0.7", port=9102, serial_port="COM5", baud_rate=4800),
		)
		station.save()
		tcp, serial, hid = station.peripherals
		self.assertEqual((tcp.host, tcp.port, tcp.serial_port, tcp.baud_rate), ("10.0.0.5", 9100, None, 0))
		self.assertEqual(
			(serial.host, serial.port, serial.serial_port, serial.baud_rate), (None, 0, "COM4", 19200)
		)
		self.assertEqual((hid.host, hid.port, hid.serial_port, hid.baud_rate), (None, 0, None, 0))

	def test_zone_cannot_have_peripherals(self):
		zone = make_zone("Clean")
		zone.append("peripherals", peripheral())
		with self.assertRaises(frappe.ValidationError):
			zone.save()

	def test_scale_cannot_be_hid(self):
		with self.assertRaises(frappe.ValidationError):
			self._station(peripheral(peripheral_type="Scale")).save()
		self._station(peripheral(peripheral_type="Scale", connection="Serial", serial_port="COM4")).save()

	def test_peripheral_change_audited(self):
		station = make_station("ZONE-CLEAN", "PACK")
		station.append("peripherals", peripheral(model="Zebra DS2208"))
		station.save()
		logs = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Zone Station", "ref_name": station.name, "action": "Update"},
			fields=["old_value", "new_value"],
		)
		self.assertEqual(len(logs), 1)
		new = json.loads(logs[0].new_value)
		self.assertEqual(json.loads(logs[0].old_value), {"peripherals": []})
		self.assertEqual(new["peripherals"][0]["model"], "Zebra DS2208")
		self.assertEqual(new["peripherals"][0]["connection"], "USB HID")
		station.reload()
		station.save()
		self.assertEqual(
			frappe.db.count(
				"Audit Log", {"ref_doctype": "Zone Station", "ref_name": station.name, "action": "Update"}
			),
			1,
		)
