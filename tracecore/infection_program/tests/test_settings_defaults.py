"""Giờ nhắc mặc định của IC Program Settings không bị thay bằng giờ hiện tại.

Frappe v15 (``frappe.model.create_new.set_dynamic_default_values``) gán ``nowtime()`` cho mọi trường Time của bản ghi
mới, bỏ qua ``default``. Site mới vì thế có giờ nhắc mẫu số / gói dự phòng = lúc lưu lần đầu thay vì 10:00 (CI PR #34
phần 1/6: 14:33:33.168823 → nhắc theo dõi NKVM lúc 11:00 không gửi).
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_time

from tracecore.infection_program import settings_defaults

SETTINGS = "IC Program Settings"


def _value(field):
	return get_time(frappe.db.get_single_value(SETTINGS, field))


class TestReminderTimeDefaults(FrappeTestCase):
	def _set(self, census, bundle):
		frappe.db.set_single_value(SETTINGS, {"census_reminder_time": census, "bundle_reminder_time": bundle})

	def test_auto_filled_times_are_reset_to_the_declared_default(self):
		self._set("14:33:33.168823", "14:33:33.168874")
		settings_defaults.ensure_reminder_times()
		self.assertEqual(_value("census_reminder_time"), get_time("10:00:00"))
		self.assertEqual(_value("bundle_reminder_time"), get_time("10:00:00"))

	def test_missing_times_get_the_declared_default(self):
		frappe.db.sql(
			"delete from tabSingles where doctype=%s and field in ('census_reminder_time','bundle_reminder_time')",
			SETTINGS,
		)
		settings_defaults.ensure_reminder_times()
		self.assertEqual(_value("census_reminder_time"), get_time("10:00:00"))

	def test_time_chosen_by_the_hospital_is_kept(self):
		self._set("13:30:00", "09:15:00")
		settings_defaults.ensure_reminder_times()
		self.assertEqual(_value("census_reminder_time"), get_time("13:30:00"))
		self.assertEqual(_value("bundle_reminder_time"), get_time("09:15:00"))

	def test_install_and_migrate_both_run_it(self):
		from tracecore.setup import install

		self.assertIn("ensure_reminder_times", install.after_install.__code__.co_names)
		with open(frappe.get_app_path("tracecore", "patches.txt"), encoding="utf-8") as handle:
			self.assertIn("tracecore.patches.v0_1.ic_reminder_time_defaults", handle.read())
