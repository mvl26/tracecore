"""Thời lượng chu trình thực tế so với chuẩn, máy rửa bận, người dỡ lô và truy vết giờ mẻ (A-73, ticket 31/10)."""

from datetime import datetime, timedelta

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from tracecore.core import client_time
from tracecore.reprocessing import cycle_time, sterilizing, trace, washing
from tracecore.reprocessing.tests import test_washing_result as base
from tracecore.tests.factories import (
	deactivate_printers,
	make_employee,
	make_load,
	make_load_ready_pack,
	make_sterilize_program,
	make_sterilizer,
	make_wash_machine,
	make_wash_ready_set,
)
from tracecore.tests.utils import bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

START = datetime(2026, 10, 31, 8, 0, 0)


class TestCycleTimeAssess(FrappeTestCase):
	def test_within_tolerance_is_normal(self):
		result = cycle_time.assess(START, START + timedelta(minutes=55), 52)
		self.assertEqual((result["actual_min"], result["standard_min"]), (55, 52))
		self.assertFalse(result["abnormal"])

	def test_much_shorter_or_longer_is_abnormal_with_direction(self):
		short = cycle_time.assess(START, START + timedelta(minutes=10), 52)
		long = cycle_time.assess(START, START + timedelta(minutes=90), 52)
		self.assertTrue(short["abnormal"])
		self.assertEqual(short["direction"], "short")
		self.assertTrue(long["abnormal"])
		self.assertEqual(long["direction"], "long")
		self.assertLess(short["deviation_pct"], 0)

	def test_boundary_is_not_abnormal(self):
		self.assertFalse(cycle_time.assess(START, START + timedelta(minutes=60), 50)["abnormal"])
		self.assertTrue(cycle_time.assess(START, START + timedelta(minutes=61), 50)["abnormal"])

	def test_missing_data_gives_none(self):
		self.assertIsNone(cycle_time.assess(START, None, 52))
		self.assertIsNone(cycle_time.assess(None, START, 52))
		self.assertIsNone(cycle_time.assess(START, START + timedelta(minutes=5), 0))
		self.assertIsNone(cycle_time.assess(START, START - timedelta(minutes=5), 52))


class TestWashCycleTime(base.WashResultCase):
	@bru("BRU-REP-015")
	def test_manual_data_reports_duration_against_program_standard(self):
		batch, _sets = self.load(1)
		ended = now_datetime()
		saved = self.save_data(batch, started_at=str(add_to_date(ended, minutes=-10)), ended_at=str(ended))
		self.assertTrue(saved["duration"]["abnormal"])
		self.assertEqual(saved["duration"]["standard_min"], 52)
		self.assertEqual(saved["duration"]["actual_min"], 10)
		saved = self.save_data(batch, started_at=str(add_to_date(ended, minutes=-50)), ended_at=str(ended))
		self.assertFalse(saved["duration"]["abnormal"])

	def test_lookup_shows_duration_after_data_is_saved(self):
		batch, _sets = self.load(1)
		self.assertIsNone(washing.lookup(batch)["duration"])
		self.save_data(batch)
		self.assertEqual(washing.lookup(batch)["duration"]["standard_min"], 52)

	@bru("BRU-REP-016")
	def test_machine_with_running_batch_is_busy(self):
		batch, _sets = self.load(1)
		block = washing.check_equipment_ready(self.machine.name)
		self.assertEqual(block.code, "EQUIPMENT_BUSY")
		self.assertIn(batch, block.reason)
		unit = make_wash_ready_set()
		code = base._code(
			washing.start,
			self.machine.name,
			self.program.name,
			[unit.name],
			[],
			base.STATION,
			client_time.utc_now(),
			self.employee.name,
		)
		self.assertEqual(code, "EQUIPMENT_BUSY")

	def test_machine_is_free_again_after_unload(self):
		batch, _sets = self.load(1)
		self.save_data(batch)
		self.close(batch)
		self.assertIsNone(washing.check_equipment_ready(self.machine.name))
		self.load(1)  # mẻ mới nạp được

	def test_other_machine_is_not_blocked(self):
		self.load(1)
		other = make_wash_machine(has_printout=1)
		self.assertIsNone(washing.check_equipment_ready(other.name))

	@bru("BRU-REP-016")
	def test_unload_records_who_unloaded_and_trace_shows_times(self):
		batch, sets = self.load(1)
		self.save_data(batch)
		unloader = make_employee()
		self.close(batch, unloaded_by=unloader.name)
		doc = frappe.get_doc("Wash Batch", batch)
		self.assertEqual(doc.unloaded_by, unloader.name)
		self.assertEqual(washing.lookup(batch)["unloaded_by"]["name"], unloader.name)
		detail = trace.cycle_detail("Wash Batch", batch)
		self.assertEqual(detail["operator"], self.employee.name)
		self.assertEqual(detail["unloaded_by"], unloader.name)
		self.assertEqual(detail["started_at"], doc.started_at)
		self.assertEqual(detail["ended_at"], doc.ended_at)
		self.assertEqual(detail["duration"]["standard_min"], 52)
		gate = next(e for e in trace.query(set_id=sets[0])["chains"][0]["events"] if e["step"] == "T2")
		self.assertEqual(gate["unloaded_by"], unloader.name)


class TestLoadCycleTime(FrappeTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers("TR-005")
		self.machine = make_sterilizer()
		self.program = make_sterilize_program(self.machine.name, requires_bi=1)

	@bru("BRU-REP-015")
	def test_lookup_and_trace_detail_show_duration_against_standard(self):
		load = make_load(self.machine, self.program, [make_load_ready_pack()])
		self.assertIsNone(sterilizing.lookup(load.name)["duration"])
		started = frappe.db.get_value("Sterilization Load", load.name, "started_at")
		frappe.db.set_value("Sterilization Load", load.name, "ended_at", add_to_date(started, minutes=2))
		standard = frappe.db.get_value("Process Program", self.program.name, "duration_min")
		described = sterilizing.lookup(load.name)["duration"]
		self.assertEqual((described["actual_min"], described["standard_min"]), (2, standard))
		detail = trace.cycle_detail("Sterilization Load", load.name)
		self.assertEqual(detail["duration"], described)
		self.assertIn("operator", detail)
