"""Lịch quan trắc nước thải theo kỳ lịch và nhắc đến hạn/quá hạn (FEAT-095; FR-M15-09, .1; BRU-ENV-006; AC-095-05, 06;
A-153 W3, W8)."""

from unittest.mock import patch

import frappe

from tracecore.environmental_hygiene import wastewater_schedule as schedule
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru

FULL = {"pH": 7.1, "COD": 48, "Coliforms": 3000, "Salmonella": "KPH"}
NO_SALMONELLA = {"pH": 7.1, "COD": 48, "Coliforms": 3000}


class ScheduleCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("Wastewater Point")
		self.owner = make_user("ww-sched@example.com", ["TC R11"])
		self.point = ef.make_point(user=self.owner).name
		ef.make_permit("T-LICH", rows=ef.rows_for(self.point))

	def cells(self, point=None, on="2026-11-12", year=2026):
		row = next(r for r in schedule.grid(year, on=on) if r["point"] == (point or self.point))
		return [cell["status"] for cell in row["periods"]], row


class TestPeriods(IsolatedTestCase):
	def test_periods_follow_calendar_blocks(self):
		self.assertEqual(
			[(str(p["start"]), str(p["end"])) for p in schedule.periods(6, 2026)],
			[("2026-01-01", "2026-06-30"), ("2026-07-01", "2026-12-31")],
		)
		self.assertEqual(len(schedule.periods(3, 2026)), 4)
		self.assertEqual(str(schedule.period_of("2026-11-12", 3)["start"]), "2026-10-01")
		self.assertTrue(schedule.period_of("2026-11-12", 3)["label"].endswith("4/2026"))
		self.assertTrue(schedule.period_of("2026-02-01", 12)["label"].endswith("2026"))


class TestGrid(ScheduleCase):
	@bru("BRU-ENV-006")
	def test_statuses_done_over_missing_due_future(self):
		"""AC-095-05."""
		ef.make_monitoring(self.point, FULL, sampled_on="2026-03-18")
		ef.make_monitoring(self.point, {"pH": 7, "COD": 40, "Salmonella": "KPH"}, sampled_on="2026-09-22")
		statuses, row = self.cells()
		self.assertEqual(statuses, ["done", "over", "miss", "due"])
		self.assertEqual(row["frequency"], 3)
		self.assertIn("Coliforms", row["periods"][2]["missing"])
		self.assertEqual(self.cells(on="2027-01-05")[0][3], "over")
		self.assertEqual(self.cells(year=2027, on="2026-11-12")[0], ["future"] * 4)

	@bru("BRU-ENV-006")
	def test_longer_frequency_parameter_is_required_at_the_end_of_its_own_period(self):
		ef.make_monitoring(self.point, NO_SALMONELLA, sampled_on="2026-03-18")
		ef.make_monitoring(self.point, NO_SALMONELLA, sampled_on="2026-06-10")
		ef.make_monitoring(self.point, NO_SALMONELLA, sampled_on="2026-08-10")
		statuses, row = self.cells()
		self.assertEqual(statuses[:3], ["done", "miss", "done"])
		self.assertEqual(row["periods"][1]["missing"], ["Salmonella"])

	def test_failed_round_marks_the_period(self):
		ef.make_monitoring(self.point, {**FULL, "Coliforms": 9300}, sampled_on="2026-09-22")
		statuses, row = self.cells()
		self.assertEqual(statuses[2], "fail")
		self.assertTrue(row["awaiting_remonitor"])

	def test_auto_only_point_is_not_applicable_and_period_rate(self):
		auto = ef.make_point("T Trạm tự động", "Outlet").name
		ef.make_permit(
			"T-AUTO",
			rows=[
				{
					"wastewater_point": auto,
					"parameter": "pH",
					"min_value": 6,
					"max_value": 9,
					"auto_monitored": 1,
				}
			],
		)
		self.assertEqual(self.cells(point=auto)[0], ["na"])
		ef.make_monitoring(self.point, FULL, sampled_on="2026-03-18")
		self.assertEqual(schedule.on_time_rate(2026, on="2026-11-12"), (1, 3))


class TestReminders(ScheduleCase):
	def setUp(self):
		super().setUp()
		ef.make_monitoring(self.point, FULL, sampled_on="2026-09-10")  # quý 3 đủ: chỉ còn quý 4 cần nhắc

	def remind(self, on):
		with patch("tracecore.core.notification.emit") as emit:
			schedule.run_daily(on)
		return [(call.args[0], call.kwargs.get("users")) for call in emit.call_args_list]

	def test_due_reminder_goes_to_owner_once_per_point_and_period(self):
		"""AC-095-06."""
		self.assertEqual(self.remind("2026-12-01"), [])
		calls = self.remind("2026-12-20")
		self.assertEqual([code for code, _users in calls], [schedule.DUE_EVENT])
		self.assertIn(self.owner, calls[0][1])
		self.assertEqual(self.remind("2026-12-21"), [])

	def test_overdue_reminder_once_after_the_period(self):
		self.remind("2026-12-20")
		self.assertEqual([code for code, _ in self.remind("2027-01-02")], [schedule.OVERDUE_EVENT])
		self.assertEqual(self.remind("2027-01-03"), [])

	def test_done_period_gets_no_reminder_and_lead_days_come_from_settings(self):
		frappe.db.set_single_value("IC Program Settings", "wastewater_due_days", 40)
		self.assertEqual([code for code, _ in self.remind("2026-12-01")], [schedule.DUE_EVENT])
		ef.make_monitoring(self.point, FULL, sampled_on="2026-10-20")
		frappe.db.set_value("Wastewater Point", self.point, "overdue_notified_period", None)
		self.assertEqual(self.remind("2027-01-02"), [])
