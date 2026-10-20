import frappe
from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

from tracecore.core import code_registry
from tracecore.patches.v0_1 import activate_existing_stations, register_station_codes
from tracecore.tests.utils import IsolatedTestCase, bru

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


def make_station(zone, step=None, **kwargs):
	return frappe.get_doc(
		{
			"doctype": "Zone Station",
			"zone_station_name": "Test station",
			"is_zone": 0,
			"parent_zone": zone,
			"station_step": step,
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
		self.assertEqual(station.station_step, "T4")
		self.assertEqual(station.is_active, 1)

	def test_station_takes_zone_type_from_parent(self):
		doc = make_station("ZONE-STERILE", "T6", zone_type="Dirty")
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
		station = make_station("ZONE-CLEAN", "T4")
		row = frappe.db.get_value(
			"Code Registry", station.name, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
		)
		self.assertIsNotNone(row)
		self.assertEqual(
			(row.prefix, row.ref_doctype, row.ref_name, row.status),
			("TR", "Zone Station", station.name, "Active"),
		)

	def test_code_registration_idempotent(self):
		station = make_station("ZONE-CLEAN", "T4")
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
			make_station("ZONE-DIRTY", "T4")
		make_station("ZONE-DIRTY", "T2")

	def test_moving_station_to_other_zone_type_checks_step(self):
		station = make_station("ZONE-CLEAN", "T4")
		station.parent_zone = "ZONE-DIRTY"
		with self.assertRaises(frappe.ValidationError):
			station.save()

	def test_removing_zone_deactivates_station(self):
		station = make_station("ZONE-CLEAN", "T4")
		self.assertEqual(station.is_active, 1)
		station.parent_zone = None
		station.save()
		station.reload()
		self.assertEqual(station.is_active, 0)
		self.assertFalse(station.zone_type)

	def test_zone_type_change_blocked_when_stations_conflict(self):
		zone = make_zone("Clean")
		station = make_station(zone.name, "T4")
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
		make_station(zone.name, "T1")
		zone.zone_type = "Department"
		with self.assertRaises(frappe.ValidationError):
			zone.save()
		empty = make_zone("Dirty")
		make_station(empty.name)  # trạm chưa có bước
		empty.zone_type = "Sterile"
		empty.save()
		children = frappe.get_all("Zone Station", filters={"parent_zone": empty.name}, pluck="zone_type")
		self.assertEqual(children, ["Sterile"])
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{"ref_doctype": "Zone Station", "action": "Update", "new_value": ("like", "%Sterile%")},
			)
		)

	@bru("BRU-ID-006")
	def test_zone_station_cannot_be_deleted(self):
		station = make_station("ZONE-CLEAN", "T4")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Zone Station", station.name, force=True)
		self.assertTrue(frappe.db.exists("Zone Station", station.name))

	def test_creating_station_writes_audit_log(self):
		station = make_station("ZONE-CLEAN", "T4")
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "Zone Station", "ref_name": station.name, "action": "Create"}
			)
		)

	def test_permissions_match_e8(self):
		validate_permissions_for_doctype("Zone Station")
		perms = {p.role: p for p in frappe.get_meta("Zone Station").permissions if p.permlevel == 0}
		for role in ("System Manager", "TC R10"):
			for right in ("read", "write", "create", "report"):
				self.assertEqual(perms[role].get(right), 1, f"{role}.{right}")
		for role in ("TC R01", "TC R02", "TC R09"):
			self.assertEqual(perms[role].read, 1, role)
			self.assertFalse(perms[role].write or perms[role].create, role)
		for p in perms.values():
			self.assertFalse(p.delete, p.role)

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
