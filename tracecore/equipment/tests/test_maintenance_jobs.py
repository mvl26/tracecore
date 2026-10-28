"""Việc định kỳ của bảo trì thiết bị (FEAT-039; FR-M5-03 nhắc 30/7 ngày, FR-M5-03.1 khóa quá hạn; UC-22; BRU-EQP-002; A-42 M1, M5)."""

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, today

from tracecore.equipment import daily_test, maintenance
from tracecore.reprocessing import sterilizing
from tracecore.tests.factories import make_equipment, make_maintenance_record, make_sterilizer, make_user
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Maintenance Record"


class JobCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user("mj-r02@example.com", ["TC R02"])
		self.r10 = make_user("mj-r10@example.com", ["TC R10"])
		self.r03 = make_user("mj-r03@example.com", ["TC R03"])
		self.machine = make_sterilizer()

	def notifications(self, user, document_type, name):
		return frappe.db.count(
			"Notification Log", {"for_user": user, "document_type": document_type, "document_name": name}
		)

	def state(self, machine=None):
		return frappe.db.get_value(
			"Equipment", (machine or self.machine).name, ["status", "lock_reason"], as_dict=True
		)

	def set_due(self, field, days, machine=None):
		frappe.db.set_value("Equipment", (machine or self.machine).name, field, add_days(today(), days))


class TestLockOverdue(JobCase):
	@bru("BRU-EQP-002")
	def test_expired_inspection_locks_a_ready_machine(self):  # FR-M5-03.1
		self.set_due("inspection_due", -1)
		self.assertEqual(maintenance.lock_overdue(), [self.machine.name])
		state = self.state()
		self.assertEqual((state.status, state.lock_reason), ("Locked", "Inspection Expired"))
		self.assertEqual(sterilizing.check_equipment_ready(self.machine.name).code, "EQUIPMENT_NOT_READY")

	@bru("BRU-EQP-002")
	def test_expired_calibration_locks_a_ready_machine(self):
		self.set_due("calibration_due", -1)
		self.assertEqual(maintenance.lock_overdue(), [self.machine.name])
		state = self.state()
		self.assertEqual((state.status, state.lock_reason), ("Locked", "Calibration Expired"))

	def test_inspection_wins_when_both_are_expired(self):
		self.set_due("inspection_due", -3)
		self.set_due("calibration_due", -1)
		maintenance.lock_overdue()
		self.assertEqual(self.state().lock_reason, "Inspection Expired")

	def test_due_today_or_later_is_not_expired(self):
		self.set_due("inspection_due", 0)
		self.set_due("calibration_due", 5)
		self.assertEqual(maintenance.lock_overdue(), [])
		self.assertEqual(self.state().status, "Ready")

	def test_preventive_maintenance_overdue_does_not_lock(self):
		self.set_due("maintenance_due", -10)
		self.assertEqual(maintenance.lock_overdue(), [])
		self.assertEqual(self.state().status, "Ready")

	def test_machines_that_are_not_ready_are_left_alone(self):
		self.set_due("inspection_due", -1)
		for status in ("Repair", "Retired"):
			frappe.db.set_value("Equipment", self.machine.name, "status", status)
			self.assertEqual(maintenance.lock_overdue(), [])
			self.assertEqual(self.state().status, status)
		frappe.db.set_value("Equipment", self.machine.name, "status", "Ready")
		daily_test._apply(self.machine.name, status="Locked", lock_reason=daily_test.LOCK_DAILY_TEST)
		maintenance.lock_overdue()
		self.assertEqual(self.state().lock_reason, "Daily Test")

	def test_a_temporary_unlock_is_respected_until_it_ends(self):
		self.set_due("calibration_due", -1)
		frappe.db.set_value(
			"Equipment", self.machine.name, "unlock_until", add_to_date(now_datetime(), hours=3)
		)
		self.assertEqual(maintenance.lock_overdue(), [])
		frappe.db.set_value(
			"Equipment", self.machine.name, "unlock_until", add_to_date(now_datetime(), hours=-1)
		)
		self.assertEqual(maintenance.lock_overdue(), [self.machine.name])

	def test_running_twice_locks_and_notifies_once(self):
		self.set_due("inspection_due", -1)
		maintenance.lock_overdue()
		self.assertEqual(maintenance.lock_overdue(), [])
		for user in (self.r02, self.r10):
			self.assertEqual(self.notifications(user, "Equipment", self.machine.name), 1)
		self.assertEqual(self.notifications(self.r03, "Equipment", self.machine.name), 0)


