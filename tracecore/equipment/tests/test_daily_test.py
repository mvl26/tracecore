"""Test hằng ngày và khóa máy (FEAT-040; FR-M5-05 .1-.3, FR-M5-06 .1-.2; UC-23; BRU-EQP-001, BRU-EQP-002)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

from tracecore.core.errors import BlockedError
from tracecore.equipment import daily_test
from tracecore.reprocessing import sterilizing, washing
from tracecore.tests.factories import make_equipment, make_sterilizer, make_wash_machine
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-005"


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
		return daily_test.record(machine.name, test_type, result, STATION, **values)


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
	def test_washer_needs_cleaning_test_and_plasma_needs_none(self):
		washer = self.washer()
		self.assertEqual(daily_test.equipment_block(washer.name).items, ["washer_cleaning"])
		self.record(washer, "washer_cleaning")
		self.assertIsNone(daily_test.equipment_block(washer.name))
		plasma = make_sterilizer(equipment_type="Plasma Sterilizer", daily_tested=False)
		self.assertIsNone(daily_test.equipment_block(plasma.name))  # FR-M5-05.2: chỉ thị hóa học từng mẻ
		self.assertEqual(blocked(self, self.record, plasma, "bowie_dick").code, "TEST_INVALID")

	def test_test_type_lot_and_result_rules(self):
		machine = self.steam()
		self.assertEqual(blocked(self, self.record, machine, "washer_cleaning").code, "TEST_INVALID")
		self.assertEqual(blocked(self, self.record, machine, "leak", result="Maybe").code, "TEST_INVALID")
		self.assertEqual(blocked(self, self.record, machine, "leak", lot="").code, "TEST_INVALID")
		self.assertEqual(
			blocked(self, self.record, machine, "leak", lot_expiry=add_days(today(), -1)).code,
			"TEST_LOT_EXPIRED",
		)
		self.assertEqual(frappe.db.count("Daily Test", {"equipment": machine.name}), 0)

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
		self.assertEqual(washing.check_equipment_ready(washer.name).code, "DAILY_TEST_REQUIRED")
		self.record(steam, "bowie_dick")
		self.record(steam, "leak")
		self.record(washer, "washer_cleaning")
		self.assertIsNone(sterilizing.check_equipment_ready(steam.name))
		self.assertIsNone(washing.check_equipment_ready(washer.name))

	def test_factory_default_records_the_required_tests(self):
		machine = make_equipment(equipment_type="Steam Sterilizer", serial="SN-F1")
		self.assertIsNone(daily_test.equipment_block(machine.name))
		self.assertEqual(
			sorted(frappe.get_all("Daily Test", filters={"equipment": machine.name}, pluck="test_type")),
			["bowie_dick", "leak"],
		)


class TestLoadIndicator(IsolatedTestCase):
	"""Hook `tracecore_load_daily_indicator` (A-23): T5b lấy Bowie-Dick từ test hằng ngày của máy trong ngày chạy mẻ."""

	def test_returns_latest_bowie_dick_of_the_day_and_nothing_for_other_indicators(self):
		machine = make_sterilizer().name  # factory ghi sẵn test hằng ngày Đạt của hôm nay
		row = daily_test.load_indicator(machine, "bowie_dick", today())
		self.assertEqual((row["result"], row["test_date"]), ("Pass", today()))
		self.assertTrue(row["daily_test"])
		self.assertIsNone(daily_test.load_indicator(machine, "chemical_class_5", today()))
		self.assertIsNone(daily_test.load_indicator(machine, "bowie_dick", add_days(today(), -1)))
