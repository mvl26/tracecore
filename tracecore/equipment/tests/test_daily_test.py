"""Test hằng ngày và khóa máy (FEAT-040; FR-M5-05 .1-.3, FR-M5-06 .1-.2; UC-23; BRU-EQP-001, BRU-EQP-002)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

from tracecore.core.errors import BlockedError
from tracecore.equipment import daily_test, pick
from tracecore.reprocessing import sterilizing, washing
from tracecore.tests.factories import (
	make_equipment,
	make_load,
	make_load_ready_pack,
	make_sterilize_program,
	make_sterilizer,
	make_wash_machine,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-005"
SETTINGS = "TraceCore Settings"


def blocked(case, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


class DailyTestCase(IsolatedTestCase):
	def steam(self, **kwargs):
		return make_sterilizer(daily_tested=False, **kwargs)

	def washer(self, **kwargs):
		return make_wash_machine(daily_tested=False, **kwargs)

	def record(self, machine, test_type, result="Pass", **extra):
		values = {"lot": "TEST-LOT-1", "lot_expiry": add_days(today(), 30), "photo": "/files/t.png", **extra}
		if test_type in daily_test.RUN_TESTS:
			self.run_test(machine, test_type)
		return daily_test.record(machine.name, test_type, result, STATION, **values)

	def run_test(self, machine, test_type):
		daily_test.start_run(machine.name, test_type, STATION)
		daily_test.end_run(machine.name, test_type)


class TestRun(DailyTestCase):
	"""#1823 (A-84): lần chạy test có bắt đầu, kết thúc; kết quả chỉ ghi sau khi kết thúc."""

	def values(self):
		return {"lot": "L1", "lot_expiry": add_days(today(), 30), "photo": "/files/t.png"}

	def overview_row(self, machine):
		return next(row for row in daily_test.overview() if row["name"] == machine.name)

	def test_result_cannot_be_recorded_before_the_run_ends(self):
		machine = self.steam()
		block = blocked(self, daily_test.record, machine.name, "bowie_dick", "Pass", STATION, **self.values())
		self.assertEqual(block.code, "DAILY_TEST_RUN_NOT_ENDED")
		daily_test.start_run(machine.name, "bowie_dick", STATION)
		block = blocked(self, daily_test.record, machine.name, "bowie_dick", "Pass", STATION, **self.values())
		self.assertEqual((block.code, block.http_status), ("DAILY_TEST_RUN_NOT_ENDED", 409))
		daily_test.end_run(machine.name, "bowie_dick")
		done = daily_test.record(
			machine.name, "bowie_dick", "Pass", STATION, employee=None, note=" đọc ", **self.values()
		)
		row = frappe.get_doc("Daily Test", done["daily_test"])
		self.assertEqual((row.run_status, row.result, row.note), ("Recorded", "Pass", "đọc"))
		self.assertTrue(row.started_at and row.ended_at and row.tested_at and row.photo)
		self.assertEqual(frappe.db.count("Daily Test", {"equipment": machine.name}), 1)

	def test_machine_shows_testing_and_cannot_be_loaded_during_the_run(self):
		machine = self.steam()
		daily_test.start_run(machine.name, "bowie_dick", STATION)
		row = self.overview_row(machine)
		self.assertEqual((row["testing"], row["ready_to_load"]), ("bowie_dick", 0))
		self.assertEqual(row["runs"], {"bowie_dick": "Running"})
		self.assertEqual(sterilizing.check_equipment_ready(machine.name).code, "EQUIPMENT_TESTING")
		frappe.db.set_value("Equipment", machine.name, "unlock_until", add_to_date(now_datetime(), hours=2))
		self.assertEqual(sterilizing.check_equipment_ready(machine.name).code, "EQUIPMENT_TESTING")
		daily_test.end_run(machine.name, "bowie_dick")
		row = self.overview_row(machine)
		self.assertIsNone(row["testing"])
		self.assertEqual(row["runs"], {"bowie_dick": "Ended"})

	def test_a_new_run_hides_an_earlier_pass_until_it_is_read(self):
		machine = self.steam()
		self.record(machine, "bowie_dick")
		self.assertTrue(daily_test.passed_today(machine.name, "bowie_dick"))
		self.run_test(machine, "bowie_dick")
		self.assertFalse(daily_test.passed_today(machine.name, "bowie_dick"))

	def test_recorded_row_cannot_be_changed_and_abandoned_run_can_be_repeated(self):
		machine = self.steam()
		self.run_test(machine, "leak")
		done = self.record(machine, "leak")
		row = frappe.get_doc("Daily Test", done["daily_test"])
		row.flags.tc_daily_test = True
		row.note = "sửa"
		self.assertRaises(frappe.ValidationError, row.save)
		self.assertEqual(frappe.db.count("Daily Test", {"equipment": machine.name, "test_type": "leak"}), 2)

	def test_only_one_run_at_a_time_and_not_while_a_load_is_unloaded(self):
		machine = self.steam()
		daily_test.start_run(machine.name, "bowie_dick", STATION)
		self.assertEqual(
			blocked(self, daily_test.start_run, machine.name, "leak", STATION).code, "DAILY_TEST_RUN_OPEN"
		)
		daily_test.end_run(machine.name, "bowie_dick")
		pack = make_load_ready_pack()
		make_load(machine, make_sterilize_program(machine.name), [pack])
		self.assertEqual(
			blocked(self, daily_test.start_run, machine.name, "leak", STATION).code, "EQUIPMENT_BUSY"
		)

	def test_end_without_a_run_and_wrong_type_are_refused(self):
		machine = self.steam()
		self.assertEqual(
			blocked(self, daily_test.end_run, machine.name, "leak").code, "DAILY_TEST_RUN_NOT_ENDED"
		)
		self.assertEqual(
			blocked(self, daily_test.start_run, machine.name, "plasma_daily", STATION).code, "TEST_INVALID"
		)
		washer = self.washer()
		self.assertEqual(
			blocked(self, daily_test.start_run, washer.name, "washer_cleaning", STATION).code, "TEST_INVALID"
		)

	def test_failed_read_locks_the_machine(self):
		machine = self.steam()
		self.assertTrue(self.record(machine, "bowie_dick", result="Fail")["locked"])
		self.assertEqual(sterilizing.check_equipment_ready(machine.name).code, "EQUIPMENT_NOT_READY")

	def test_load_indicator_skips_a_run_without_a_result(self):
		machine = self.steam()
		self.record(machine, "bowie_dick")
		self.run_test(machine, "bowie_dick")
		self.assertEqual(daily_test.load_indicator(machine.name, "bowie_dick")["result"], "Pass")

	def test_machine_shows_the_running_load_on_every_status_until_unloaded(self):
		machine = self.steam()
		self.record(machine, "bowie_dick")
		self.record(machine, "leak")
		self.assertEqual(self.overview_row(machine)["ready_to_load"], 1)
		load = make_load(machine, make_sterilize_program(machine.name), [make_load_ready_pack()])
		row = self.overview_row(machine)
		self.assertEqual(
			(row["running_load"], row["running_status"], row["ready_to_load"]), (load.name, "Running", 0)
		)
		frappe.db.set_value("Sterilization Load", load.name, "status", "Cycle Complete")
		self.assertEqual(self.overview_row(machine)["running_status"], "Cycle Complete")
		frappe.db.set_value("Sterilization Load", load.name, "unload_scan_at", now_datetime())
		self.assertIsNone(self.overview_row(machine)["running_load"])


