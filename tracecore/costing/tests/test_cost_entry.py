"""Cost Entry (FEAT-044; FR-M7-01 .1-.4, FR-M7-02 .1; UC-27 bước 1-4, E1, E2; architecture A-47 C1, C2, C4, C7, C12)."""

import frappe
from frappe.utils import add_days, get_first_day, get_last_day, today

from tracecore.tests.factories import (
	cost_allocation,
	make_cost_entry,
	make_equipment,
	make_program,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Cost Entry"


class CostEntryCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.machine = make_equipment()

	def entry(self, percents=(100,), **kwargs):
		"""Cost Entry Nháp; mỗi tỷ lệ trong `percents` gắn cho một máy riêng (đối tượng không được trùng trong một khoản)."""
		others = [make_equipment(serial="SN-" + frappe.generate_hash(length=8)) for _i in percents[1:]]
		machines = [self.machine, *others]
		rows = [cost_allocation(m.name, percent) for m, percent in zip(machines, percents, strict=True)]
		return make_cost_entry(allocations=rows, **kwargs)


class TestCostEntryData(CostEntryCase):
	def test_entry_is_named_cp(self):  # A-47 C1
		self.assertRegex(self.entry().name, r"^CP-\d{4}-\d{5}$")

	def test_category_is_required(self):
		with self.assertRaises(frappe.MandatoryError):
			self.entry(category=None)

	def test_unknown_or_inactive_category_is_rejected(self):
		with self.assertRaises(frappe.LinkValidationError):
			self.entry(category="Không có")
		frappe.db.set_value("Cost Category", "Steam Cost", "is_active", 0)
		with self.assertRaises(frappe.ValidationError):
			self.entry(category="Steam Cost")

	def test_negative_amount_is_blocked(self):  # FR-M7-01.4, UC-27 E1
		with self.assertRaises(frappe.ValidationError):
			self.entry(amount=-1)

	def test_zero_amount_is_allowed(self):
		self.assertEqual(self.entry(amount=0).amount, 0)

	def test_period_end_cannot_be_before_start(self):
		with self.assertRaises(frappe.ValidationError):
			self.entry(period_from=today(), period_to=add_days(today(), -1))

	def test_one_day_period_is_allowed(self):
		self.assertEqual(self.entry(period_from=today(), period_to=today()).period_to, today())

	def test_meter_source_computes_quantity_from_readings(self):  # FR-M7-01.3
		doc = self.entry(source="Meter", opening_reading=1200.5, closing_reading=1500, unit="kWh")
		self.assertEqual(doc.quantity, 299.5)

	def test_meter_reading_cannot_decrease_or_be_negative(self):  # FR-M7-01.3, .4
		for opening, closing in ((500, 400), (-1, 10), (0, -5)):
			with self.assertRaises(frappe.ValidationError, msg=(opening, closing)):
				self.entry(source="Meter", opening_reading=opening, closing_reading=closing, unit="kWh")

	def test_meter_needs_both_readings(self):
		with self.assertRaises(frappe.ValidationError):
			self.entry(source="Meter", opening_reading=10, closing_reading=None, unit="kWh")

	def test_other_sources_ignore_readings(self):
		doc = self.entry(source="Invoice", opening_reading=10, closing_reading=40)
		self.assertEqual(doc.quantity, 0)

	def test_entry_cannot_be_deleted(self):
		doc = self.entry()
		with self.assertRaises(frappe.ValidationError):
			doc.delete()
		self.assertTrue(frappe.db.exists(DOCTYPE, doc.name))


class TestCostAllocation(CostEntryCase):
	def test_total_other_than_100_is_blocked(self):  # FR-M7-02.1, UC-27 E2
		for percents in ((99,), (101,), (50, 49), (60, 41), (33, 33, 33)):
			with self.assertRaises(frappe.ValidationError, msg=percents):
				self.entry(percents)

	def test_total_exactly_100_is_accepted(self):
		for percents in ((100,), (60, 40), (33.33, 33.33, 33.34)):
			doc = self.entry(percents)
			self.assertEqual(len(doc.allocations), len(percents))

	def test_percent_must_be_positive_and_at_most_100(self):
		for percent in (0, -10, 100.5):
			with self.assertRaises(frappe.ValidationError, msg=percent):
				make_cost_entry(allocations=[cost_allocation(self.machine.name, percent)])

	def test_same_target_twice_is_blocked(self):
		rows = [cost_allocation(self.machine.name, 50), cost_allocation(self.machine.name, 50)]
		with self.assertRaises(frappe.ValidationError):
			make_cost_entry(allocations=rows)

	def test_target_must_exist_for_its_type(self):
		with self.assertRaises(frappe.LinkValidationError):
			make_cost_entry(allocations=[cost_allocation("TB-9999", 100)])

	def test_zone_and_program_can_be_targets(self):  # FR-M7-02: thiết bị, khu hoặc chương trình
		program = make_program(self.machine.name)
		rows = [
			cost_allocation(self.machine.name, 50),
			cost_allocation("ZONE-CLEAN", 30, "Zone Station"),
			cost_allocation(program.name, 20, "Process Program"),
		]
		doc = make_cost_entry(allocations=rows)
		self.assertEqual(
			[r.target_type for r in doc.allocations], ["Equipment", "Zone Station", "Process Program"]
		)

	def test_target_type_is_required_with_target(self):
		with self.assertRaises(frappe.ValidationError):
			make_cost_entry(allocations=[{"target_type": "", "target": self.machine.name, "percent": 100}])

	def test_draft_without_allocations_can_be_saved(self):
		self.assertEqual(make_cost_entry().docstatus, 0)

	def test_submit_needs_allocations(self):  # UC-27 bước 3-5
		doc = make_cost_entry()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 0)

	def test_submit_then_cancel(self):  # C2
		doc = self.entry((60, 40))
		doc.submit()
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 1)
		doc.cancel()
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 2)

	def test_submitted_entry_keeps_allocations_read_only(self):
		doc = self.entry()
		doc.submit()
		doc.reload()
		doc.allocations[0].percent = 50
		with self.assertRaises(frappe.ValidationError):
			doc.save()


class TestCostEntryPermissions(CostEntryCase):
	def test_permissions_follow_a47_c12(self):
		expected = {
			"TC R09": {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 0},
			"TC R01": {"read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 1},
			"TC R02": {"read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R10": {"read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R03": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R04": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R05": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
		}
		for role, flags in expected.items():
			user = make_user(f"ce-{role.split()[-1].lower()}@example.com", [role])
			for ptype, allowed in flags.items():
				self.assertEqual(
					int(bool(frappe.has_permission(DOCTYPE, ptype, user=user))),
					allowed,
					msg=f"{role} {ptype}",
				)

	def test_r09_creates_and_submits_an_entry(self):
		user = make_user("ce-flow@example.com", ["TC R09"])
		frappe.set_user(user)
		try:
			doc = make_cost_entry(
				allocations=[cost_allocation(self.machine.name, 100)],
				period_from=get_first_day(today()),
				period_to=get_last_day(today()),
			)
			doc.submit()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 1)
