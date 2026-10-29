"""Chi phí/kg của lô giặt khi hoàn tất (FEAT-034; FR-M3-04, .2; FR-M7-03; A-50 D8)."""

from unittest.mock import patch

import frappe

from tracecore.costing import from_laundry
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DISINFECTANT = "HC-F34-DIS"
DETERGENT = "HC-F34-DET"


class LaundryCostCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		for code in (DISINFECTANT, DETERGENT):
			factories.make_item(code, "Chemical")
		self.washer = factories.make_equipment(
			equipment_type="Laundry Washer",
			serial="LW-" + frappe.generate_hash(length=8),
			zone_in="ZONE-DIRTY",
			zone_out=None,
		)
		self.program = factories.make_program(
			self.washer.name,
			code="MG-" + frappe.generate_hash(length=6).upper(),
			minutes=45,
			kwh=2,
			water=100,
			consumables=[
				{"item": DISINFECTANT, "qty_per_load": 1, "qty_per_kg": 0.5},
				{"item": DETERGENT, "qty_per_kg": 0.1},
			],
		)

	def rates(self, **omit):
		rows = {
			"Electricity": factories.rate_line(3000, "Electricity"),
			"Tap Water": factories.rate_line(20, "Tap Water"),
			"Labor": factories.rate_line(60000, "Labor"),
			"Disinfectant": factories.rate_line(1000, "Item", DISINFECTANT),
			"Detergent": factories.rate_line(500, "Item", DETERGENT),
		}
		return factories.make_cost_rate_version(
			rates=[row for key, row in rows.items() if key not in omit], submit=True
		)

	def batch(self, **kwargs):
		values = {
			"doctype": "Laundry Batch",
			"batch_type": "In-house",
			"weight_kg": 10,
			"contaminated": 1,
			"equipment": self.washer.name,
			"program": self.program.name,
			**kwargs,
		}
		return frappe.get_doc(values).insert(ignore_permissions=True)

	def ctx(self, batch, **kwargs):
		return {
			"batch": batch.name,
			"batch_type": batch.batch_type,
			"equipment": batch.equipment,
			"program": batch.program,
			"kg": batch.weight_kg,
			"chemicals": [],
			"result": "Pass",
			**kwargs,
		}

	def cost_of(self, batch):
		return frappe.db.get_value(
			"Laundry Batch",
			batch.name,
			[
				"cost_electricity",
				"cost_water",
				"cost_chemical",
				"cost_labor",
				"cost_total",
				"cost_per_kg",
				"cost_note",
			],
			as_dict=True,
		)


@bru("BRU-LIN-001")
class TestLaundryCost(LaundryCostCase):
	def test_hook_is_registered(self):
		self.assertIn(
			"tracecore.costing.from_laundry.on_laundry_complete",
			frappe.get_hooks("tracecore_after_laundry_complete"),
		)

	def test_cost_adds_electricity_water_chemicals_and_labor(self):  # FR-M3-04
		self.rates()
		batch = self.batch()
		from_laundry.on_laundry_complete(self.ctx(batch))
		cost = self.cost_of(batch)
		# điện 2 kWh x 3.000; nước 100 l x 20; hóa chất (1 + 0.5 x 10) x 1.000 + (0.1 x 10) x 500; nhân công 45/60 h x 60.000
		self.assertEqual(
			(cost.cost_electricity, cost.cost_water, cost.cost_chemical, cost.cost_labor),
			(6000, 2000, 6500, 45000),
		)
		self.assertEqual((cost.cost_total, cost.cost_per_kg), (59500, 5950))
		self.assertFalse(cost.cost_note)

	def test_operator_chemical_quantity_replaces_the_norm_in_the_cost(self):
		self.rates()
		batch = self.batch()
		from_laundry.on_laundry_complete(self.ctx(batch, chemicals=[{"item": DISINFECTANT, "qty": 2}]))
		self.assertEqual(self.cost_of(batch).cost_chemical, 2 * 1000 + 1 * 500)

	def test_missing_rate_leaves_that_part_out_and_names_it(self):  # FR-M3-04.2 tinh thần, FR-M7-05.2
		self.rates(Labor=True)
		batch = self.batch()
		from_laundry.on_laundry_complete(self.ctx(batch))
		cost = self.cost_of(batch)
		self.assertEqual((cost.cost_labor, cost.cost_total), (0, 14500))
		self.assertIn("Labor", cost.cost_note)

	def test_without_an_approved_rate_version_the_batch_is_kept_with_a_note(self):
		batch = self.batch()
		from_laundry.on_laundry_complete(self.ctx(batch))
		cost = self.cost_of(batch)
		self.assertEqual((cost.cost_total, cost.cost_per_kg), (0, 0))
		self.assertTrue(cost.cost_note)

	def test_program_without_norm_is_costed_without_chemicals(self):  # FR-M3-04.2
		self.rates()
		bare = factories.make_program(self.washer.name, code="MG-BARE", minutes=60, kwh=1, water=0)
		batch = self.batch(program=bare.name)
		from_laundry.on_laundry_complete(self.ctx(batch))
		cost = self.cost_of(batch)
		self.assertEqual((cost.cost_chemical, cost.cost_labor, cost.cost_total), (0, 60000, 63000))

	def test_outsourced_batch_keeps_its_own_price(self):  # UC-17 A2
		self.rates()
		batch = self.batch(
			batch_type="Outsourced",
			equipment=None,
			program=None,
			vendor="Giặt ABC",
			price_per_kg=12000,
			cost_total=120000,
			cost_per_kg=12000,
		)
		from_laundry.on_laundry_complete(self.ctx(batch))
		self.assertEqual(self.cost_of(batch).cost_total, 120000)

	def test_a_failure_while_costing_never_breaks_the_completion(self):
		batch = self.batch()
		with patch("tracecore.costing.from_laundry.rates.rate_for", side_effect=RuntimeError("boom")):
			from_laundry.on_laundry_complete(self.ctx(batch))
		self.assertEqual(self.cost_of(batch).cost_total, 0)