class TestPickTypes(DailyTestCase):
	"""#1806: gợi ý chọn tay cho test hằng ngày dùng loại máy có test (`TESTS`), và theo đúng loại máy của bước."""

	def test_daily_test_purpose_lists_the_machine_types_of_the_step(self):
		self.assertEqual(
			set(pick.types_for("T5", pick.PURPOSE_DAILY_TEST)), {"Steam Sterilizer", "Plasma Sterilizer"}
		)
		self.assertEqual(
			set(pick.types_for("T2", pick.PURPOSE_DAILY_TEST)), {"Washer-Disinfector", "Ultrasonic Cleaner"}
		)

	def test_daily_test_purpose_without_a_step_lists_every_machine_type_with_a_test(self):
		self.assertEqual(set(pick.types_for(None, pick.PURPOSE_DAILY_TEST)), set(daily_test.TESTS))

	def test_other_purposes_keep_the_types_of_the_step(self):
		self.assertEqual(pick.types_for("T4"), ("Sealer",))
		self.assertEqual(pick.types_for("T4", pick.PURPOSE_DAILY_TEST), ())


class TestRecord(DailyTestCase):
	@bru("BRU-EQP-001")
	def test_steam_needs_bowie_dick_and_leak_today(self):
		machine = self.steam()
		block = daily_test.equipment_block(machine.name)
		self.assertEqual(block.code, "DAILY_TEST_REQUIRED")
		self.assertCountEqual(block.items, ["bowie_dick", "leak"])
		self.record(machine, "bowie_dick")
		self.assertEqual(daily_test.equipment_block(machine.name).items, ["leak"])
		self.record(machine, "leak")
		self.assertIsNone(daily_test.equipment_block(machine.name))

	@bru("BRU-EQP-001")
	def test_plasma_needs_its_own_test_and_never_bowie_dick(self):
		plasma = make_sterilizer(equipment_type="Plasma Sterilizer", daily_tested=False)
		self.assertEqual(daily_test.equipment_block(plasma.name).items, ["plasma_daily"])
		self.assertEqual(blocked(self, self.record, plasma, "bowie_dick").code, "TEST_INVALID")
		self.record(plasma, "plasma_daily")
		self.assertIsNone(daily_test.equipment_block(plasma.name))

	def test_test_type_lot_and_result_rules(self):
		machine = self.steam()
		self.assertEqual(blocked(self, self.record, machine, "washer_cleaning").code, "TEST_INVALID")
		self.assertEqual(blocked(self, self.record, machine, "leak", result="Maybe").code, "TEST_INVALID")
		self.assertEqual(blocked(self, self.record, machine, "leak", lot="").code, "TEST_INVALID")
		self.assertEqual(
			blocked(self, self.record, machine, "leak", lot_expiry=add_days(today(), -1)).code,
			"TEST_LOT_EXPIRED",
		)
		# chỉ còn dòng lần chạy đã kết thúc, chưa có kết quả nào được ghi
		self.assertEqual(
			frappe.db.count("Daily Test", {"equipment": machine.name, "run_status": "Recorded"}), 0
		)

	def test_missing_bowie_dick_photo_is_a_warning_not_a_block(self):
		machine = self.steam()
		done = self.record(machine, "bowie_dick", photo=None)
		self.assertEqual(done["warnings"], ["photo_missing"])
		self.assertEqual(self.record(machine, "leak", photo=None)["warnings"], [])

	def test_yesterdays_test_does_not_count(self):
		machine = self.steam()
		self.record(machine, "bowie_dick")
		self.record(machine, "leak")
		frappe.db.set_value("Daily Test", {"equipment": machine.name}, "test_date", add_days(today(), -1))
		self.assertCountEqual(daily_test.equipment_block(machine.name).items, ["bowie_dick", "leak"])

	@bru("BRU-EQP-001")
	def test_failed_test_locks_the_machine_and_a_pass_of_all_unlocks_it(self):
		machine = self.steam()
		self.record(machine, "leak")
		done = self.record(machine, "bowie_dick", result="Fail")
		self.assertTrue(done["locked"])
		state = frappe.db.get_value("Equipment", machine.name, ["status", "lock_reason"], as_dict=True)
		self.assertEqual((state.status, state.lock_reason), ("Locked", "Daily Test"))
		self.assertEqual(frappe.db.get_value("Daily Test", done["daily_test"], "nc_pending"), 1)
		self.assertEqual(sterilizing.check_equipment_ready(machine.name).code, "EQUIPMENT_NOT_READY")
		self.record(machine, "bowie_dick", result="Pass")
		state = frappe.db.get_value("Equipment", machine.name, ["status", "lock_reason"], as_dict=True)
		self.assertEqual((state.status, state.lock_reason), ("Ready", None))


