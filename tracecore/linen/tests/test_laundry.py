"""Laundry Batch: tạo lô giặt, chặn nghiệp vụ, hoàn tất (FEAT-034; FR-M3-03, .1-.4; UC-17, A1, A2, E1-E3;
BRU-LIN-001, BRU-LIN-003, BRU-EQP-002; A-50 D1-D10)."""

from unittest.mock import patch

import frappe

from tracecore.core.errors import BlockedError
from tracecore.linen import laundry
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DISINFECTANT = "HC-F34-DIS"
DETERGENT = "HC-F34-DET"


def load(kg, contaminated=1):
	return {"kg": kg, "contaminated": contaminated}


class LaundryCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.station = factories.make_linen_station()
		self.operator = factories.make_employee(first_name="Giặt").name
		self.washer = factories.make_equipment(
			name="Máy giặt test",
			equipment_type="Laundry Washer",
			serial="LW-" + frappe.generate_hash(length=8),
			zone_in="ZONE-DIRTY",
			zone_out=None,
			capacity_kg=30,
		)
		self.dryer = factories.make_equipment(
			name="Máy sấy test",
			equipment_type="Dryer",
			serial="DR-" + frappe.generate_hash(length=8),
			zone_in="ZONE-DIRTY",
			zone_out=None,
		)
		factories.make_item(DISINFECTANT, "Chemical")
		frappe.db.set_value("Item", DISINFECTANT, "tc_is_disinfectant", 1)
		factories.make_item(DETERGENT, "Chemical")
		self.hot = self.program(temperature=75)
		self.cold = self.program(temperature=40)

	def program(self, **kwargs):
		code = "MG-" + frappe.generate_hash(length=6).upper()
		return factories.make_program(self.washer.name, code=code, minutes=45, kwh=2, water=100, **kwargs)

	def start(self, **kwargs):
		values = {
			"station": self.station,
			"operator": self.operator,
			"equipment": self.washer.name,
			"program": self.hot.name,
			"loads": [load(10)],
		}
		return laundry.start(**{**values, **kwargs})

	def blocked(self, code, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			self.start(**kwargs)
		self.assertEqual(caught.exception.block.code, code)
		return caught.exception.block


class TestStart(LaundryCase):
	@bru("BRU-LIN-001")
	def test_creates_a_running_batch_named_lg(self):  # FR-M3-03, A-50 D2
		doc = self.start(loads=[load(10), load(5)])
		self.assertRegex(doc.name, r"^LG-\d{6}-\d{2}$")
		self.assertEqual((doc.status, doc.docstatus, doc.batch_type), ("Running", 0, "In-house"))
		self.assertEqual((doc.weight_kg, doc.contaminated), (15, 1))
		self.assertEqual(
			(doc.equipment, doc.program, doc.operator), (self.washer.name, self.hot.name, self.operator)
		)
		self.assertTrue(doc.started_at)

	@bru("BRU-LIN-003")
	def test_mixed_contaminated_and_clean_loads_are_refused(self):  # FR-M3-03.1, UC-17 E1
		self.blocked("LAUNDRY_MIXED", loads=[load(10, 1), load(5, 0)])

	def test_all_clean_loads_make_a_clean_batch(self):
		doc = self.start(loads=[load(10, 0), load(5, 0)])
		self.assertEqual(doc.contaminated, 0)

	@bru("BRU-LIN-001")
	def test_weight_must_be_a_positive_number(self):
		for loads in (
			None,
			[],
			[load(0)],
			[load(-3)],
			[{"kg": "x", "contaminated": 1}],
			[{"contaminated": 1}],
		):
			self.blocked("LAUNDRY_WEIGHT_INVALID", loads=loads)

	@bru("BRU-LIN-001")
	def test_weight_over_machine_capacity_is_refused(self):  # FR-M3-03.3
		self.blocked("LAUNDRY_OVER_CAPACITY", loads=[load(20), load(10.5)])
		self.assertEqual(self.start(loads=[load(30)]).weight_kg, 30)

	def test_machine_without_capacity_is_not_limited(self):
		frappe.db.set_value("Equipment", self.washer.name, "capacity_kg", 0)
		self.assertEqual(self.start(loads=[load(500)]).weight_kg, 500)

	@bru("BRU-EQP-002")
	def test_locked_washer_cannot_be_chosen(self):  # FR-M3-03.4, UC-17 E3
		frappe.db.set_value("Equipment", self.washer.name, "status", "Locked")
		self.blocked("EQUIPMENT_NOT_READY")

	def test_unknown_or_wrong_type_of_machine_is_refused(self):
		self.blocked("LAUNDRY_EQUIPMENT_INVALID", equipment="TB-9999")
		self.blocked("LAUNDRY_EQUIPMENT_INVALID", equipment=self.dryer.name)
		self.blocked("LAUNDRY_EQUIPMENT_INVALID", equipment=None)

	def test_program_must_belong_to_the_machine_and_be_active(self):
		other = factories.make_equipment(
			equipment_type="Laundry Washer", serial="LW-" + frappe.generate_hash(length=8), zone_out=None
		)
		foreign = factories.make_program(other.name, code="MG-OTHER", minutes=30, kwh=1, water=50)
		self.blocked("LAUNDRY_PROGRAM_INVALID", program=foreign.name)
		self.blocked("LAUNDRY_PROGRAM_INVALID", program=None)
		frappe.db.set_value("Process Program", self.hot.name, "is_active", 0)
		self.blocked("LAUNDRY_PROGRAM_INVALID")

	@bru("BRU-LIN-003")
	def test_contaminated_batch_below_71c_needs_a_disinfectant(self):  # FR-M3-03.2, UC-17 E2
		self.blocked("LAUNDRY_TEMP_TOO_LOW", program=self.cold.name)
		self.blocked(
			"LAUNDRY_TEMP_TOO_LOW", program=self.cold.name, chemicals=[{"item": DETERGENT, "qty": 1}]
		)

	@bru("BRU-LIN-003")
	def test_disinfectant_chosen_by_the_operator_allows_a_cool_program(self):
		doc = self.start(program=self.cold.name, chemicals=[{"item": DISINFECTANT, "qty": 0.5}])
		self.assertEqual([(row.item, row.qty) for row in doc.chemicals], [(DISINFECTANT, 0.5)])

	@bru("BRU-LIN-003")
	def test_disinfectant_in_the_program_norm_allows_a_cool_program(self):
		program = self.program(temperature=40, consumables=[{"item": DISINFECTANT, "qty_per_kg": 0.1}])
		self.assertEqual(self.start(program=program.name).program, program.name)

	@bru("BRU-LIN-003")
	def test_71c_is_enough_and_clean_linen_has_no_temperature_rule(self):
		self.assertTrue(self.start(program=self.program(temperature=71).name))
		self.assertTrue(self.start(program=self.cold.name, loads=[load(8, 0)]))

	def test_unknown_chemical_is_refused(self):
		self.blocked("LAUNDRY_CHEMICAL_INVALID", chemicals=[{"item": "KHONG-CO", "qty": 1}])

	@bru("BRU-LIN-001")
	def test_outsourced_batch_needs_vendor_and_price_and_no_machine(self):  # UC-17 A2
		self.blocked("LAUNDRY_VENDOR_REQUIRED", batch_type="Outsourced", equipment=None, program=None)
		self.blocked(
			"LAUNDRY_VENDOR_REQUIRED",
			batch_type="Outsourced",
			equipment=None,
			program=None,
			vendor="Giặt ABC",
		)
		doc = self.start(
			batch_type="Outsourced", equipment=None, program=None, vendor="Giặt ABC", price_per_kg=12000
		)
		self.assertEqual((doc.batch_type, doc.vendor, doc.price_per_kg), ("Outsourced", "Giặt ABC", 12000))
		self.assertFalse(doc.equipment)

	@bru("BRU-LIN-001")
	def test_redo_links_to_a_failed_batch_only(self):  # UC-17 A1
		first = self.start()
		self.blocked("LAUNDRY_REDO_INVALID", redo_of=first.name)
		self.blocked("LAUNDRY_REDO_INVALID", redo_of="LG-000000-99")
		laundry.complete(
			first.name, dryer=self.dryer.name, dry_temp_c=70, dry_minutes=30, clean_ok=0, dry_ok=1
		)
		self.assertEqual(self.start(redo_of=first.name).redo_of, first.name)


class TestComplete(LaundryCase):
	def finish(self, doc, **kwargs):
		values = {
			"dryer": self.dryer.name,
			"dry_temp_c": 70,
			"dry_minutes": 40,
			"clean_ok": 1,
			"dry_ok": 1,
		}
		return laundry.complete(doc.name, **{**values, **kwargs})

	@bru("BRU-LIN-001")
	def test_clean_and_dry_makes_the_batch_pass_and_submits_it(self):  # FR-M3-03, UC-17 bước 4-6
		doc = self.finish(self.start())
		self.assertEqual((doc.status, doc.docstatus), ("Passed", 1))
		self.assertEqual((doc.dryer, doc.dry_temp_c, doc.dry_minutes), (self.dryer.name, 70, 40))
		self.assertTrue(doc.ended_at)

	@bru("BRU-LIN-001")
	def test_not_clean_or_not_dry_makes_the_batch_fail(self):
		self.assertEqual(self.finish(self.start(), clean_ok=0).status, "Failed")
		self.assertEqual(self.finish(self.start(), dry_ok=0).status, "Failed")

	def test_result_checks_are_required(self):
		doc = self.start()
		for field in ("clean_ok", "dry_ok"):
			with self.assertRaises(BlockedError) as caught:
				self.finish(doc, **{field: None})
			self.assertEqual(caught.exception.block.code, "LAUNDRY_RESULT_REQUIRED")

	@bru("BRU-EQP-002")
	def test_dryer_must_be_a_ready_dryer(self):
		doc = self.start()
		for dryer in (None, self.washer.name, "TB-9999"):
			with self.assertRaises(BlockedError) as caught:
				self.finish(doc, dryer=dryer)
			self.assertEqual(caught.exception.block.code, "LAUNDRY_EQUIPMENT_INVALID")
		frappe.db.set_value("Equipment", self.dryer.name, "status", "Locked")
		with self.assertRaises(BlockedError) as caught:
			self.finish(doc)
		self.assertEqual(caught.exception.block.code, "EQUIPMENT_NOT_READY")

	def test_dry_temperature_and_minutes_must_be_positive(self):
		doc = self.start()
		for field in ("dry_temp_c", "dry_minutes"):
			with self.assertRaises(BlockedError) as caught:
				self.finish(doc, **{field: 0})
			self.assertEqual(caught.exception.block.code, "LAUNDRY_DRY_INVALID")

	def test_a_finished_batch_cannot_be_completed_again(self):
		doc = self.start()
		self.finish(doc)
		with self.assertRaises(BlockedError) as caught:
			self.finish(doc)
		self.assertEqual(caught.exception.block.code, "LAUNDRY_NOT_RUNNING")

	def test_unknown_batch_is_not_found(self):
		with self.assertRaises(BlockedError) as caught:
			laundry.complete(
				"LG-000000-99", dryer=self.dryer.name, dry_temp_c=70, dry_minutes=40, clean_ok=1, dry_ok=1
			)
		self.assertEqual(caught.exception.block.code, "LAUNDRY_NOT_FOUND")

	@bru("BRU-INV-002")
	def test_complete_runs_the_after_complete_hook_with_the_batch_context(self):  # A-50 (c)
		doc = self.start(chemicals=[{"item": DISINFECTANT, "qty": 0.5}])
		with patch("tracecore.linen.laundry.extension.run") as run:
			done = self.finish(doc)
		hook, ctx = run.call_args.args
		self.assertEqual(hook, "tracecore_after_laundry_complete")
		self.assertEqual(ctx["batch"], done.name)
		self.assertEqual(
			(ctx["equipment"], ctx["program"], ctx["kg"], ctx["result"]),
			(self.washer.name, self.hot.name, 10, "Pass"),
		)
		self.assertEqual(ctx["chemicals"], [{"item": DISINFECTANT, "qty": 0.5}])

	def test_failed_batch_runs_the_hook_with_a_fail_result(self):
		doc = self.start()
		with patch("tracecore.linen.laundry.extension.run") as run:
			self.finish(doc, clean_ok=0)
		self.assertEqual(run.call_args.args[1]["result"], "Fail")

	@bru("BRU-LIN-001")
	def test_outsourced_batch_cost_is_kg_times_price_and_has_no_hook_stock(self):  # UC-17 A2
		doc = self.start(
			batch_type="Outsourced",
			equipment=None,
			program=None,
			vendor="Giặt ABC",
			price_per_kg=12000,
			loads=[load(10)],
		)
		with patch("tracecore.linen.laundry.extension.run") as run:
			done = laundry.complete(doc.name, clean_ok=1, dry_ok=1)
		self.assertEqual((done.status, done.cost_total, done.cost_per_kg), ("Passed", 120000, 12000))
		self.assertEqual(run.call_args.args[1]["equipment"], None)
