"""Nhật ký môi trường khu (FEAT-008, FR-M9-04, FR-M9-04.1, FR-M9-04.2, UC-33 bước 3, A-55)."""

from datetime import datetime, time
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

from tracecore.admin_reports import environment
from tracecore.core import notification
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
ZONE = "ZONE-CLEAN"
OTHER_ZONE = "ZONE-DIRTY"


def monitor(zone=ZONE, **limits):
	doc = frappe.get_doc("Zone Station", zone)
	doc.update({"env_monitored": 1, **limits})
	doc.save(ignore_permissions=True)


def reading(zone=ZONE, submit=True, measured_at=None, **values):
	doc = frappe.get_doc(
		{
			"doctype": "Environment Log",
			"zone": zone,
			"measured_at": measured_at or add_to_date(now_datetime(), minutes=-1),
			**values,
		}
	)
	doc.insert()
	if submit:
		doc.submit()
	return doc


def at(day, hour, minute=0):
	return datetime.combine(getdate(day), time(hour, minute))


class EnvCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")
		self.r04 = make_user("env-r04@example.com", ["TC R04"])
		self.r02 = make_user("env-r02@example.com", ["TC R02"])
		monitor()


class TestEnvironmentLog(EnvCase):
	def test_reading_is_recorded_with_zone_values_source_and_recorder(self):
		frappe.set_user(self.r04)
		doc = reading(temperature=21.5, humidity=55, pressure_diff=8)
		self.assertEqual(doc.docstatus, 1)
		self.assertTrue(doc.name.startswith("MT-"))
		self.assertEqual((doc.source, doc.recorded_by), ("Manual", self.r04))
		self.assertEqual(str(doc.log_date), str(getdate(doc.measured_at)))
		self.assertEqual(doc.out_of_range, 0)

	def test_needs_at_least_one_value(self):
		with self.assertRaises(frappe.ValidationError):
			reading()

	def test_humidity_must_be_a_percentage(self):
		with self.assertRaises(frappe.ValidationError):
			reading(humidity=120)
		with self.assertRaises(frappe.ValidationError):
			reading(humidity=-1)

	def test_future_time_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			reading(temperature=20, measured_at=add_to_date(now_datetime(), minutes=30))

	def test_zone_must_be_a_monitored_zone(self):
		with self.assertRaises(frappe.ValidationError):
			reading(zone="TR-004", temperature=20)  # trạm, không phải khu
		with self.assertRaises(frappe.ValidationError):
			reading(zone=OTHER_ZONE, temperature=20)  # khu chưa bật theo dõi

	def test_reading_out_of_range_is_flagged_and_alerts_r02(self):
		monitor(temp_min=18, temp_max=24, humidity_max=60)
		with patch.object(notification, "emit") as emit:
			doc = reading(temperature=26, humidity=50)
		self.assertEqual(doc.out_of_range, 1)
		self.assertIn("temperature", doc.breaches)
		self.assertNotIn("humidity", doc.breaches)
		self.assertEqual(emit.call_args.args[0], "ENV_OUT_OF_RANGE")

	def test_reading_in_range_does_not_alert(self):
		monitor(temp_min=18, temp_max=24)
		with patch.object(notification, "emit") as emit:
			doc = reading(temperature=24)
		self.assertEqual(doc.out_of_range, 0)
		emit.assert_not_called()

	def test_blank_limit_is_not_checked(self):
		monitor(temp_min=18, temp_max=None, pressure_min=5)
		self.assertEqual(reading(temperature=40).out_of_range, 0)
		self.assertEqual(reading(pressure_diff=2).out_of_range, 1)

	def test_draft_does_not_alert(self):
		monitor(temp_max=24)
		with patch.object(notification, "emit") as emit:
			reading(temperature=30, submit=False)
		emit.assert_not_called()

	def test_reading_cannot_be_deleted(self):
		doc = reading(temperature=20, submit=False)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Environment Log", doc.name)

	def test_permissions_follow_the_matrix(self):
		assert_permission_matrix(self, "Environment Log")

	def test_zone_staff_can_record_and_read_zones(self):
		for role in ("TC R03", "TC R04", "TC R05", "TC R06"):
			user = make_user(f"env-{role[-3:].lower()}@example.com", [role])
			self.assertTrue(frappe.has_permission("Environment Log", "create", user=user), role)
			self.assertTrue(frappe.has_permission("Zone Station", "read", user=user), role)
		r07 = make_user("env-r07@example.com", ["TC R07"])
		self.assertFalse(frappe.has_permission("Environment Log", "create", user=r07))