class TestInspectionAndUnlock(DailyTestCase):
	@bru("BRU-EQP-002")
	def test_overdue_inspection_blocks_before_daily_test(self):
		washer = self.washer(inspection_due=add_days(today(), -1))
		self.record(washer, "washer_cleaning")
		self.assertEqual(daily_test.equipment_block(washer.name).code, "EQUIPMENT_INSPECTION_EXPIRED")

	@bru("BRU-EQP-002")
	def test_temporary_unlock_bypasses_tests_until_it_expires(self):
		machine = self.steam()
		result = daily_test.unlock_temp(machine.name, "Ca khẩn", 2, STATION)
		self.assertEqual(frappe.db.get_value("Equipment", machine.name, "status"), "Ready")
		self.assertIsNone(daily_test.equipment_block(machine.name))
		self.assertTrue(result["unlock_until"] > now_datetime())
		with patch(
			"tracecore.equipment.daily_test.now_datetime", return_value=add_to_date(now_datetime(), hours=3)
		):
			self.assertEqual(daily_test.equipment_block(machine.name).code, "DAILY_TEST_REQUIRED")
		audit = frappe.get_all(
			"Audit Log", filters={"ref_name": machine.name, "action": "Override"}, pluck="reason"
		)
		self.assertIn("TempUnlock", audit)

	def test_unlock_rules(self):
		machine = self.steam()
		for hours in (0, 25, "x", None):
			with self.subTest(hours=hours):
				self.assertEqual(
					blocked(self, daily_test.unlock_temp, machine.name, "ok", hours).code, "UNLOCK_INVALID"
				)
		self.assertEqual(blocked(self, daily_test.unlock_temp, machine.name, " ", 2).code, "UNLOCK_INVALID")
		repair = self.steam(serial="SN-REPAIR")
		frappe.db.set_value("Equipment", repair.name, "status", "Repair")
		self.assertEqual(
			blocked(self, daily_test.unlock_temp, repair.name, "ok", 2).code, "UNLOCK_NOT_ALLOWED"
		)

	@bru("BRU-EQP-002")
	def test_pressure_equipment_with_overdue_inspection_is_never_unlocked(self):
		machine = self.steam(inspection_due=add_days(today(), -1))
		self.assertEqual(
			blocked(self, daily_test.unlock_temp, machine.name, "ok", 2).code, "UNLOCK_NOT_ALLOWED"
		)
		washer = self.washer(inspection_due=add_days(today(), -1))
		daily_test.unlock_temp(washer.name, "ok", 2, STATION)  # không phải thiết bị áp lực: R02 mở được
		self.assertIsNone(daily_test.equipment_block(washer.name))


