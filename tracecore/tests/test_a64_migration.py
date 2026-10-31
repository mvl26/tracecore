"""Migration A-64 (FEAT-051): patch ánh xạ theo mã cũ, sơ đồ yhct, năng lực theo CSV (AC-1, AC-8)."""

import csv
import os
import tempfile

import frappe
from frappe.utils import add_days, now_datetime

from tracecore.core import zones
from tracecore.patches.v0_1 import a64_configurable_stations as patch
from tracecore.setup import migrate_a64
from tracecore.tests.factories import make_employee
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["User", "Employee", "Department"]


def _strip_functions(station):
	frappe.db.delete("Zone Station Function", {"parent": station, "parenttype": "Zone Station"})


class TestPatch(IsolatedTestCase):
	def test_maps_legacy_steps_and_runs_twice(self):
		for station, step in (("TR-002", "T2"), ("TR-005", "T5"), ("TR-004", "T4")):
			_strip_functions(station)
			frappe.db.set_value("Zone Station", station, {"legacy_step": step, "station_no": 0})
		patch.execute()
		patch.execute()
		self.assertEqual(zones.station_functions("TR-002"), ["WASH_LOAD", "WASH_UNLOAD"])
		self.assertEqual(zones.station_functions("TR-005"), ["STERI_LOAD", "STERI_UNLOAD"])
		self.assertEqual(zones.station_functions("TR-004"), ["PACK"])
		self.assertEqual(frappe.db.get_value("Zone Station", "TR-005", "station_no"), 5)

	def test_step_without_mapping_gets_no_function_and_no_error(self):
		"""T9/T10 từ Property Setter tạm: sơ đồ riêng của site gán sau."""
		_strip_functions("TR-007")
		frappe.db.set_value("Zone Station", "TR-007", {"legacy_step": "T9", "station_no": 0})
		patch.execute()
		self.assertEqual(zones.station_functions("TR-007"), [])
		self.assertEqual(frappe.db.get_value("Zone Station", "TR-007", "station_no"), 9)

	def test_removes_temporary_property_setter(self):
		frappe.make_property_setter(
			{
				"doctype": "Zone Station",
				"fieldname": "legacy_step",
				"property": "options",
				"value": "T9",
				"property_type": "Text",
			}
		)
		name = frappe.db.get_value("Property Setter", {"doc_type": "Zone Station", "property": "options"})
		frappe.rename_doc("Property Setter", name, patch.TEMP_PROPERTY_SETTER, force=True)
		patch.execute()
		self.assertFalse(frappe.db.exists("Property Setter", patch.TEMP_PROPERTY_SETTER))

	def test_counts_are_unchanged(self):
		before = {doctype: frappe.db.count(doctype) for doctype in migrate_a64.COUNTED}
		patch.execute()
		self.assertEqual(before, {doctype: frappe.db.count(doctype) for doctype in migrate_a64.COUNTED})


class TestYhctPlan(IsolatedTestCase):
	def test_dry_run_changes_nothing(self):
		before = zones.station_functions("TR-004")
		result = migrate_a64.apply_yhct(dry_run=True)
		self.assertEqual(len(result), 11)
		self.assertEqual(zones.station_functions("TR-004"), before)
		self.assertFalse(frappe.db.exists("Zone Station", "TR-010"))

	def test_applies_ten_numbered_stations_without_validation_error(self):
		migrate_a64.apply_yhct(dry_run=False)
		self.assertEqual(zones.station_functions("TR-002"), ["MANUAL_WASH"])
		self.assertEqual(zones.station_functions("TR-003"), ["WASH_LOAD"])
		self.assertEqual(zones.station_functions("TR-006"), ["ASSEMBLE", "PACK"])
		self.assertEqual(frappe.db.get_value("Zone Station", "TR-008", "zone_type"), "Sterile")
		self.assertEqual(frappe.db.get_value("Zone Station", "TR-010", "station_no"), 10)
		self.assertEqual(zones.missing_functions(), [])

	def test_station_with_documents_is_replaced_not_redefined(self):
		original = migrate_a64.station_documents
		migrate_a64.station_documents = lambda station, links=None: {"Pack": 1} if station == "TR-003" else {}
		try:
			result = migrate_a64.apply_yhct(dry_run=False)
		finally:
			migrate_a64.station_documents = original
		row = next(item for item in result if item["no"] == 3)
		self.assertEqual((row["action"], row["retired"]), ("replaced", "TR-003"))
		self.assertEqual(frappe.db.get_value("Zone Station", "TR-003", "is_active"), 0)
		self.assertEqual(zones.station_functions("TR-003"), ["ASSEMBLE"])
		self.assertEqual(zones.station_functions(row["station"]), ["WASH_LOAD"])
		self.assertEqual(frappe.db.get_value("Zone Station", row["station"], "station_no"), 3)


