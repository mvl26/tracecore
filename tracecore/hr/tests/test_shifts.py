"""Phân ca theo khu và báo cáo (FEAT-037, FR-M4-04, UC-20): chặn xếp ca thiếu năng lực, lịch tuần, sản lượng theo ca."""

from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

from tracecore.hr import competency
from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.tracecore.report.shift_schedule import shift_schedule
from tracecore.tracecore.report.station_output import station_output
from tracecore.v1.tests.station_fixtures import make_station_employee

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
STATION = "TR-004"  # T4, khu Sạch


def shift_type(start="00:00:00", end="23:30:00"):
	name = "TC Ca " + frappe.generate_hash(length=5)
	frappe.get_doc(
		{
			"doctype": "Shift Type",
			"name": name,
			"start_time": start,
			"end_time": end,
			# HRMS cộng thêm biên check-in/out vào độ dài ca; về 0 để ca cả ngày không bị coi là tự chồng lấn
			"begin_check_in_before_shift_start_time": 0,
			"allow_check_out_after_shift_end_time": 0,
		}
	).insert(ignore_permissions=True)
	return name


def shift_around(now):
	"""Giờ bắt đầu/kết thúc của ca bao thời điểm `now` trong khung ngày hôm nay của báo cáo.

	Ca mặc định 00:00-23:30 bỏ sót thao tác test tạo khi CI chạy sau 23:30 giờ VN (HRMS không cho ca 00:00-23:59:59).
	Bắt đầu = max(now - 1 giờ, 00:00 hôm nay); kết thúc = now + 1 giờ, qua nửa đêm thì thành ca đêm.
	"""
	midnight = datetime.combine(now.date(), datetime.min.time())
	begin = max(now - timedelta(hours=1), midnight)
	return begin.strftime("%H:%M:%S"), (now + timedelta(hours=1)).strftime("%H:%M:%S")


