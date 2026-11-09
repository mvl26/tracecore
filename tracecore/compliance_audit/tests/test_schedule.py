"""Lịch giám sát, độ bao phủ và nhắc việc (FEAT-060 AC-5; FR-M12-03, FR-M12-03.1; UC-43 bước 4–6, E2)."""

import frappe
from frappe.utils import add_days, get_last_day, getdate

from tracecore.compliance_audit import schedule as audit_schedule
from tracecore.compliance_audit.tests.factories import R02, answers, make_observer, make_template
from tracecore.core import notification
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

DOCTYPE = "Audit Schedule"
ALL_PASS = dict.fromkeys(("PNC-01", "PNC-02", "PNC-03", "PNC-04", "PNC-05"), "Pass")
TODAY = getdate()


class ScheduleCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		self.dept_a = factories.make_department("Schedule Ward A")
		self.dept_b = factories.make_department("Schedule Ward B")
		self.template = make_template("T-SCH")
		self.assignee_user = factories.make_user("aud-assignee@example.com", ["TC R11"])
		self.assignee = make_observer(user=self.assignee_user, first_name="Schedule Assignee")
		self.observer = make_observer(first_name="Schedule Observer")
		self.r02 = factories.make_user("aud-sch-r02@example.com", [R02])

	def make_schedule(self, departments=None, **values):
		return frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"audit_template": self.template.name,
				"frequency": "Monthly",
				"target_count": 30,
				"assignee": self.assignee,
				"departments": [{"department": d} for d in (departments or [self.dept_a, self.dept_b])],
				**values,
			}
		).insert()

	def make_session(self, department, submit=True, on=TODAY, **values):
		doc = frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": values.pop("template", self.template.name),
				"department": department,
				"observer": self.observer,
				"audit_date": on,
				"answers": answers(**ALL_PASS),
				**values,
			}
		).insert()
		if submit:
			doc.submit()
		return doc

	def deliveries(self, event, user):
		return frappe.db.count("Notification Delivery", {"event_code": event, "recipient": user, "channel": "In App"})


class TestScheduleRules(ScheduleCase):
	def test_named_by_series_and_follows_template_code(self):
		doc = self.make_schedule()
		self.assertTrue(doc.name.startswith("LGS-"))
		self.assertEqual(doc.template_code, "T-SCH")

	def test_draft_template_rejected(self):
		"""UC-43 E2, BRU-AUD-001: lịch gắn mẫu Nháp bị chặn."""
		self.template = make_template("T-SCH-D", submit=False)
		with self.assertRaises(frappe.ValidationError):
			self.make_schedule()

	def test_invalid_schedule_rejected(self):
		for label, values in {
			"zero target": dict(target_count=0),
			"duplicate department": dict(departments=[self.dept_a, self.dept_a]),
		}.items():
			with self.subTest(label), self.assertRaises(frappe.ValidationError):
				self.make_schedule(**values)

	def test_periods(self):
		day = getdate("2026-11-11")
		self.assertEqual(audit_schedule.period_of("Weekly", day), (getdate("2026-11-09"), getdate("2026-11-15"), "2026-W46"))
		self.assertEqual(audit_schedule.period_of("Monthly", day), (getdate("2026-11-01"), getdate("2026-11-30"), "2026-11"))
		self.assertEqual(audit_schedule.period_of("Quarterly", day), (getdate("2026-10-01"), getdate("2026-12-31"), "2026-Q4"))


class TestCoverage(ScheduleCase):
	def test_coverage_counts_posted_audits_per_department(self):
		"""FR-M12-03.1: mục tiêu 30, khoa mới làm 12 → "12/30"; phiếu Nháp, Hủy, khoa khác không tính."""
		doc = self.make_schedule()
		for _ in range(12):
			self.make_session(self.dept_a)
		self.make_session(self.dept_a, submit=False)
		self.make_session(self.dept_a).cancel()
		self.make_session(self.dept_b)
		rows = {row["department"]: row for row in audit_schedule.coverage(doc.name)}
		self.assertEqual(rows[self.dept_a]["label"], "12/30")
		self.assertEqual((rows[self.dept_b]["done"], rows[self.dept_b]["target"]), (1, 30))
		self.assertEqual(rows[self.dept_a]["period"], audit_schedule.period_of("Monthly", TODAY)[2])

	def test_coverage_counts_new_versions_of_same_code(self):
		from tracecore.compliance_audit import templates

		doc = self.make_schedule()
		self.make_session(self.dept_a)
		v2 = templates.new_version(self.template.name)
		v2.submit()
		self.make_session(self.dept_a, template=v2.name)
		self.assertEqual(audit_schedule.coverage(doc.name)[0]["done"], 2)

	def test_hand_hygiene_counts_opportunities(self):
		hh = make_template(
			"T-SCH-HH", scoring="By Opportunity", audit_type="Hand Hygiene",
			items=(("HH-NOTE", "", "Observation note", 0, 0),),
		)
		self.template = hh
		doc = self.make_schedule()
		opportunities = [{"moment": str(m), "action": "Hand Rub"} for m in (1, 2, 3)]
		frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": hh.name,
				"department": self.dept_a,
				"observer": self.observer,
				"opportunities": opportunities,
				"answers": answers(**{"HH-NOTE": "N/A"}),
			}
		).insert().submit()
		self.assertEqual(audit_schedule.coverage(doc.name)[0]["done"], 3)


class TestScheduleJobs(ScheduleCase):
	def test_due_notice_on_first_day_once(self):
		start, _end, _key = audit_schedule.period_of("Monthly", TODAY)
		self.make_schedule()
		self.make_schedule(active=0, departments=[self.dept_a])
		audit_schedule.run_daily(start)
		audit_schedule.run_daily(start)
		self.assertEqual(self.deliveries("AUDIT_DUE", self.assignee_user), 1)
		audit_schedule.run_daily(add_days(start, 1))
		self.assertEqual(self.deliveries("AUDIT_DUE", self.assignee_user), 1)

	def test_last_week_reminds_departments_below_target_once(self):
		end = get_last_day(TODAY)
		self.make_schedule(target_count=1)
		self.make_session(self.dept_a, on=end)
		audit_schedule.run_daily(add_days(end, -7))
		self.assertEqual(self.deliveries("AUDIT_COVERAGE_LOW", self.assignee_user), 0)
		audit_schedule.run_daily(add_days(end, -3))
		audit_schedule.run_daily(end)
		self.assertEqual(self.deliveries("AUDIT_COVERAGE_LOW", self.assignee_user), 1)
		self.assertEqual(self.deliveries("AUDIT_COVERAGE_LOW", self.r02), 1)
		message = frappe.db.get_value(
			"Notification Delivery", {"event_code": "AUDIT_COVERAGE_LOW", "recipient": self.r02}, "message"
		)
		self.assertIn("Schedule Ward B", message)
		self.assertNotIn("Schedule Ward A", message)

	def test_no_reminder_when_every_department_on_target(self):
		end = get_last_day(TODAY)
		self.make_schedule(target_count=1)
		self.make_session(self.dept_a, on=end)
		self.make_session(self.dept_b, on=end)
		audit_schedule.run_daily(end)
		self.assertEqual(self.deliveries("AUDIT_COVERAGE_LOW", self.r02), 0)