class TestRemindDue(JobCase):
	def plan(self, days, kind="Inspection", **kwargs):
		return make_maintenance_record(
			self.machine.name, kind, planned_date=add_days(today(), days), **kwargs
		)

	def count(self, doc, user=None):
		return self.notifications(user or self.r02, DOCTYPE, doc.name)

	def flags(self, doc):
		return frappe.db.get_value(DOCTYPE, doc.name, ["reminded_30", "reminded_7"], as_dict=True)

	@bru("BRU-EQP-002")
	def test_reminds_r02_and_r10_30_days_ahead_once(self):  # FR-M5-03
		doc = self.plan(30)
		maintenance.remind_due()
		self.assertEqual((self.count(doc), self.count(doc, self.r10), self.count(doc, self.r03)), (1, 1, 0))
		self.assertEqual(self.flags(doc), {"reminded_30": 1, "reminded_7": 0})
		maintenance.remind_due()
		self.assertEqual(self.count(doc), 1)

	def test_nothing_before_the_30_day_window(self):
		doc = self.plan(31)
		maintenance.remind_due()
		self.assertEqual(self.count(doc), 0)

	@bru("BRU-EQP-002")
	def test_reminds_again_at_7_days(self):
		doc = self.plan(20)
		maintenance.remind_due()
		frappe.db.set_value(DOCTYPE, doc.name, "planned_date", add_days(today(), 7))
		maintenance.remind_due()
		self.assertEqual(self.count(doc), 2)
		self.assertEqual(self.flags(doc), {"reminded_30": 1, "reminded_7": 1})
		maintenance.remind_due()
		self.assertEqual(self.count(doc), 2)

	def test_a_record_first_seen_inside_7_days_gets_a_single_reminder(self):
		doc = self.plan(3)
		maintenance.remind_due()
		maintenance.remind_due()
		self.assertEqual(self.count(doc), 1)
		self.assertEqual(self.flags(doc), {"reminded_30": 1, "reminded_7": 1})

	def test_overdue_planned_record_is_reminded_once(self):
		doc = self.plan(-4)
		maintenance.remind_due()
		maintenance.remind_due()
		self.assertEqual(self.count(doc), 1)

	def test_closed_abandoned_incident_and_unplanned_records_are_skipped(self):
		submitted = self.plan(2, "Preventive")
		submitted.submit()
		abandoned = self.plan(2, "Preventive")
		abandoned.abandon("Không còn cần")
		incident = self.plan(2, "Incident")
		unplanned = make_maintenance_record(self.machine.name, "Preventive", planned_date=None)
		maintenance.remind_due()
		for doc in (submitted, abandoned, incident, unplanned):
			row = frappe.db.get_value(
				DOCTYPE,
				doc.name,
				["name", "record_type", "docstatus", "abandoned", "planned_date"],
				as_dict=True,
			)
			self.assertEqual(self.count(doc), 0, str(row))

	def test_other_machines_records_are_reminded_too(self):
		other = make_equipment(serial="SN-JOBS-2")
		doc = make_maintenance_record(other.name, "Calibration", planned_date=add_days(today(), 10))
		maintenance.remind_due()
		self.assertEqual(self.count(doc), 1)


class TestScheduling(IsolatedTestCase):
	def test_jobs_are_registered_in_the_scheduler(self):
		events = frappe.get_hooks("scheduler_events")
		self.assertIn("tracecore.equipment.maintenance.lock_overdue", events["cron"]["0 0 * * *"])
		self.assertIn("tracecore.equipment.maintenance.remind_due", events["daily"])
