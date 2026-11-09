"""Nhắc hạn kế hoạch năm, kết luận họp, văn bản nội bộ (FEAT-058 AC-5, AC-8, AC-11; FR-M11-05, .1, FR-M11-07, FR-M11-08)."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core import notification
from tracecore.infection_program import annual_plan, reminders
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests.utils import IsolatedTestCase, bru

YEAR = getdate(today()).year


def _sent(event, user=None):
	filters = {"event_code": event, "channel": "In App"}
	if user:
		filters["recipient"] = user
	return frappe.db.count("Notification Delivery", filters)


class TestICReminders(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		frappe.db.sql("delete from `tabNotification Delivery` where event_code like 'IC\\_%%'")
		frappe.db.sql("delete from `tabIC Procedure Document`")
		fx.clear_plans(YEAR)
		self.r01 = fx.user("R01", prefix="remind")
		self.owner_user = fx.user("R11", prefix="remind-owner")
		self.owner = fx.employee("Remind Owner", user=self.owner_user)

	def test_events_registered_with_r01_default(self):
		for code in (
			"IC_PLAN_ACTIVITY_DUE",
			"IC_PLAN_ACTIVITY_OVERDUE",
			"IC_RESOLUTION_DUE",
			"IC_RESOLUTION_OVERDUE",
			"IC_DOCUMENT_REVIEW_DUE",
		):
			self.assertEqual(notification.EVENTS[code][4], ("TC R01",), code)
			self.assertTrue(frappe.db.exists("Notification Rule", code))

	def test_display_status(self):
		on = getdate("2026-11-09")
		self.assertEqual(reminders.display_status("Completed", "2026-01-01", on), "completed")
		self.assertEqual(reminders.display_status("Planned", "2026-11-08", on), "overdue")
		self.assertEqual(reminders.display_status("In Progress", "2026-11-16", on), "due_soon")
		self.assertEqual(reminders.display_status("In Progress", "2026-11-17", on), "in_progress")
		self.assertEqual(reminders.display_status("Planned", None, on), "planned")

	def test_activity_reminders_once_per_milestone(self):
		doc = fx.plan(
			YEAR,
			activities=[
				{"activity": "Due soon", "responsible": self.owner, "due_date": add_days(today(), 5)},
				{"activity": "Late", "responsible": self.owner, "due_date": add_days(today(), -1)},
				{"activity": "Far", "responsible": self.owner, "due_date": add_days(today(), 30)},
				{
					"activity": "Done",
					"responsible": self.owner,
					"due_date": add_days(today(), -3),
					"status": "Completed",
				},
			],
		)
		reminders.run_daily()
		self.assertEqual(_sent("IC_PLAN_ACTIVITY_DUE"), 0)  # kế hoạch Nháp không nhắc
		fx.approve(doc, fx.user("R13", prefix="remind"))
		reminders.run_daily()
		reminders.run_daily()  # chạy lại không gửi trùng
		self.assertEqual(_sent("IC_PLAN_ACTIVITY_DUE", self.owner_user), 1)
		self.assertEqual(_sent("IC_PLAN_ACTIVITY_OVERDUE", self.owner_user), 1)
		self.assertEqual(_sent("IC_PLAN_ACTIVITY_DUE", self.r01), 1)  # R01 nhận theo Rule
		# hoạt động "sắp tới hạn" sang quá hạn → nhắc mốc thứ hai đúng một lần
		reminders.run_daily(on=add_days(today(), 6))
		self.assertEqual(_sent("IC_PLAN_ACTIVITY_OVERDUE", self.owner_user), 2)
		self.assertEqual(reminders.attention_count(), 1)

	@bru("BRU-ICP-005")
	def test_document_review_flagged_and_r01_notified_once(self):
		near = fx.procedure("RM-01", issued_on=add_days(today(), -300), review_due=add_days(today(), 20))
		fx.procedure("RM-02", issued_on=add_days(today(), -10), review_due=add_days(today(), 200))
		result = reminders.run_daily()
		reminders.run_daily()
		self.assertEqual(result["documents"], 1)
		self.assertEqual(frappe.db.get_value("IC Procedure Document", near.name, "status"), "Review Needed")
		self.assertEqual(_sent("IC_DOCUMENT_REVIEW_DUE", self.r01), 1)
		self.assertEqual(annual_plan.badges(self.r01), {"ke-hoach": 1})

	def test_resolution_reminders_stop_when_done(self):
		doc = fx.meeting(
			[
				("Overdue item", self.owner, add_days(today(), -2)),
				("Closed item", self.owner, add_days(today(), -2)),
			],
			submit=True,
		)
		doc.reload()
		todo = frappe.get_doc("ToDo", doc.resolutions[1].todo)
		todo.status = "Closed"
		todo.save(ignore_permissions=True)
		reminders.run_daily()
		self.assertEqual(_sent("IC_RESOLUTION_OVERDUE", self.owner_user), 1)