class TestZoneLimits(EnvCase):
	def test_limits_accept_decimal_comma_and_keep_blank(self):
		monitor(temp_min="18,5", temp_max=" 24 ", humidity_max="")
		row = frappe.db.get_value(
			"Zone Station", ZONE, ["temp_min", "temp_max", "humidity_max"], as_dict=True
		)
		self.assertEqual((row.temp_min, row.temp_max, row.humidity_max), ("18.5", "24", None))

	def test_limits_must_be_numbers_with_min_not_above_max(self):
		with self.assertRaises(frappe.ValidationError):
			monitor(temp_min="cold")
		with self.assertRaises(frappe.ValidationError):
			monitor(humidity_min=70, humidity_max=60)

	def test_stations_never_monitor(self):
		station = frappe.get_doc("Zone Station", "TR-004")
		station.env_monitored = 1
		station.save(ignore_permissions=True)
		self.assertEqual(station.env_monitored, 0)


class TestReminderTimes(EnvCase):
	def test_times_are_sorted_and_unique(self):
		self.assertEqual(environment.parse_times("17:00, 11:00,11:00"), [time(11, 0), time(17, 0)])
		self.assertEqual(environment.parse_times(""), [])

	def test_settings_reject_invalid_times(self):
		settings = frappe.get_single("TraceCore Settings")
		for bad in ("25:00", "11h", "11:00; 17:00"):
			settings.env_reminder_times = bad
			with self.assertRaises(frappe.ValidationError, msg=bad):
				settings.save()

	def test_default_times(self):
		self.assertEqual(
			frappe.get_meta("TraceCore Settings").get_field("env_reminder_times").default, "11:00, 17:00"
		)


class TestRemindMissing(EnvCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		frappe.db.set_single_value("TraceCore Settings", "env_reminder_times", "11:00, 17:00")
		self.day = add_days(today(), -1)

	def reminders(self, zone=ZONE):
		return frappe.db.count(
			"Notification Delivery",
			{"event_code": "ENV_LOG_MISSING", "recipient": self.r02, "ref_name": zone},
		)

	def test_zone_without_a_reading_before_the_time_is_reminded_once(self):
		environment.remind_missing(now=at(self.day, 11, 5))
		self.assertEqual(self.reminders(), 1)
		environment.remind_missing(now=at(self.day, 11, 20))
		self.assertEqual(self.reminders(), 1)

	def test_reading_in_the_window_prevents_the_reminder(self):
		reading(temperature=20, measured_at=at(self.day, 10))
		environment.remind_missing(now=at(self.day, 11, 5))
		self.assertEqual(self.reminders(), 0)

	def test_each_time_checks_its_own_window(self):
		reading(temperature=20, measured_at=at(self.day, 10))
		environment.remind_missing(now=at(self.day, 17, 5))
		self.assertEqual(self.reminders(), 1)  # 11:00-17:00 chưa đo

	def test_nothing_before_the_first_time_or_for_unmonitored_zones(self):
		environment.remind_missing(now=at(self.day, 10, 30))
		self.assertEqual(self.reminders(), 0)
		environment.remind_missing(now=at(self.day, 11, 5))
		self.assertEqual(self.reminders(OTHER_ZONE), 0)

	def test_draft_reading_does_not_count(self):
		reading(temperature=20, measured_at=at(self.day, 10), submit=False)
		environment.remind_missing(now=at(self.day, 11, 5))
		self.assertEqual(self.reminders(), 1)

	def test_no_times_no_reminder(self):
		frappe.db.set_single_value("TraceCore Settings", "env_reminder_times", "")
		environment.remind_missing(now=at(self.day, 18))
		self.assertEqual(self.reminders(), 0)