class TestCalibration(DailyTestCase):
	"""Hạn hiệu chuẩn (FEAT-039, A-43 M4, M5): quá hạn chặn tạo mẻ/lô, R02 mở khóa tạm được kể cả máy áp lực."""

	@bru("BRU-EQP-002")
	def test_overdue_calibration_blocks_the_machine(self):
		washer = self.washer(calibration_due=add_days(today(), -1))
		self.record(washer, "washer_cleaning")
		block = daily_test.equipment_block(washer.name)
		self.assertEqual(block.code, "EQUIPMENT_CALIBRATION_EXPIRED")
		self.assertEqual(washing.check_equipment_ready(washer.name).code, "EQUIPMENT_CALIBRATION_EXPIRED")

	def test_calibration_due_today_or_later_does_not_block(self):
		for due in (today(), add_days(today(), 30)):
			with self.subTest(due=due):
				washer = self.washer(calibration_due=due, serial=f"SN-CAL-{due}")
				self.record(washer, "washer_cleaning")
				self.assertIsNone(daily_test.equipment_block(washer.name))

	@bru("BRU-EQP-002")
	def test_r02_can_unlock_overdue_calibration_even_for_pressure_equipment(self):
		machine = self.steam(calibration_due=add_days(today(), -1))
		self.assertEqual(daily_test.equipment_block(machine.name).code, "EQUIPMENT_CALIBRATION_EXPIRED")
		daily_test.unlock_temp(machine.name, "Chờ hiệu chuẩn", 2, STATION)
		self.assertIsNone(daily_test.equipment_block(machine.name))

	@bru("BRU-EQP-002")
	def test_overdue_inspection_of_pressure_equipment_still_cannot_be_unlocked(self):
		machine = self.steam(inspection_due=add_days(today(), -1), calibration_due=add_days(today(), -1))
		self.assertEqual(
			blocked(self, daily_test.unlock_temp, machine.name, "ok", 2).code, "UNLOCK_NOT_ALLOWED"
		)
		self.assertEqual(daily_test.equipment_block(machine.name).code, "EQUIPMENT_INSPECTION_EXPIRED")

	def test_overview_reports_overdue_calibration(self):
		washer = self.washer(calibration_due=add_days(today(), -1))
		self.record(washer, "washer_cleaning")
		row = next(item for item in daily_test.overview() if item["name"] == washer.name)
		self.assertTrue(row["calibration_expired"])
		self.assertEqual(row["ready_to_load"], 0)

	def test_due_dates_and_expired_lock_reasons_exist_on_equipment(self):
		machine = self.steam(maintenance_due=add_days(today(), 30))
		self.assertEqual(
			str(frappe.db.get_value("Equipment", machine.name, "maintenance_due")),
			str(add_days(today(), 30)),
		)
		for reason in ("Inspection Expired", "Calibration Expired"):
			daily_test._apply(machine.name, status="Locked", lock_reason=reason)
			self.assertEqual(frappe.db.get_value("Equipment", machine.name, "lock_reason"), reason)