class TestCompetencyCsv(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		employee = make_employee(card="A64-" + frappe.generate_hash(length=8).upper())
		self.employee = employee if isinstance(employee, str) else employee.name
		frappe.db.set_value("Zone Station", "TR-003", "legacy_step", "T3")
		self.competency = (
			frappe.get_doc(
				{
					"doctype": "Station Competency",
					"employee": self.employee,
					"station": "TR-003",
					"valid_from": now_datetime(),
					"valid_until": add_days(now_datetime(), 30),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		handle = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
		handle.close()
		self.path = handle.name
		self.addCleanup(os.unlink, self.path)
		migrate_a64.competency_csv(self.path)

	def _rows(self):
		with open(self.path, newline="", encoding="utf-8-sig") as handle:
			return list(csv.DictReader(handle))

	def _decide(self, decide):
		rows = self._rows()
		for row in rows:
			decide(row)
		with open(self.path, "w", newline="", encoding="utf-8-sig") as handle:
			writer = csv.DictWriter(handle, fieldnames=migrate_a64.CSV_FIELDS)
			writer.writeheader()
			writer.writerows(rows)

	def test_export_suggests_stations_with_same_old_function(self):
		row = next(item for item in self._rows() if item["competency"] == self.competency)
		self.assertEqual(row["old_function"], "ASSEMBLE")
		self.assertIn("TR-003", row["suggested_stations"])
		self.assertEqual((row["new_stations"], row["approved"]), ("", ""))

	def test_undecided_row_refuses_whole_file(self):
		with self.assertRaises(frappe.ValidationError):
			migrate_a64.apply_competency_csv(self.path, dry_run=False)
		self.assertEqual(frappe.db.get_value("Station Competency", self.competency, "is_active"), 1)

	def test_apply_keeps_old_record_and_copies_to_new_stations(self):
		def decide(row):
			if row["competency"] == self.competency:
				row.update(approved="1", new_stations="TR-004;TR-001")
			else:
				row.update(approved="0")

		self._decide(decide)
		total = frappe.db.count("Station Competency")
		migrate_a64.apply_competency_csv(self.path, dry_run=True)
		self.assertEqual(frappe.db.count("Station Competency"), total)
		migrate_a64.apply_competency_csv(self.path, dry_run=False)
		self.assertEqual(frappe.db.count("Station Competency"), total + 2)
		old = frappe.db.get_value("Station Competency", self.competency, ["is_active", "revoke_reason"])
		self.assertEqual(old, (0, "A-64"))
		self.assertTrue(
			frappe.db.exists(
				"Station Competency", {"employee": self.employee, "station": "TR-004", "is_active": 1}
			)
		)


class TestDeleteCatalog(IsolatedTestCase):
	def _station(self, **kwargs):
		return frappe.get_doc(
			{
				"doctype": "Zone Station",
				"zone_station_name": "Delete me",
				"is_zone": 0,
				"parent_zone": "ZONE-CLEAN",
				"functions": [{"station_function": "PACK"}],
				**kwargs,
			}
		).insert(ignore_permissions=True)

	def test_administrator_deletes_unused_station(self):
		frappe.set_user("Administrator")
		station = self._station()
		frappe.delete_doc("Zone Station", station.name)
		self.assertFalse(frappe.db.exists("Zone Station", station.name))
		self.assertEqual(frappe.db.get_value("Code Registry", station.name, "status"), "Disabled")
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_name": station.name, "action": "Delete"}))

	def test_administrator_cannot_delete_station_in_use(self):
		frappe.set_user("Administrator")
		station = self._station()
		frappe.get_doc(
			{
				"doctype": "Sterile Location",
				"location_name": "Linked",
				"zone_station": "ZONE-STERILE",
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Zone Station", "ZONE-STERILE")
		self.assertTrue(frappe.db.exists("Zone Station", station.name))

	def test_system_function_cannot_be_deleted_custom_unused_can(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Station Function", "PACK")
		custom = frappe.get_doc(
			{
				"doctype": "Station Function",
				"function_code": "TEST_DELETE",
				"function_name": "Delete",
				"process_order": 99,
			}
		).insert(ignore_permissions=True)
		frappe.delete_doc("Station Function", custom.name)
		self.assertFalse(frappe.db.exists("Station Function", custom.name))

	def test_zone_type_in_use_is_kept_unused_can_go(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Zone Type", "Clean")
		spare = frappe.get_doc({"doctype": "Zone Type", "type_name": "TEST Bỏ"}).insert(
			ignore_permissions=True
		)
		frappe.delete_doc("Zone Type", spare.name)
		self.assertFalse(frappe.db.exists("Zone Type", spare.name))