def assignment(employee, shift, zone=None, start=None, end=None, **fields):
	doc = frappe.get_doc(
		{
			"doctype": "Shift Assignment",
			"employee": employee,
			"shift_type": shift,
			"company": "_Test Company",
			"start_date": start or today(),
			"end_date": end or start or today(),
			"status": "Active",
			"tc_zone": zone,
			**fields,
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


class ShiftCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user("shift-r02@example.com", ["TC R02"])
		self.worker_user = make_user("shift-r04@example.com", ["TC R04"])
		self.employee = make_station_employee(self.worker_user)
		self.zone = frappe.db.get_value("Zone Station", STATION, "parent_zone")
		self.shift = shift_type()
		self.addCleanup(frappe.set_user, "Administrator")

	def grant(self, **kwargs):
		frappe.set_user(self.r02)
		doc = competency.grant(
			self.employee.name, STATION, valid_until=add_days(now_datetime(), 60), **kwargs
		)
		frappe.set_user("Administrator")
		return doc


class TestShiftAssignment(ShiftCase):
	@bru("BRU-HR-001")
	def test_employee_without_competency_in_the_zone_cannot_be_scheduled(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			assignment(self.employee.name, self.shift, self.zone)
		self.assertIn(self.zone, str(caught.exception))

	def test_competency_at_one_station_of_the_zone_is_enough(self):
		self.grant()
		self.assertEqual(assignment(self.employee.name, self.shift, self.zone).tc_zone, self.zone)

	def test_competency_in_another_zone_does_not_count(self):
		self.grant()
		other = next(z for z in ("ZONE-DIRTY", "ZONE-STERILE") if z != self.zone)
		with self.assertRaises(frappe.ValidationError):
			assignment(self.employee.name, self.shift, other)

	@bru("BRU-HR-001")
	def test_missing_required_certificate_blocks_scheduling(self):
		self.grant(required_certificates=["Pressure Equipment Operation"])
		with self.assertRaises(frappe.ValidationError):
			assignment(self.employee.name, self.shift, self.zone)

	def test_revoked_or_expired_competency_does_not_count(self):
		doc = self.grant()
		frappe.set_user(self.r02)
		competency.revoke(doc.name, "Đổi khu")
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			assignment(self.employee.name, self.shift, self.zone)

	def test_competency_must_cover_the_shift_dates(self):
		self.grant()
		with self.assertRaises(frappe.ValidationError):
			assignment(self.employee.name, self.shift, self.zone, start=add_days(today(), 90))

	def test_assignment_without_a_zone_is_not_checked(self):
		self.assertIsNone(assignment(self.employee.name, self.shift).tc_zone)

	def test_zone_field_must_be_a_zone_not_a_station(self):
		with self.assertRaises(frappe.ValidationError):
			assignment(self.employee.name, self.shift, STATION)

	def test_overlapping_assignment_for_the_same_employee_is_rejected(self):
		self.grant()
		assignment(self.employee.name, self.shift, self.zone)
		with self.assertRaises(frappe.ValidationError):
			assignment(self.employee.name, shift_type(), self.zone)


class TestShiftAssignmentForm(IsolatedTestCase):
	def test_shift_location_is_hidden(self):
		"""Shift Location (chấm công GPS của HRMS) không dùng ở TraceCore; khu của ca là `tc_zone` nên ẩn để khỏi tạo nhầm."""
		self.assertTrue(frappe.get_meta("Shift Assignment").get_field("shift_location").hidden)

	def test_hidden_shift_location_ships_as_fixture(self):
		from tracecore import hooks

		names = [
			row["filters"][0][2]
			for row in hooks.fixtures
			if row["dt"] == "Property Setter" and "filters" in row
		]
		self.assertIn("Shift Assignment-shift_location-hidden", names)


class TestShiftSchedule(ShiftCase):
	def test_week_schedule_lists_each_day_of_each_assignment(self):
		monday = add_days(getdate(today()), -getdate(today()).weekday())
		# thứ Hai đầu tuần có thể đã qua: năng lực phải có hiệu lực từ trước đó mới xếp ca được
		self.grant(valid_from=add_days(monday, -1))
		assignment(self.employee.name, self.shift, self.zone, start=monday, end=add_days(monday, 2))
		columns, rows = shift_schedule.execute({"from_date": monday, "to_date": add_days(monday, 6)})
		mine = [row for row in rows if row["employee"] == self.employee.name]
		self.assertEqual([str(row["date"]) for row in mine], [str(add_days(monday, i)) for i in range(3)])
		self.assertTrue(all(row["zone"] == self.zone and row["shift_type"] == self.shift for row in mine))
		self.assertTrue(columns)

	def test_default_range_is_the_current_week_and_zone_filter_applies(self):
		self.grant()
		assignment(self.employee.name, self.shift, self.zone)
		_, rows = shift_schedule.execute({})
		self.assertIn(self.employee.name, [row["employee"] for row in rows])
		_, other = shift_schedule.execute(
			{"zone": next(z for z in ("ZONE-DIRTY", "ZONE-STERILE") if z != self.zone)}
		)
		self.assertNotIn(self.employee.name, [row["employee"] for row in other])

	def test_assignments_outside_the_range_or_cancelled_are_left_out(self):
		self.grant()
		doc = assignment(self.employee.name, self.shift, self.zone)
		_, rows = shift_schedule.execute(
			{"from_date": add_days(today(), 10), "to_date": add_days(today(), 12)}
		)
		self.assertNotIn(self.employee.name, [row["employee"] for row in rows])
		doc.cancel()
		_, rows = shift_schedule.execute({})
		self.assertNotIn(self.employee.name, [row["employee"] for row in rows])


def gate_pass(unit, step, user, result="Pass"):
	"""Một kết quả cổng của chu trình 1 do `user` ghi bây giờ (dựng thẳng để người ghi và giờ ghi xác định)."""
	return frappe.get_doc(
		{
			"doctype": "Step Gate Result",
			"set_unit": unit.name,
			"cycle_no": 1,
			"step": step,
			"result": result,
			"recorded_by": user,
			"recorded_at": now_datetime(),
		}
	).insert(ignore_permissions=True)


class TestStationOutput(ShiftCase):
	def test_shift_around_now_contains_now_in_todays_window(self):
		for now in (
			datetime(2026, 10, 28, 23, 45),
			datetime(2026, 10, 28, 0, 15),
			datetime(2026, 10, 28, 10, 0),
		):
			begin, end = station_output.shift_window(now.date(), *shift_around(now))
			self.assertTrue(begin <= now <= end, (now, begin, end))

	def test_counts_sets_and_batches_recorded_by_the_employee_inside_the_shift(self):
		self.grant()
		# ca quanh lúc chạy test: không lệ thuộc giờ CI chạy (sau 23:30 ca mặc định đã kết thúc)
		assignment(self.employee.name, shift_type(*shift_around(now_datetime())), self.zone)
		units = [factories.make_set_unit() for _ in range(3)]
		gate_pass(units[0], "T1", self.worker_user)
		gate_pass(units[0], "T2", self.worker_user)  # cùng bộ, bước khác: vẫn tính một bộ
		gate_pass(units[1], "T1", self.worker_user)
		gate_pass(units[2], "T1", self.worker_user, result="Fail")  # không Pass: không tính
		machine = factories.make_wash_machine()
		factories.make_wash_batch(
			machine,
			factories.make_wash_program(machine),
			[factories.make_wash_ready_set()],
			operator=self.employee.name,
		)
		_, rows = station_output.execute({})
		row = next(r for r in rows if r["employee"] == self.employee.name)
		self.assertEqual((row["sets_processed"], row["batches"]), (2, 1))
		self.assertEqual(row["zone"], self.zone)

	def test_activity_outside_the_shift_window_is_not_counted(self):
		self.grant()
		early = shift_type("00:00:00", "00:00:01")
		assignment(self.employee.name, early, self.zone)
		gate_pass(factories.make_set_unit(), "T1", self.worker_user)
		_, rows = station_output.execute({})
		row = next(r for r in rows if r["employee"] == self.employee.name)
		self.assertEqual((row["sets_processed"], row["batches"]), (0, 0))

	def test_night_shift_window_crosses_midnight(self):
		window = station_output.shift_window(getdate(today()), "22:00:00", "06:00:00")
		self.assertEqual(window[1] - window[0], add_to_date(window[0], hours=8) - window[0])

	def test_filters_by_employee_and_zone(self):
		self.grant()
		assignment(self.employee.name, self.shift, self.zone)
		_, rows = station_output.execute({"employee": "NV-NOBODY"})
		self.assertEqual(rows, [])
		other = next(z for z in ("ZONE-DIRTY", "ZONE-STERILE") if z != self.zone)
		_, rows = station_output.execute({"zone": other})
		self.assertNotIn(self.employee.name, [row["employee"] for row in rows])
