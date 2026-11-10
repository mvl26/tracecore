"""Nhắc mẫu số thiếu và gói dự phòng chưa chấm (FEAT-062; FR-M13-03, .1, .2, FR-M12-07, FR-M12-07.2; A-141 Q1, Q3, c, d)."""

from datetime import datetime, time

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core import notification
from tracecore.hai_surveillance import reminders
from tracecore.hai_surveillance.tests import factories as f
from tracecore.tests.utils import IsolatedTestCase


def _at(hour, minute=0, day=None):
	return datetime.combine(getdate(day or today()), time(hour, minute))


def _deliveries(event, department):
	return frappe.get_all(
		"Notification Delivery",
		filters={"event_code": event, "ref_doctype": "Department", "ref_name": department},
		pluck="recipient",
	)


class TestCensusReminder(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		self.ward = f.make_ward("KSNK Reminder ICU")
		self.clinic = f.make_ward("KSNK Reminder Clinic", inpatient=0)
		for department in (self.ward, self.clinic):
			frappe.db.delete("Ward Daily Census", {"department": department})
			frappe.db.delete("Device Episode", {"department": department})
		frappe.db.delete("Notification Delivery", {"event_code": ["in", [reminders.CENSUS_EVENT, reminders.BUNDLE_EVENT]]})
		self.r12 = f.make_dept_user("r12-reminder@test.local", f.R12, self.ward)
		self.r08 = f.make_dept_user("r08-reminder@test.local", f.R08, self.ward)
		self.r11 = f.factories.make_user("r11-reminder@test.local", [f.R11])
		frappe.db.set_single_value("IC Program Settings", {"census_reminder_time": "10:00:00", "bundle_reminder_time": "11:00:00"})

	def test_before_time_nothing(self):
		reminders.run(_at(9, 45))
		self.assertEqual(_deliveries(reminders.CENSUS_EVENT, self.ward), [])

	def test_missing_census_reminds_network_member_and_supervisor_once(self):
		reminders.run(_at(10, 0))
		recipients = set(_deliveries(reminders.CENSUS_EVENT, self.ward))
		self.assertIn(self.r12, recipients)
		self.assertIn(self.r11, recipients)
		self.assertNotIn(self.r08, recipients)
		count = len(_deliveries(reminders.CENSUS_EVENT, self.ward))
		reminders.run(_at(10, 15))
		self.assertEqual(len(_deliveries(reminders.CENSUS_EVENT, self.ward)), count)

	def test_non_inpatient_ward_not_reminded(self):
		reminders.run(_at(10, 0))
		self.assertEqual(_deliveries(reminders.CENSUS_EVENT, self.clinic), [])

	def test_census_present_not_reminded(self):
		f.make_census(self.ward, add_days(today(), -1))
		reminders.run(_at(10, 0))
		self.assertEqual(_deliveries(reminders.CENSUS_EVENT, self.ward), [])

	def test_configured_time(self):
		frappe.db.set_single_value("IC Program Settings", "census_reminder_time", "13:30:00")
		reminders.run(_at(12, 0))
		self.assertEqual(_deliveries(reminders.CENSUS_EVENT, self.ward), [])
		reminders.run(_at(13, 30))
		self.assertTrue(_deliveries(reminders.CENSUS_EVENT, self.ward))

	def test_open_episode_without_bundle_reminds_ward(self):
		f.make_census(self.ward, add_days(today(), -1))
		f.make_episode(self.ward)
		f.make_episode(self.ward, code="BN-0000002214", device="Urinary Catheter")
		reminders.run(_at(10, 30))
		self.assertEqual(_deliveries(reminders.BUNDLE_EVENT, self.ward), [])  # giờ nhắc gói là 11:00
		reminders.run(_at(11, 0))
		recipients = set(_deliveries(reminders.BUNDLE_EVENT, self.ward))
		self.assertEqual(recipients, {self.r08, self.r12})
		message = frappe.db.get_value(
			"Notification Delivery",
			{"event_code": reminders.BUNDLE_EVENT, "ref_name": self.ward, "recipient": self.r12},
			"message",
		)
		self.assertIn("***4821", message)
		self.assertIn("***2214", message)
		self.assertNotIn("BN-0000004821", message)
		reminders.run(_at(11, 15))
		self.assertEqual(len(_deliveries(reminders.BUNDLE_EVENT, self.ward)), 2)

	def test_closed_episode_not_reminded(self):
		episode = f.make_episode(self.ward)
		frappe.db.set_value("Device Episode", episode.name, "status", "Closed")
		reminders.run(_at(11, 0))
		self.assertEqual(_deliveries(reminders.BUNDLE_EVENT, self.ward), [])

	def test_checked_episode_not_reminded(self):
		episode = f.make_episode(self.ward)
		f.post_bundle(episode, "Pass")
		reminders.run(_at(11, 0))
		self.assertEqual(_deliveries(reminders.BUNDLE_EVENT, self.ward), [])

	def test_bundle_episodes_filter(self):
		episode = f.make_episode(self.ward)
		self.assertEqual([row.name for row in reminders.unchecked_episodes(getdate(today()))], [episode.name])
