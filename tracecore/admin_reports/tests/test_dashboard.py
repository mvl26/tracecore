"""Dashboard vận hành (FEAT-006, FR-M9-01, FR-M9-01.2, UC-32, SCR-32): số liệu tổng hợp của dịch vụ M9.

Dữ liệu dựng bằng ``db_insert`` (không qua dịch vụ nghiệp vụ) vì đây chỉ kiểm phép đếm; site test có sẵn dữ liệu của test
khác nên so sánh theo phần chênh lệch hoặc lọc theo bản ghi của test.
"""

from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from tracecore.admin_reports import dashboard
from tracecore.tests.factories import make_employee, make_equipment, make_set_unit
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def insert(doctype, **values):
	"""Bản ghi `doctype` ghi thẳng vào DB (bỏ validate/link) với tên ngẫu nhiên; trả tên."""
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.name = "TEST-" + frappe.generate_hash(length=10)
	doc.db_insert()
	return doc.name


def by_key(rows, key):
	return {row[key]: row for row in rows}


class TestPeriodRange(IsolatedTestCase):
	def test_day_week_month_ranges_end_exclusive(self):
		on = datetime(2026, 10, 29, 15, 30)  # thứ Năm
		self.assertEqual(dashboard.period_range("day", on), (datetime(2026, 10, 29), datetime(2026, 10, 30)))
		self.assertEqual(dashboard.period_range("week", on), (datetime(2026, 10, 26), datetime(2026, 11, 2)))
		self.assertEqual(dashboard.period_range("month", on), (datetime(2026, 10, 1), datetime(2026, 11, 1)))
		self.assertEqual(
			dashboard.period_range("month", datetime(2026, 12, 5)),
			(datetime(2026, 12, 1), datetime(2027, 1, 1)),
		)

	def test_unknown_period_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			dashboard.period_range("year")


class TestSetStatusCounts(IsolatedTestCase):
	def test_every_status_is_listed_and_counts_follow_the_data(self):
		before = by_key(dashboard.set_status_counts(), "status")
		self.assertEqual(list(before), list(dashboard.SET_STATUSES))
		self.assertTrue(all(row["count"] >= 0 for row in before.values()))
		make_set_unit()
		after = by_key(dashboard.set_status_counts(), "status")
		self.assertEqual(after["New"]["count"], before["New"]["count"] + 1)
		self.assertEqual(after["Sterile"]["count"], before["Sterile"]["count"])

	def test_department_filter_without_sets_gives_zero_for_every_status(self):
		rows = dashboard.set_status_counts(department="No such department")
		self.assertEqual([row["count"] for row in rows], [0] * len(dashboard.SET_STATUSES))


