"""Khung khu-trạm mặc định (ZONE-DIRTY/CLEAN/STERILE, TR-001..007): tạo nếu chưa có, không bao giờ ghi đè.

Trước đây khung này là fixtures; `bench migrate` (``sync_fixtures``) nhập lại fixtures với force nên xóa rồi chèn lại
bản ghi: trạm R10 đã tắt bật lại, thiết bị ngoại vi mất (FEAT-002 final review F1).
"""

import os
from unittest.mock import patch

import frappe
from frappe.core.doctype.data_import.data_import import import_doc
from frappe.utils.fixtures import sync_fixtures

from tracecore import hooks
from tracecore.core import zones
from tracecore.patches.v0_1 import seed_zone_stations
from tracecore.setup import install
from tracecore.setup.seed import DEFAULT_STATIONS, DEFAULT_ZONES, ensure_zone_stations
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["User"]


def _import_zone_station_files_only(path):
	"""Nhập lại (force) như migrate, nhưng chỉ file fixtures có Zone Station.

	Fixtures Custom Field của Item gọi ALTER TABLE (commit ngầm) nên không chạy được trong savepoint của test.
	"""
	with open(path, encoding="utf-8") as handle:
		docs = frappe.parse_json(handle.read())
	if any(doc.get("doctype") == "Zone Station" for doc in docs):
		import_doc(path)


def _edit_tr004():
	station = frappe.get_doc("Zone Station", "TR-004")
	station.zone_station_name = "T4 Packing (R10 edited)"
	station.is_active = 0
	station.append(
		"peripherals",
		{"peripheral_type": "Scanner", "connection": "USB HID", "model": "Seed test", "is_active": 1},
	)
	station.save()


def _assert_tr004_edit_kept(test):
	station = frappe.get_doc("Zone Station", "TR-004")
	test.assertEqual(station.zone_station_name, "T4 Packing (R10 edited)")
	test.assertEqual(station.is_active, 0)
	test.assertEqual([row.model for row in station.peripherals], ["Seed test"])


class TestZoneStationSeed(IsolatedTestCase):
	def test_zone_station_is_not_a_fixture(self):
		self.assertNotIn("Zone Station", [entry["dt"] for entry in hooks.fixtures])
		self.assertFalse(os.path.exists(frappe.get_app_path("tracecore", "fixtures", "zone_station.json")))

	def test_fixture_sync_keeps_r10_edits(self):
		"""`bench migrate` chạy sync_fixtures: sửa của R10 trên TR-004 (tắt, thêm thiết bị) phải còn nguyên."""
		_edit_tr004()
		with (
			patch.object(frappe.db, "commit"),
			patch(  # import_doc commit sau mỗi file: giữ trong savepoint
				"frappe.utils.fixtures.import_doc", side_effect=_import_zone_station_files_only
			),
		):
			sync_fixtures("tracecore")
		_assert_tr004_edit_kept(self)

	def test_seed_and_patch_keep_r10_edits(self):
		_edit_tr004()
		self.assertEqual(ensure_zone_stations(), [])
		seed_zone_stations.execute()
		_assert_tr004_edit_kept(self)

	def test_seed_creates_missing_records(self):
		"""Site mới (hoặc thiếu bản ghi): tạo khu trước, trạm sau, đúng tên/khu/bước, đang hoạt động."""
		names = ("in", ["ZONE-STERILE", "TR-006", "TR-007"])
		frappe.db.delete("Zone Station", {"name": names})
		frappe.db.delete("Zone Station Function", {"parent": names})
		created = ensure_zone_stations()
		self.assertEqual(created, ["ZONE-STERILE", "TR-006", "TR-007"])
		self.assertEqual(ensure_zone_stations(), [])
		for zone in DEFAULT_ZONES:
			doc = frappe.get_doc("Zone Station", zone["name"])
			self.assertEqual((doc.is_zone, doc.is_active, doc.zone_type), (1, 1, zone["zone_type"]))
		for station in DEFAULT_STATIONS:
			doc = frappe.get_doc("Zone Station", station["name"])
			self.assertEqual(
				(
					doc.is_zone,
					doc.is_active,
					doc.parent_zone,
					[row.station_function for row in doc.functions],
				),
				(0, 1, station["parent_zone"], list(station["functions"])),
			)
		self.assertEqual(frappe.db.get_value("Zone Station", "TR-007", "zone_type"), "Sterile")
		# FEAT-027: trạm T8 quét sử dụng nằm ở khu Department mặc định
		self.assertEqual(
			frappe.db.get_value("Zone Station", "TR-008", ["zone_type", "station_no"]), ("Department", 8)
		)
		self.assertEqual(zones.station_functions("TR-008"), ["USE"])
		self.assertEqual(frappe.db.get_value("Code Registry", "TR-007", "prefix"), "TR")

	def test_after_install_seeds_zone_stations(self):
		with (
			patch.object(install, "ensure_zone_stations") as seed,
			patch.object(install, "ensure_sample_templates"),
			patch.object(install, "apply_system_settings"),
		):
			install.after_install()
		seed.assert_called_once_with()

	def test_patch_registered_post_model_sync(self):
		with open(frappe.get_app_path("tracecore", "patches.txt"), encoding="utf-8") as handle:
			text = handle.read()
		post = text.split("[post_model_sync]", 1)[1]
		self.assertIn("tracecore.patches.v0_1.seed_zone_stations", post)
