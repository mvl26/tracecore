"""Phân bổ theo ngày và khóa kỳ của Cost Entry (FEAT-044; FR-M7-01.2, FR-M7-02.2; UC-27 E3; A-47 C5, C6)."""

import frappe
from frappe.utils import add_days, formatdate, getdate

from tracecore.costing import entry as costing
from tracecore.tests.factories import cost_allocation, make_cost_entry, make_equipment
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SETTINGS = "Cost Settings"
JAN = "2026-01-01"
JAN_END = "2026-01-31"


class ServiceCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_equipment()
		self.other = make_equipment(serial="SN-002")

	def entry(self, amount, period_from=JAN, period_to=JAN_END, percents=(100,), **kwargs):
		machines = [self.machine, self.other][: len(percents)]
		rows = [cost_allocation(m.name, p) for m, p in zip(machines, percents, strict=True)]
		return make_cost_entry(
			amount=amount, period_from=period_from, period_to=period_to, allocations=rows, **kwargs
		)


class TestAmountInRange(ServiceCase):
	def test_whole_period_is_the_whole_amount(self):
		doc = self.entry(3100000)
		self.assertEqual(costing.amount_in(doc, JAN, JAN_END), 3100000)
		self.assertEqual(costing.amount_in(doc, "2025-12-01", "2026-02-28"), 3100000)

	def test_part_of_the_period_is_prorated_by_day(self):  # FR-M7-01.2
		doc = self.entry(3100000)
		self.assertEqual(costing.amount_in(doc, "2026-01-01", "2026-01-10"), 1000000)
		self.assertEqual(costing.amount_in(doc, "2026-01-11", "2026-01-31"), 2100000)

	def test_no_overlap_is_zero(self):
		doc = self.entry(3100000)
		self.assertEqual(costing.amount_in(doc, "2026-02-01", "2026-02-28"), 0)
		self.assertEqual(costing.amount_in(doc, "2025-12-01", "2025-12-31"), 0)

	def test_days_add_up_to_the_exact_amount_without_losing_a_dong(self):
		doc = self.entry(100000, "2026-04-01", "2026-04-30")  # 100.000 / 30 không chia hết
		days = [getdate("2026-04-01")]
		while days[-1] < getdate("2026-04-30"):
			days.append(add_days(days[-1], 1))
		self.assertEqual(sum(costing.amount_in(doc, d, d) for d in days), 100000)
		self.assertEqual(costing.amount_in(doc, "2026-04-01", "2026-04-15"), 15 * 3333)
		self.assertEqual(costing.amount_in(doc, "2026-04-30", "2026-04-30"), 3333 + 10)

	def test_one_day_entry(self):
		doc = self.entry(500000, "2026-01-05", "2026-01-05")
		self.assertEqual(costing.amount_in(doc, JAN, JAN_END), 500000)
		self.assertEqual(costing.amount_in(doc, "2026-01-06", JAN_END), 0)

	def test_range_end_before_start_is_zero(self):
		doc = self.entry(3100000)
		self.assertEqual(costing.amount_in(doc, JAN_END, JAN), 0)


class TestSplitByTarget(ServiceCase):
	def test_split_by_percent(self):
		doc = self.entry(1000000, percents=(60, 40))
		self.assertEqual(
			costing.split(doc, JAN, JAN_END),
			{("Equipment", self.machine.name): 600000, ("Equipment", self.other.name): 400000},
		)

	def test_split_never_loses_a_dong(self):
		third = make_equipment(serial="SN-003")
		rows = [
			cost_allocation(self.machine.name, 33.33),
			cost_allocation(self.other.name, 33.33),
			cost_allocation(third.name, 33.34),
		]
		doc = make_cost_entry(amount=1000001, period_from=JAN, period_to=JAN_END, allocations=rows)
		for date_from, date_to in ((JAN, JAN_END), (JAN, "2026-01-10"), ("2026-01-20", JAN_END)):
			parts = costing.split(doc, date_from, date_to)
			self.assertEqual(sum(parts.values()), costing.amount_in(doc, date_from, date_to))

	def test_allocated_to_one_target(self):
		doc = self.entry(1000000, percents=(60, 40))
		self.assertEqual(costing.allocated_to(doc, "Equipment", self.other.name, JAN, JAN_END), 400000)
		self.assertEqual(costing.allocated_to(doc, "Equipment", "TB-9999", JAN, JAN_END), 0)


class TestPeriodLock(ServiceCase):
	def lock(self, date):
		frappe.db.set_single_value(SETTINGS, "locked_until", date)

	def test_entry_in_a_locked_period_cannot_be_created(self):  # UC-27 E3
		self.lock("2026-01-31")
		with self.assertRaises(frappe.ValidationError):
			self.entry(1000000, "2026-01-15", "2026-01-31")
		with self.assertRaises(frappe.ValidationError):
			self.entry(1000000, "2026-01-31", "2026-02-10")

	def test_entry_after_the_lock_date_is_allowed(self):
		self.lock("2026-01-31")
		self.assertEqual(self.entry(1000000, "2026-02-01", "2026-02-28").docstatus, 0)

	def test_no_lock_date_means_nothing_is_locked(self):
		self.assertEqual(self.entry(1000000, "2020-01-01", "2020-01-31").docstatus, 0)

	def test_draft_cannot_be_submitted_once_its_period_is_locked(self):
		doc = self.entry(1000000, "2026-01-01", JAN_END)
		self.lock("2026-01-31")
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		self.assertEqual(frappe.db.get_value("Cost Entry", doc.name, "docstatus"), 0)

	def test_submitted_entry_cannot_be_cancelled_once_its_period_is_locked(self):
		doc = self.entry(1000000, "2026-01-01", JAN_END)
		doc.submit()
		self.lock("2026-01-31")
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()
		self.assertEqual(frappe.db.get_value("Cost Entry", doc.name, "docstatus"), 1)

	def test_moving_a_draft_into_a_locked_period_is_blocked(self):
		doc = self.entry(1000000, "2026-02-01", "2026-02-28")
		self.lock("2026-01-31")
		doc.period_from = "2026-01-20"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_moving_a_draft_out_of_a_locked_period_is_blocked(self):
		doc = self.entry(1000000, "2026-01-10", "2026-01-31")
		self.lock("2026-01-31")
		doc.period_from = "2026-02-01"
		doc.period_to = "2026-02-28"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_opening_the_period_allows_work_again(self):
		doc = self.entry(1000000, "2026-01-01", JAN_END)
		self.lock("2026-01-31")
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		self.lock("2025-12-31")
		doc.reload()  # lần ghi sổ hỏng để lại mốc thời gian mới trong bộ nhớ
		doc.submit()
		self.assertEqual(frappe.db.get_value("Cost Entry", doc.name, "docstatus"), 1)

	def test_error_tells_the_period_is_locked(self):
		self.lock("2026-01-31")
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.entry(1000000, "2026-01-15", "2026-01-31")
		self.assertIn(formatdate("2026-01-31"), str(ctx.exception))
