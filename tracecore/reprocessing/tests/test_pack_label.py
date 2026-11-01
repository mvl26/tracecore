"""Nhãn gói `Tên bộ - Khoa (CY-…)` ở mọi nơi hiển thị gói (A-88, #1836 T5-05) và lời hướng dẫn không có mã luật (T5-04)."""

import re

import frappe

from tracecore.core import client_time, zones
from tracecore.reprocessing import issuing, sterilizing, storage, usage
from tracecore.tests.factories import (
	deactivate_printers,
	make_department,
	make_employee,
	make_equipment,
	make_load,
	make_load_ready_pack,
	make_released_pack,
	make_sterilize_program,
	make_stocked_pack,
)
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def _asset(*parts):
	with open(frappe.get_app_path("tracecore", *parts), encoding="utf-8") as handle:
		return handle.read()


class TestPackFields(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.department = make_department("Khoa nhãn gói")
		self.department_name = frappe.db.get_value("Department", self.department, "department_name")
		self.machine = make_equipment(
			"Hấp nhãn", "Steam Sterilizer", serial="SN-" + frappe.generate_hash(length=8)
		)
		self.program = make_sterilize_program(self.machine)

	def pack(self):
		return make_load_ready_pack(department=self.department)

	def test_admit_returns_department(self):
		row = sterilizing.admit_pack(self.pack().name, self.machine.name, self.program.name)
		self.assertEqual(row["department_name"], self.department_name)
		self.assertTrue(row["set_name"])

	def test_running_load_and_lookup_have_pack_rows(self):
		pack = self.pack()
		load = make_load(self.machine, self.program, [pack], status="Running")
		running = next(row for row in sterilizing.running_loads() if row["load"] == load.name)
		self.assertEqual(running["packs"], [pack.name])
		self.assertEqual(running["pack_rows"][0]["department_name"], self.department_name)
		self.assertEqual(running["pack_rows"][0]["cycle_id"], pack.name)
		described = sterilizing.lookup(load.name)
		self.assertEqual(described["packs"][0]["department_name"], self.department_name)

	def test_complete_returns_pack_rows(self):
		pack = self.pack()
		station = zones.stations_with_function("STERI_LOAD")[0]
		deactivate_printers(station)
		done = sterilizing.complete(
			self.machine.name,
			self.program.name,
			[pack.name],
			station,
			client_time.utc_now(),
			make_employee().name,
		)
		self.assertEqual(done["pack_rows"][0]["department_name"], self.department_name)

	def test_storage_card_and_dashboard_have_department(self):
		pack = make_released_pack(department=self.department)
		self.assertEqual(storage.pack_card(pack.name)["department_name"], self.department_name)
		stocked = make_stocked_pack(expiry_days=3)
		frappe.db.set_value("Pack", stocked.name, "department", self.department)
		rows = storage.overview()["expiring"]
		row = next(item for item in rows if item["cycle_id"] == stocked.name)
		self.assertEqual(row["department_name"], self.department_name)

	def test_usage_card_has_department(self):
		pack = make_released_pack(status="Issued", department=self.department)
		pack = frappe.get_doc("Pack", pack.name)
		self.assertEqual(usage._card(pack, None)["department_name"], self.department_name)

	def test_issue_note_rows_have_department(self):
		self.assertIn("department_name", _asset("reprocessing", "issuing.py").split('"packs": [', 1)[1][:400])
		self.assertTrue(issuing)


class TestPackLabelAssets(IsolatedTestCase):
	def test_shared_helper_is_defined_once_and_used_on_every_screen(self):
		station = _asset("ui", "page", "station", "station.js")
		self.assertIn("function tcPackLabel(", station)
		self.assertIn("function tcPackLabelHtml(", station)
		for name in ("station_t5.js", "station_t5b.js", "station_t6.js", "station_t7.js", "station_t8.js"):
			script = _asset("public", "js", name)
			self.assertTrue(re.search(r"tcPackLabel(Html)?\(", script), name)
			self.assertNotIn("function tcPackLabel", script, name)

	def test_helper_builds_name_department_code(self):
		station = _asset("ui", "page", "station", "station.js")
		body = station.split("function tcPackLabel(", 1)[1].split("\n}", 1)[0]
		self.assertIn("set_name", body)
		self.assertIn("department_name", body)
		self.assertIn("cycle_id", body)

	def test_t5_guidance_has_no_rule_code(self):
		for name in ("station_t5.js", "station_t2.js"):
			self.assertIsNone(re.search(r"BRU-[A-Z]+-\d+", _asset("public", "js", name)), name)
		self.assertIn(
			"Chỉ nhận gói đã đóng gói xong và đúng chương trình máy", _asset("translations", "vi.csv")
		)
