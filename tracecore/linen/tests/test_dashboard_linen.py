"""Khối Đồ vải của dashboard SCR-32 (ux-foundations DASH-02)."""

from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from tracecore.linen import analysis, laundry
from tracecore.linen.tests.test_machine_usage import UsageCase
from tracecore.tests.factories import (
	linen_line,
	make_department,
	make_linen_collection,
	make_linen_issue,
	make_linen_type,
)

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


def today_range():
	day = getdate(today())
	start = datetime(day.year, day.month, day.day)
	return start, start + timedelta(days=1)


class TestLinenDashboard(UsageCase):
	def block(self, **filters):
		return analysis.dashboard(*today_range(), **filters)

	def test_kg_collected_and_returned_by_department(self):
		ward = make_department("Khoa Dashboard Do Vai")
		other = make_department("Khoa Dashboard Khac")
		sheet = make_linen_type(std_weight_kg=0.5).name
		make_linen_collection([linen_line(sheet, 20, 10)], department=ward, submit=True)
		make_linen_issue([linen_line(sheet, 10, 5)], department=ward, kind="Return", submit=True)
		make_linen_collection([linen_line(sheet, 4, 2)], department=other, submit=True)
		block = self.block(department=ward)
		self.assertEqual(block["collected_kg"], 10)
		self.assertEqual(block["returned_kg"], 5)
		self.assertEqual(
			[
				(row["department"], row["collected_kg"], row["returned_kg"], row["variance_kg"])
				for row in block["by_department"]
			],
			[(ward, 10, 5, 5)],
		)
		self.assertEqual(self.block()["collected_kg"], 12)

	def test_cost_per_kg_counts_recorded_batches_in_the_period(self):
		one = self.run_batch(kg=10)
		two = self.run_batch(kg=20)
		block = self.block()
		self.assertEqual(block["cost_per_kg"], round((one.cost_total + two.cost_total) / 30))
		moved = now_datetime() - timedelta(days=3)
		frappe.db.set_value("Laundry Batch", two.name, "ended_at", moved)
		self.assertEqual(self.block()["cost_per_kg"], round(one.cost_total / 10))

	def test_running_batches_are_counted_whatever_the_period(self):
		laundry.start(
			self.station,
			self.operator,
			[{"kg": 5, "contaminated": 1}],
			equipment=self.washer.name,
			program=self.normal.name,
		)
		self.assertEqual(self.block()["running"], 1)

	def test_failed_batch_stays_until_it_is_rewashed(self):
		doc = laundry.start(
			self.station,
			self.operator,
			[{"kg": 5, "contaminated": 1}],
			equipment=self.washer.name,
			program=self.normal.name,
		)
		failed = laundry.complete(
			doc.name,
			dryer=self.dryer.name,
			dry_program=self.dry.name,
			clean_ok=0,
			dry_ok=1,
			deviation_reason="Lý do",
		)
		self.assertEqual(self.block()["failed_waiting"], [failed.name])
		laundry.start(
			self.station,
			self.operator,
			[{"kg": 5, "contaminated": 1}],
			equipment=self.washer.name,
			program=self.normal.name,
			redo_of=failed.name,
		)
		self.assertEqual(self.block()["failed_waiting"], [])

	def test_batch_over_the_deviation_limit_needs_action(self):
		self.run_batch(actual_kwh=50)
		self.run_batch()
		self.assertEqual(len(self.block()["over_deviation"]), 1)

	def test_department_issued_over_its_quota_needs_action(self):
		ward = make_department("Khoa Dashboard Dinh Muc")
		sheet = make_linen_type(
			std_weight_kg=0.5, quotas=[{"department": ward, "min_qty": 0, "max_qty": 5}]
		).name
		make_linen_issue([linen_line(sheet, 10, 5)], department=ward, kind="Return", submit=True)
		self.assertEqual(self.block()["over_quota_departments"], [ward])

	def test_machine_table_shows_washer_and_dryer_and_follows_the_machine_filter(self):
		self.run_batch(kg=10)
		rows = {row["machine"]: row for row in self.block()["machines"]}
		self.assertEqual(set(rows), {self.washer.name, self.dryer.name})
		self.assertEqual((rows[self.washer.name]["batches"], rows[self.washer.name]["weight_kg"]), (1, 10))
		only = self.block(equipment=self.dryer.name)["machines"]
		self.assertEqual([row["machine"] for row in only], [self.dryer.name])

	def test_nothing_recorded_gives_zero_not_an_error(self):
		yesterday = add_days(getdate(today()), -400)
		start = datetime(yesterday.year, yesterday.month, yesterday.day)
		block = analysis.dashboard(start, start + timedelta(days=1))
		self.assertEqual((block["collected_kg"], block["returned_kg"], block["cost_per_kg"]), (0, 0, 0))
		self.assertEqual((block["by_department"], block["machines"]), ([], []))