class TestOutput(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.start, self.end = dashboard.period_range("day")
		self.now = now_datetime()
		self.station = "TR-004"
		self.unit = make_set_unit().name

	def gate(self, result="Pass", at=None, station=None, user="Administrator"):
		return insert(
			"Step Gate Result",
			set_unit=self.unit,
			cycle_no=1,
			step="T4",
			result=result,
			station=station or self.station,
			recorded_by=user,
			recorded_at=at or self.now,
		)

	def test_station_and_user_count_passed_gates_inside_the_period(self):
		before_station = by_key(dashboard.output_by_station(self.start, self.end), "station")
		before_user = by_key(dashboard.output_by_user(self.start, self.end), "user")
		self.gate()
		self.gate()
		self.gate(result="Fail")
		self.gate(at=self.start - timedelta(minutes=1))
		station = by_key(dashboard.output_by_station(self.start, self.end), "station")[self.station]
		user = by_key(dashboard.output_by_user(self.start, self.end), "user")["Administrator"]
		self.assertEqual(station["count"], before_station.get(self.station, {"count": 0})["count"] + 2)
		self.assertEqual(user["count"], before_user.get("Administrator", {"count": 0})["count"] + 2)
		self.assertTrue(station["station_name"])
		self.assertTrue(user["full_name"])

	def test_zone_filter_keeps_only_stations_of_that_zone(self):
		zone = frappe.db.get_value("Zone Station", self.station, "parent_zone")
		other = next(z for z in ("ZONE-DIRTY", "ZONE-STERILE") if z != zone)
		self.gate()
		self.assertIn(
			self.station, by_key(dashboard.output_by_station(self.start, self.end, zone=zone), "station")
		)
		self.assertNotIn(
			self.station, by_key(dashboard.output_by_station(self.start, self.end, zone=other), "station")
		)

	def test_rows_are_sorted_and_limited(self):
		for _ in range(3):
			self.gate(station="TR-003")
		rows = dashboard.output_by_station(self.start, self.end, limit=1)
		self.assertEqual(len(rows), 1)
		counts = [row["count"] for row in dashboard.output_by_station(self.start, self.end)]
		self.assertEqual(counts, sorted(counts, reverse=True))

	def test_equipment_counts_wash_batches_and_loads_started_in_the_period(self):
		washer = make_equipment(
			name="Máy rửa dash",
			equipment_type="Washer-Disinfector",
			serial="WD-" + frappe.generate_hash(length=6),
		).name
		sterilizer = make_equipment(name="Máy hấp dash", serial="ST-" + frappe.generate_hash(length=6)).name
		insert("Wash Batch", equipment=washer, status="Passed", started_at=self.now)
		insert("Wash Batch", equipment=washer, status="Running", started_at=self.now)
		insert("Sterilization Load", equipment=sterilizer, status="Released", started_at=self.now)
		insert(
			"Sterilization Load",
			equipment=sterilizer,
			status="Released",
			started_at=self.start - timedelta(days=1),
		)
		rows = by_key(dashboard.output_by_equipment(self.start, self.end), "equipment")
		self.assertEqual((rows[washer]["wash"], rows[washer]["load"], rows[washer]["count"]), (2, 0, 2))
		self.assertEqual(
			(rows[sterilizer]["wash"], rows[sterilizer]["load"], rows[sterilizer]["count"]), (0, 1, 1)
		)
		self.assertEqual(rows[washer]["equipment_name"], "Máy rửa dash")
		only = dashboard.output_by_equipment(self.start, self.end, equipment=washer)
		self.assertEqual([row["equipment"] for row in only], [washer])


class TestFailureRates(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.start, self.end = dashboard.period_range("day")
		self.sterilizer = make_equipment(
			name="Máy hấp lỗi", serial="SF-" + frappe.generate_hash(length=6)
		).name
		self.washer = make_equipment(
			name="Máy rửa lỗi",
			equipment_type="Washer-Disinfector",
			serial="WF-" + frappe.generate_hash(length=6),
		).name

	def test_rates_count_finished_loads_and_batches_only(self):
		now = now_datetime()
		for status in ("Released", "Released", "Quarantine", "Failed", "Running", "Cycle Complete"):
			insert("Sterilization Load", equipment=self.sterilizer, status=status, started_at=now)
		for status in ("Passed", "Failed", "Running"):
			insert("Wash Batch", equipment=self.washer, status=status, started_at=now)
		load = dashboard.failure_rates(self.start, self.end, equipment=self.sterilizer)["load"]
		wash = dashboard.failure_rates(self.start, self.end, equipment=self.washer)["wash"]
		self.assertEqual((load["failed"], load["finished"], load["percent"]), (1, 4, 25.0))
		self.assertEqual((wash["failed"], wash["finished"], wash["percent"]), (1, 2, 50.0))

	def test_no_finished_load_gives_zero_percent(self):
		rates = dashboard.failure_rates(self.start, self.end, equipment=self.sterilizer)
		self.assertEqual(rates["load"], {"failed": 0, "finished": 0, "percent": 0})
		self.assertEqual(rates["wash"], {"failed": 0, "finished": 0, "percent": 0})


class TestActionLists(IsolatedTestCase):
	def test_pending_overrides_are_requested_only(self):
		before = dashboard.pending_overrides()["count"]
		unit = make_set_unit().name
		requested = insert("Par Override", set_unit=unit, status="Requested", requested_at=now_datetime())
		insert("Par Override", set_unit=unit, status="Approved", requested_at=now_datetime())
		result = dashboard.pending_overrides()
		self.assertEqual(result["count"], before + 1)
		self.assertIn(requested, [row["name"] for row in result["rows"]])

	def test_open_recalls_with_unconfirmed_packs(self):
		before = dashboard.open_recalls()["count"]
		pending = insert(
			"Recall Order", status="Open", pack_count=4, confirmed_count=2, opened_at=now_datetime()
		)
		insert("Recall Order", status="Open", pack_count=3, confirmed_count=3, opened_at=now_datetime())
		insert("Recall Order", status="Closed", pack_count=3, confirmed_count=1, opened_at=now_datetime())
		result = dashboard.open_recalls()
		self.assertEqual(result["count"], before + 1)
		self.assertIn(pending, [row["name"] for row in result["rows"]])

	def test_certificates_expiring_or_expired_of_active_staff(self):
		staff = make_employee(first_name="Dash cert").name
		left = make_employee(first_name="Dash left", status="Left", relieving_date=today()).name
		soon = insert(
			"Certificate", employee=staff, status="Valid", no_expiry=0, expires_on=add_days(today(), 20)
		)
		gone = insert(
			"Certificate", employee=staff, status="Expired", no_expiry=0, expires_on=add_days(today(), -3)
		)
		far = insert(
			"Certificate", employee=staff, status="Valid", no_expiry=0, expires_on=add_days(today(), 200)
		)
		forever = insert("Certificate", employee=staff, status="Valid", no_expiry=1)
		of_left = insert(
			"Certificate", employee=left, status="Expired", no_expiry=0, expires_on=add_days(today(), -3)
		)
		names = [row["name"] for row in dashboard.expiring_certificates(limit=500)["rows"]]
		self.assertIn(soon, names)
		self.assertIn(gone, names)
		for name in (far, forever, of_left):
			self.assertNotIn(name, names)
		row = next(row for row in dashboard.expiring_certificates(limit=500)["rows"] if row["name"] == soon)
		self.assertEqual(row["days_left"], 20)

	def test_equipment_needing_attention(self):
		locked = make_equipment(
			name="Máy khóa", serial="LK-" + frappe.generate_hash(length=6), daily_tested=False
		)
		frappe.db.set_value("Equipment", locked.name, {"status": "Locked", "lock_reason": "Daily Test"})
		due = make_equipment(
			name="Máy sắp kiểm định",
			serial="DU-" + frappe.generate_hash(length=6),
			inspection_due=add_days(today(), 10),
		)
		fine = make_equipment(
			name="Máy ổn",
			serial="OK-" + frappe.generate_hash(length=6),
			inspection_due=add_days(today(), 300),
		)
		retired = make_equipment(name="Máy thanh lý", serial="RT-" + frappe.generate_hash(length=6))
		frappe.db.set_value(
			"Equipment", retired.name, {"status": "Retired", "inspection_due": add_days(today(), 1)}
		)
		rows = by_key(dashboard.equipment_attention(limit=500)["rows"], "name")
		self.assertIn(locked.name, rows)
		self.assertEqual(rows[due.name]["due_in"], 10)
		self.assertNotIn(fine.name, rows)
		self.assertNotIn(retired.name, rows)

	def test_lists_are_limited_but_count_everything(self):
		for _ in range(3):
			insert("Recall Order", status="Open", pack_count=2, confirmed_count=0, opened_at=now_datetime())
		result = dashboard.open_recalls(limit=2)
		self.assertEqual(len(result["rows"]), 2)
		self.assertGreaterEqual(result["count"], 3)


class TestEmptyGivesZero(IsolatedTestCase):
	def test_period_without_data_gives_zero(self):
		start = datetime(1990, 1, 1)
		end = start + timedelta(days=1)
		self.assertEqual(dashboard.output_by_station(start, end), [])
		self.assertEqual(dashboard.output_by_user(start, end), [])
		self.assertEqual(dashboard.output_by_equipment(start, end), [])
		rates = dashboard.failure_rates(start, end)
		self.assertEqual(rates["load"]["percent"], 0)
		self.assertEqual(rates["wash"]["percent"], 0)
		self.assertEqual(getdate(start), getdate("1990-01-01"))
