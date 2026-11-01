"""Lô giặt: tự điền định mức, lưu định mức và thực tế, lý do lệch, chi phí (#1847 DV-03; FR-M3-09, .1, .2;
BRU-LIN-006, BRU-LIN-007; A-104 D4-D9)."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.core.errors import BlockedError
from tracecore.linen import laundry
from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import laundry as laundry_api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SOAP = "HC-1847-SOAP"
BLEACH = "HC-1847-BLE"
SOFT = "HC-1847-SOFT"
TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def _call_desk(**kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", datetime.now(TIME_ZONE).isoformat(timespec="seconds"))
	with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
		return laundry_api.complete_desk(**kwargs)


def code():
	return "LD-" + frappe.generate_hash(length=6).upper()


class Case(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		for item in (SOAP, BLEACH, SOFT):
			factories.make_item(item, "Chemical")
		self.station = factories.make_linen_station()
		self.operator = factories.make_employee(first_name="Giặt").name
		self.washer = factories.make_equipment(
			equipment_type="Laundry Washer",
			serial="LW-" + frappe.generate_hash(length=8),
			zone_in="ZONE-DIRTY",
			zone_out=None,
			capacity_kg=30,
		)
		self.dryer = factories.make_equipment(
			equipment_type="Dryer",
			serial="DR-" + frappe.generate_hash(length=8),
			zone_in="ZONE-DIRTY",
			zone_out=None,
			capacity_kg=30,
		)
		self.wash = factories.make_program(
			self.washer.name,
			code=code(),
			minutes=60,
			kwh=5,
			water=400,
			temperature=75,
			max_load_kg=20,
			consumables=[
				{"item": SOAP, "qty_per_load": 1, "qty_per_kg": 0.5, "unit_price": 100},
				{"item": BLEACH, "qty_per_kg": 0.1, "unit_price": 200},
			],
		)
		self.dry = factories.make_program(
			self.dryer.name, code=code(), minutes=30, kwh=8, water=0, temperature=80
		)

	def rates(self):
		return factories.make_cost_rate_version(
			rates=[factories.rate_line(3000, "Electricity"), factories.rate_line(20, "Tap Water")],
			submit=True,
		)

	def draft(self, **kwargs):
		values = {
			"doctype": "Laundry Batch",
			"batch_type": "In-house",
			"weight_kg": 10,
			"contaminated": 1,
			"equipment": self.washer.name,
			"program": self.wash.name,
			**kwargs,
		}
		return frappe.get_doc(values)

	def start(self, **kwargs):
		values = {
			"station": self.station,
			"operator": self.operator,
			"equipment": self.washer.name,
			"program": self.wash.name,
			"loads": [{"kg": 10, "contaminated": 1}],
			**kwargs,
		}
		return laundry.start(**values)

	def complete(self, doc, **kwargs):
		values = {
			"dryer": self.dryer.name,
			"dry_temp_c": 80,
			"dry_minutes": 30,
			"clean_ok": 1,
			"dry_ok": 1,
			**kwargs,
		}
		return laundry.complete(doc.name, **values)

	def assert_blocked(self, code_, call):
		with self.assertRaises(BlockedError) as caught:
			call()
		self.assertEqual(caught.exception.block.code, code_)

	def rows(self, doc):
		return {row.item: row for row in doc.chemicals}


class TestAutoFill(Case):
	def test_choosing_a_program_fills_chemicals_water_and_power(self):
		doc = self.start()
		rows = self.rows(doc)
		self.assertAlmostEqual(rows[SOAP].norm_qty, 6)
		self.assertAlmostEqual(rows[SOAP].qty, 6)
		self.assertAlmostEqual(rows[BLEACH].norm_qty, 1)
		self.assertEqual(rows[SOAP].uom, frappe.db.get_value("Item", SOAP, "stock_uom"))
		self.assertEqual((doc.norm_kwh, doc.actual_kwh), (5, 5))
		self.assertEqual((doc.norm_water_l, doc.actual_water_l), (400, 400))

	def test_operator_quantity_stays_and_norm_is_kept_beside_it(self):
		doc = self.start(chemicals=[{"item": SOAP, "qty": 7}])
		self.assertEqual(self.rows(doc)[SOAP].qty, 7)
		self.assertAlmostEqual(self.rows(doc)[SOAP].norm_qty, 6)

	def test_chemical_outside_the_norm_stays_with_a_zero_norm(self):
		doc = self.start(chemicals=[{"item": SOFT, "qty": 2}])
		self.assertEqual(self.rows(doc)[SOFT].norm_qty, 0)
		self.assertEqual(self.rows(doc)[SOFT].qty, 2)

	def test_zero_quantity_means_the_norm_as_stock_deducts_it(self):
		doc = self.start(chemicals=[{"item": SOAP, "qty": 0}])
		self.assertAlmostEqual(self.rows(doc)[SOAP].qty, 6)

	def test_changing_the_weight_moves_untouched_values_only(self):
		doc = self.start(chemicals=[{"item": BLEACH, "qty": 9}])
		doc.weight_kg = 20
		doc.save()
		rows = self.rows(doc)
		self.assertAlmostEqual(rows[SOAP].qty, 11)
		self.assertAlmostEqual(rows[BLEACH].norm_qty, 2)
		self.assertEqual(rows[BLEACH].qty, 9)

	def test_dry_program_adds_its_own_power_and_no_water(self):
		doc = self.start(dryer=self.dryer.name, dry_program=self.dry.name)
		self.assertEqual((doc.norm_dry_kwh, doc.actual_dry_kwh), (8, 8))
		self.assertEqual(doc.norm_water_l, 400)
		self.assertEqual(doc.norm_kwh, 5)

	def test_dry_chemical_row_records_its_program(self):
		dry = factories.make_program(
			self.dryer.name,
			code=code(),
			minutes=30,
			kwh=8,
			water=0,
			consumables=[{"item": SOFT, "qty_per_load": 2, "unit_price": 50}],
		)
		doc = self.start(dryer=self.dryer.name, dry_program=dry.name)
		self.assertEqual(self.rows(doc)[SOFT].program, dry.name)
		self.assertEqual(self.rows(doc)[SOAP].program, self.wash.name)

	def test_outsourced_batch_has_no_norm(self):
		doc = laundry.start(
			self.station,
			self.operator,
			[{"kg": 10, "contaminated": 1}],
			batch_type="Outsourced",
			vendor="NCC",
			price_per_kg=9000,
		)
		self.assertFalse(doc.norm_kwh)
		self.assertFalse(doc.chemicals)


class TestRules(Case):
	@bru("BRU-LIN-007")
	def test_weight_over_the_program_max_load_is_refused(self):
		self.assert_blocked(
			"LAUNDRY_OVER_PROGRAM_LOAD", lambda: self.start(loads=[{"kg": 21, "contaminated": 1}])
		)

	def test_dry_program_must_belong_to_the_dryer(self):
		self.assert_blocked(
			"LAUNDRY_PROGRAM_INVALID",
			lambda: self.start(dryer=self.dryer.name, dry_program=self.wash.name),
		)

	def test_dry_program_needs_a_dryer(self):
		self.assert_blocked("LAUNDRY_EQUIPMENT_INVALID", lambda: self.start(dry_program=self.dry.name))

	def test_desk_insert_keeps_the_rules_as_validation_errors(self):
		with self.assertRaises(frappe.ValidationError):
			self.draft(weight_kg=21).insert()
		with self.assertRaises(frappe.ValidationError):
			self.draft(equipment=None, program=None).insert()

	def test_desk_insert_starts_a_running_batch(self):
		doc = self.draft().insert()
		self.assertEqual(doc.status, "Running")
		self.assertTrue(doc.started_at)
		self.assertAlmostEqual(self.rows(doc)[SOAP].qty, 6)

	def test_a_running_batch_cannot_be_submitted_directly(self):
		doc = self.draft().insert()
		with self.assertRaises(frappe.ValidationError):
			doc.submit()

	def test_a_locked_washer_does_not_stop_saving_a_running_batch(self):
		doc = self.start()
		frappe.db.set_value("Equipment", self.washer.name, "status", "Locked")
		doc.result_note = "x"
		doc.save()


class TestDeviation(Case):
	@bru("BRU-LIN-006")
	def test_above_threshold_needs_a_reason_on_complete(self):
		doc = self.start()
		self.assert_blocked("LAUNDRY_DEVIATION_REASON_REQUIRED", lambda: self.complete(doc, actual_kwh=5.6))
		done = self.complete(doc, actual_kwh=5.6, deviation_reason="Giặt lại")
		self.assertEqual(done.status, "Passed")
		self.assertAlmostEqual(done.norm_deviation_pct, 12)
		self.assertEqual(done.deviation_reason, "Giặt lại")

	@bru("BRU-LIN-006")
	def test_within_threshold_needs_no_reason(self):
		doc = self.start()
		self.assertEqual(self.complete(doc, actual_kwh=5.5, actual_water_l=360).status, "Passed")

	@bru("BRU-LIN-006")
	def test_chemical_above_threshold_needs_a_reason(self):
		doc = self.start(chemicals=[{"item": SOAP, "qty": 7}])
		self.assert_blocked("LAUNDRY_DEVIATION_REASON_REQUIRED", lambda: self.complete(doc))

	def test_chemical_outside_the_norm_is_not_a_deviation(self):
		doc = self.start(chemicals=[{"item": SOFT, "qty": 7}])
		self.assertEqual(self.complete(doc).status, "Passed")

	@bru("BRU-LIN-006")
	def test_threshold_comes_from_settings(self):
		frappe.db.set_single_value("TraceCore Settings", "laundry_norm_deviation_percent", 50)
		self.addCleanup(
			frappe.db.set_single_value, "TraceCore Settings", "laundry_norm_deviation_percent", 10
		)
		doc = self.start()
		self.assertEqual(self.complete(doc, actual_kwh=7).status, "Passed")

	def test_negative_actual_is_refused(self):
		doc = self.start()
		self.assert_blocked("LAUNDRY_ACTUAL_INVALID", lambda: self.complete(doc, actual_kwh=-1))


class TestComplete(Case):
	def test_dry_program_at_completion_fills_power_and_drying_values(self):
		doc = self.start()
		done = laundry.complete(
			doc.name, dryer=self.dryer.name, dry_program=self.dry.name, clean_ok=1, dry_ok=1
		)
		self.assertEqual(done.dry_program, self.dry.name)
		self.assertEqual((done.dry_temp_c, done.dry_minutes), (80, 30))
		self.assertEqual((done.norm_dry_kwh, done.actual_dry_kwh), (8, 8))

	def test_dryer_chosen_at_start_is_used_at_completion(self):
		doc = self.start(dryer=self.dryer.name)
		done = laundry.complete(doc.name, dry_temp_c=80, dry_minutes=30, clean_ok=1, dry_ok=1)
		self.assertEqual(done.dryer, self.dryer.name)

	def test_cost_uses_actual_and_stores_the_norm_cost(self):
		self.rates()
		doc = self.start(chemicals=[{"item": SOAP, "qty": 6.3}])
		done = laundry.complete(
			doc.name,
			dryer=self.dryer.name,
			dry_program=self.dry.name,
			clean_ok=1,
			dry_ok=1,
			actual_kwh=5.5,
			actual_dry_kwh=8,
			actual_water_l=420,
		)
		# điện 13,5 kWh x 3000; nước 420 L x 20; hóa chất 6,3 x 100 + 1 x 200
		self.assertAlmostEqual(done.cost_electricity, 40500)
		self.assertAlmostEqual(done.cost_water, 8400)
		self.assertAlmostEqual(done.cost_chemical, 830)
		self.assertAlmostEqual(done.cost_total, 49730)
		self.assertAlmostEqual(done.cost_per_kg, 4973)
		# định mức 13 kWh; 400 L; 6 x 100 + 1 x 200
		self.assertAlmostEqual(done.norm_cost_electricity, 39000)
		self.assertAlmostEqual(done.norm_cost_water, 8000)
		self.assertAlmostEqual(done.norm_cost_chemical, 800)
		self.assertAlmostEqual(done.norm_cost_total, 47800)
		self.assertAlmostEqual(done.norm_cost_per_kg, 4780)
		rows = self.rows(done)
		self.assertEqual(rows[SOAP].unit_price, 100)
		self.assertAlmostEqual(rows[SOAP].amount, 630)

	def test_view_returns_the_norm_cost_for_the_station(self):
		self.rates()
		done = self.complete(self.start())
		view = laundry.view(done)
		self.assertAlmostEqual(view["norm_cost_total"], view["cost_total"])
		self.assertEqual(view["norm_deviation_pct"], 0)

	def test_context_lists_dry_programs_and_running_batch_norms(self):
		doc = self.start()
		ctx = laundry.context()
		self.assertIn(self.dry.name, [row.name for row in ctx["dry_programs"]])
		self.assertNotIn(self.dry.name, [row.name for row in ctx["programs"]])
		running = next(row for row in ctx["running"] if row.name == doc.name)
		self.assertEqual((running.norm_kwh, running.norm_water_l), (5, 400))


class TestDeskForm(Case):
	def test_refresh_norm_fills_an_unsaved_form_without_saving(self):
		doc = self.draft()
		doc.refresh_norm()
		self.assertFalse(doc.name)
		self.assertEqual(doc.actual_kwh, 5)
		self.assertAlmostEqual(self.rows(doc)[SOAP].qty, 6)

	def test_norm_preview_rpc_gives_the_cost_of_the_form(self):
		self.rates()
		preview = laundry_api.norm_preview(program=self.wash.name, dry_program=self.dry.name, kg=10)
		self.assertEqual(preview["electricity"], 13 * 3000)
		self.assertEqual(preview["chemical"], 800)

	def test_norm_preview_refuses_a_reader_without_batch_access(self):
		frappe.set_user(make_user("laundry-norm-r03@example.com", roles=("TC R03",)))
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			laundry_api.norm_preview(program=self.wash.name, kg=10)

	def test_complete_desk_finishes_a_saved_batch(self):
		doc = self.draft(dryer=self.dryer.name, dry_program=self.dry.name).insert()
		result = _call_desk(batch=doc.name, clean_ok=1, dry_ok=1)
		self.assertTrue(result["ok"])
		self.assertEqual(frappe.db.get_value("Laundry Batch", doc.name, "status"), "Passed")
		self.assertEqual(frappe.db.get_value("Laundry Batch", doc.name, "docstatus"), 1)

	@bru("BRU-LIN-006")
	def test_complete_desk_returns_the_reason_block_with_actuals_from_the_form(self):
		doc = self.draft(dryer=self.dryer.name, dry_program=self.dry.name, actual_kwh=9).insert()
		result = _call_desk(batch=doc.name, clean_ok=1, dry_ok=1)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "LAUNDRY_DEVIATION_REASON_REQUIRED")

	def test_complete_desk_needs_a_linen_role(self):
		doc = self.draft(dryer=self.dryer.name, dry_program=self.dry.name).insert()
		frappe.set_user(make_user("laundry-norm-r09@example.com", roles=("TC R09",)))
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			_call_desk(batch=doc.name, clean_ok=1, dry_ok=1)