class TestIntegration(DailyTestCase):
	@bru("BRU-EQP-001")
	def test_load_and_wash_readiness_use_the_daily_test(self):
		steam, washer = self.steam(), self.washer()
		self.assertEqual(sterilizing.check_equipment_ready(steam.name).code, "DAILY_TEST_REQUIRED")
		self.assertIsNone(washing.check_equipment_ready(washer.name))  # máy rửa không có test bắt buộc (A-70)
		self.record(steam, "bowie_dick")
		self.record(steam, "leak")
		self.assertIsNone(sterilizing.check_equipment_ready(steam.name))

	def test_factory_default_records_the_required_tests(self):
		machine = make_equipment(equipment_type="Steam Sterilizer", serial="SN-F1")
		self.assertIsNone(daily_test.equipment_block(machine.name))
		self.assertEqual(
			sorted(frappe.get_all("Daily Test", filters={"equipment": machine.name}, pluck="test_type")),
			["bowie_dick", "leak"],
		)


class TestModes(DailyTestCase):
	"""Diện bắt buộc cấu hình theo từng viện trong TraceCore Settings (A-70)."""

	def setting(self, mode=None, leak=1, plasma=1):
		frappe.db.set_single_value(SETTINGS, "daily_test_mode", mode or daily_test.MODE_ALL)
		frappe.db.set_single_value(SETTINGS, "daily_test_steam_leak", leak)
		frappe.db.set_single_value(SETTINGS, "daily_test_plasma", plasma)

	def plasma(self, **kwargs):
		return make_sterilizer(equipment_type="Plasma Sterilizer", daily_tested=False, **kwargs)

	def others(self):
		options = frappe.get_meta("Equipment").get_field("equipment_type").options.split("\n")
		types = [kind for kind in options if kind and kind not in ("Steam Sterilizer", "Plasma Sterilizer")]
		self.assertIn("Washer-Disinfector", types)
		extra = {"Laundry Washer": {"capacity_kg": 10}, "Dryer": {"capacity_kg": 10}}
		return [self.washer(equipment_type=kind, **extra.get(kind, {})) for kind in types]

	@bru("BRU-EQP-001")
	def test_machines_other_than_sterilizers_are_never_required_in_any_mode(self):
		machines = self.others()
		for mode in daily_test.MODES:
			self.setting(mode)
			for machine in machines:
				with self.subTest(mode=mode, machine=machine.equipment_type):
					self.assertIsNone(daily_test.equipment_block(machine.name))

	@bru("BRU-EQP-001")
	def test_not_required_mode_blocks_nothing(self):
		self.setting(daily_test.MODE_NONE)
		for machine in (self.steam(), self.plasma(), self.steam(daily_test_required=1)):
			self.assertIsNone(sterilizing.check_equipment_ready(machine.name))

	@bru("BRU-EQP-001")
	def test_all_mode_blocks_steam_and_plasma_until_a_pass(self):
		self.setting(daily_test.MODE_ALL)
		steam, plasma = self.steam(), self.plasma()
		self.assertEqual(sterilizing.check_equipment_ready(steam.name).code, "DAILY_TEST_REQUIRED")
		self.assertEqual(sterilizing.check_equipment_ready(plasma.name).code, "DAILY_TEST_REQUIRED")
		self.record(steam, "bowie_dick")
		self.record(steam, "leak")
		self.record(plasma, "plasma_daily")
		self.assertIsNone(sterilizing.check_equipment_ready(steam.name))
		self.assertIsNone(sterilizing.check_equipment_ready(plasma.name))

	@bru("BRU-EQP-001")
	def test_selected_mode_blocks_only_ticked_machines(self):
		self.setting(daily_test.MODE_SELECTED)
		ticked, plain = self.steam(daily_test_required=1), self.steam()
		ticked_plasma, plain_plasma = self.plasma(daily_test_required=1), self.plasma()
		self.assertEqual(daily_test.equipment_block(ticked.name).code, "DAILY_TEST_REQUIRED")
		self.assertEqual(daily_test.equipment_block(ticked_plasma.name).code, "DAILY_TEST_REQUIRED")
		self.assertIsNone(daily_test.equipment_block(plain.name))
		self.assertIsNone(daily_test.equipment_block(plain_plasma.name))

	def test_tick_has_no_effect_in_other_modes_and_is_cleared_on_other_types(self):
		self.setting(daily_test.MODE_ALL)
		self.assertEqual(daily_test.equipment_block(self.steam().name).code, "DAILY_TEST_REQUIRED")
		washer = self.washer(daily_test_required=1)
		self.assertEqual(frappe.db.get_value("Equipment", washer.name, "daily_test_required"), 0)
		self.setting(daily_test.MODE_SELECTED)
		self.assertIsNone(daily_test.equipment_block(washer.name))

	def test_tick_is_only_shown_for_sterilizers(self):
		field = frappe.get_meta("Equipment").get_field("daily_test_required")
		self.assertIn("Steam Sterilizer", field.depends_on)
		self.assertIn("Plasma Sterilizer", field.depends_on)

	@bru("BRU-EQP-001")
	def test_leak_and_plasma_tests_follow_the_settings(self):
		self.setting(daily_test.MODE_ALL, leak=0, plasma=0)
		steam, plasma = self.steam(), self.plasma()
		self.assertEqual(daily_test.equipment_block(steam.name).items, ["bowie_dick"])
		self.assertIsNone(daily_test.equipment_block(plasma.name))

	@bru("BRU-EQP-001")
	def test_changing_the_mode_takes_effect_at_once(self):
		machine = self.steam()
		self.setting(daily_test.MODE_ALL)
		self.assertIsNotNone(daily_test.equipment_block(machine.name))
		self.setting(daily_test.MODE_NONE)
		self.assertIsNone(daily_test.equipment_block(machine.name))
		self.setting(daily_test.MODE_ALL)
		self.assertIsNotNone(daily_test.equipment_block(machine.name))

	def test_voluntary_test_does_not_lock_or_warn(self):
		washer = self.washer()
		done = self.record(washer, "washer_cleaning", result="Fail", photo=None)
		self.assertFalse(done["locked"])
		self.assertEqual(frappe.db.get_value("Equipment", washer.name, "status"), "Ready")
		self.assertEqual(frappe.db.get_value("Daily Test", done["daily_test"], "nc_pending"), 0)
		self.setting(daily_test.MODE_NONE)
		steam = self.steam()
		done = self.record(steam, "bowie_dick", result="Fail", photo=None)
		self.assertFalse(done["locked"])
		self.assertEqual(done["warnings"], [])
		self.assertEqual(frappe.db.get_value("Equipment", steam.name, "status"), "Ready")

	@bru("BRU-EQP-001")
	def test_failed_required_plasma_test_locks_the_machine(self):
		plasma = self.plasma()
		self.assertTrue(self.record(plasma, "plasma_daily", result="Fail")["locked"])
		self.assertEqual(frappe.db.get_value("Equipment", plasma.name, "lock_reason"), "Daily Test")

	def locked(self, machine):
		daily_test._apply(machine.name, status="Locked", lock_reason=daily_test.LOCK_DAILY_TEST)

	def state(self, machine):
		return tuple(frappe.db.get_value("Equipment", machine.name, ["status", "lock_reason"]))

	@bru("BRU-EQP-001")
	def test_saving_settings_releases_locks_that_are_no_longer_required(self):
		steam = self.steam()
		self.locked(steam)
		self.setting(daily_test.MODE_ALL)
		settings = frappe.get_single(SETTINGS)
		settings.save(ignore_permissions=True)
		self.assertEqual(self.state(steam), ("Locked", "Daily Test"))
		settings.daily_test_mode = daily_test.MODE_NONE
		settings.save(ignore_permissions=True)
		self.assertEqual(self.state(steam), ("Ready", None))

	def test_unticking_a_machine_releases_its_lock(self):
		self.setting(daily_test.MODE_SELECTED)
		machine = self.steam(daily_test_required=1)
		self.locked(machine)
		doc = frappe.get_doc("Equipment", machine.name)
		doc.daily_test_required = 0
		doc.save(ignore_permissions=True)
		self.assertEqual(self.state(machine), ("Ready", None))

	@bru("BRU-EQP-001")
	def test_patch_opens_machines_out_of_scope_and_keeps_the_rest(self):
		from tracecore.patches.v0_1 import daily_test_config

		self.setting(daily_test.MODE_ALL)
		washer, steam, plasma = self.washer(), self.steam(), self.plasma()
		other_lock = self.washer()
		for machine in (washer, steam, plasma):
			self.locked(machine)
		daily_test._apply(other_lock.name, status="Locked", lock_reason="Inspection Expired")
		daily_test_config.execute()
		self.assertEqual(self.state(washer), ("Ready", None))
		self.assertEqual(self.state(steam), ("Locked", "Daily Test"))
		self.assertEqual(self.state(plasma), ("Locked", "Daily Test"))
		self.assertEqual(self.state(other_lock), ("Locked", "Inspection Expired"))

	def test_defaults_are_written_once_and_never_overwrite_a_choice(self):
		frappe.db.delete("Singles", {"doctype": SETTINGS, "field": ["like", "daily_test_%"]})
		daily_test.ensure_settings()
		self.assertEqual(daily_test.mode(), daily_test.MODE_ALL)
		self.assertIn("leak", daily_test.required_tests("Steam Sterilizer"))
		self.setting(daily_test.MODE_NONE, leak=0)
		daily_test.ensure_settings()
		self.assertEqual(daily_test.mode(), daily_test.MODE_NONE)
		self.setting(daily_test.MODE_ALL, leak=0)
		daily_test.ensure_settings()
		self.assertNotIn("leak", daily_test.required_tests("Steam Sterilizer"))

	def test_overview_offers_voluntary_tests_without_requiring_them(self):
		washer, plasma = self.washer(), self.plasma()
		rows = {row["name"]: row for row in daily_test.overview()}
		self.assertEqual(rows[washer.name]["required"], [])
		self.assertEqual(rows[washer.name]["optional"], ["washer_cleaning"])
		self.assertEqual(rows[washer.name]["ready_to_load"], 1)
		self.assertEqual(rows[plasma.name]["required"], ["plasma_daily"])
		self.assertEqual(rows[plasma.name]["ready_to_load"], 0)


class TestLoadIndicator(IsolatedTestCase):
	"""Hook `tracecore_load_daily_indicator` (A-23): T5b lấy Bowie-Dick từ test hằng ngày của máy trong ngày chạy mẻ."""

	def test_returns_latest_bowie_dick_of_the_day_and_nothing_for_other_indicators(self):
		machine = make_sterilizer().name  # factory ghi sẵn test hằng ngày Đạt của hôm nay
		row = daily_test.load_indicator(machine, "bowie_dick", today())
		self.assertEqual((row["result"], row["test_date"]), ("Pass", today()))
		self.assertTrue(row["daily_test"])
		self.assertIsNone(daily_test.load_indicator(machine, "chemical_class_5", today()))
		self.assertIsNone(daily_test.load_indicator(machine, "bowie_dick", add_days(today(), -1)))
