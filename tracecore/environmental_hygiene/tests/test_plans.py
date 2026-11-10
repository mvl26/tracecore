"""Kế hoạch lấy mẫu: giao việc khi đến kỳ, mẫu trễ hạn, nhắc R01 khi quá 7 ngày (FEAT-070; FR-M15-05, .1; UC-54 E3)."""

from unittest.mock import patch

import frappe

from tracecore.environmental_hygiene import plans, zones
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase


class TestSamplingPlan(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.ward = ef.make_department("KLM Khoa Gây mê")
		frappe.db.delete(zones.DOCTYPE, {"department": self.ward})
		self.zone = ef.make_zone(self.ward, area="Phòng mổ KLM").name
		self.user = make_user("klm-r11@example.com", [ef.R11])
		self.employee = make_employee(first_name="Lấy mẫu", user_id=self.user).name
		ef.make_limit("T-PM-KK", value=10)
		self.plan = frappe.get_doc(
			{
				"doctype": "Sampling Plan",
				"title": "Không khí phòng mổ",
				"sample_type": "Air",
				"limit_code": "T-PM-KK",
				"frequency": "Monthly",
				"assignee": self.employee,
				"zones": [{"environment_zone": self.zone, "next_due": "2026-11-05"}],
			}
		).insert(ignore_permissions=True)

	def todos(self):
		return frappe.get_all(
			"ToDo",
			filters={"reference_type": plans.DOCTYPE, "reference_name": self.plan.name, "status": "Open"},
			fields=["allocated_to", "description"],
		)

	def test_zone_listed_once(self):
		self.plan.append("zones", {"environment_zone": self.zone, "next_due": "2026-12-01"})
		with self.assertRaises(frappe.ValidationError):
			self.plan.save()

	def test_due_plan_assigns_task_once(self):
		with patch("tracecore.core.notification.emit") as emit:
			plans.run_daily("2026-11-04")
			self.assertEqual(self.todos(), [])
			plans.run_daily("2026-11-05")
			plans.run_daily("2026-11-06")
		todos = self.todos()
		self.assertEqual(len(todos), 1)
		self.assertEqual(todos[0].allocated_to, self.user)
		self.assertEqual([call.args[0] for call in emit.call_args_list], [plans.DUE_EVENT])

	def test_overdue_list_and_reminder_after_seven_days(self):
		self.assertEqual([row["zone"] for row in plans.overdue("2026-11-06")], [self.zone])
		self.assertEqual(plans.overdue("2026-11-05"), [])
		with patch("tracecore.core.notification.emit") as emit:
			plans.run_daily("2026-11-11")
			self.assertNotIn(plans.OVERDUE_EVENT, [call.args[0] for call in emit.call_args_list])
			plans.run_daily("2026-11-12")
			plans.run_daily("2026-11-13")
		self.assertEqual([call.args[0] for call in emit.call_args_list].count(plans.OVERDUE_EVENT), 1)

	def test_posted_sample_moves_next_due_and_closes_task(self):
		with patch("tracecore.core.notification.emit"):
			plans.run_daily("2026-11-05")
		ef.make_sample(self.zone, 4, sampled_on="2026-11-06", sampling_plan=self.plan.name)
		row = frappe.get_doc(plans.DOCTYPE, self.plan.name).zones[0]
		self.assertEqual(str(row.next_due), "2026-12-06")
		self.assertEqual(str(row.last_sampled_on), "2026-11-06")
		self.assertEqual(self.todos(), [])

	def test_sample_without_plan_matches_active_plan_of_zone(self):
		ef.make_sample(self.zone, 4, sampled_on="2026-11-06")
		self.assertEqual(str(frappe.get_doc(plans.DOCTYPE, self.plan.name).zones[0].next_due), "2026-12-06")

	def test_resample_does_not_move_plan(self):
		failed = ef.make_sample(self.zone, 24, sampled_on="2026-11-06")
		ef.make_sample(self.zone, 4, sampled_on="2026-11-07", is_resample_of=failed.name)
		self.assertEqual(str(frappe.get_doc(plans.DOCTYPE, self.plan.name).zones[0].next_due), "2026-12-06")

	def test_inactive_plan_is_skipped(self):
		frappe.db.set_value(plans.DOCTYPE, self.plan.name, "active", 0)
		plans.run_daily("2026-11-20")
		self.assertEqual(self.todos(), [])
		self.assertEqual(plans.overdue("2026-11-20"), [])
