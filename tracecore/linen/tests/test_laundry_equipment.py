"""Thiết bị giặt là và định mức theo mẻ (#1847 DV-01, DV-02; FR-M3-07, FR-M3-08; BRU-LIN-005; A-104)."""

import frappe
from frappe.utils import add_days, today

from tracecore.core import program_norm
from tracecore.costing import from_laundry
from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru
from tracecore.v1 import navigation

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SOAP = "HC-1847-SOAP"
BLEACH = "HC-1847-BLE"


def machine(equipment_type="Laundry Washer", **kwargs):
	return factories.make_equipment(
		equipment_type=equipment_type,
		serial=frappe.generate_hash(length=10),
		zone_in="ZONE-DIRTY",
		zone_out=None,
		**kwargs,
	)


def code():
	return "LD-" + frappe.generate_hash(length=6).upper()


class TestCatalog(IsolatedTestCase):
	def test_washer_and_dryer_declare_rated_power(self):
		washer = machine(capacity_kg=30)
		washer.rated_power_kw = 7.5
		washer.save()
		self.assertEqual(frappe.db.get_value("Equipment", washer.name, "rated_power_kw"), 7.5)

	def test_rated_power_cannot_be_negative(self):
		washer = machine()
		washer.rated_power_kw = -1
		with self.assertRaises(frappe.ValidationError):
			washer.save()

	def test_laundry_equipment_is_a_filtered_list_in_the_linen_group(self):
		frappe.set_user(make_user("laundry-eq-r02@example.com", roles=("TC R02",)))
		self.addCleanup(frappe.set_user, "Administrator")
		links = [link for link in navigation.context()["management"] if link["group"] == "Linen"]
		found = [link for link in links if link["label"] == "Laundry equipment"]
		self.assertEqual(len(found), 1)
		self.assertTrue(found[0]["route"].startswith("/app/equipment?equipment_type="))
		self.assertIn("Laundry Washer", found[0]["route"])
		self.assertIn("Dryer", found[0]["route"])

	def test_type_and_status_are_standard_list_filters(self):
		meta = frappe.get_meta("Equipment")
		self.assertTrue(meta.get_field("equipment_type").in_standard_filter)
		self.assertTrue(meta.get_field("status").in_standard_filter)

	def test_r07_reads_machines_and_programs_but_cannot_change_them(self):
		user = make_user("laundry-eq-r07@example.com", roles=("TC R07",))
		for doctype in ("Equipment", "Process Program"):
			self.assertTrue(frappe.has_permission(doctype, "read", user=user), doctype)
			self.assertFalse(frappe.has_permission(doctype, "write", user=user), doctype)

	def test_effective_permissions_match_the_matrix(self):
		assert_permission_matrix(self, "Equipment")
		assert_permission_matrix(self, "Process Program")


class NormCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.make_item(SOAP, "Chemical")
		factories.make_item(BLEACH, "Chemical")
		self.washer = machine(capacity_kg=30)
		self.dryer = machine("Dryer", capacity_kg=30)

	def wash(self, **kwargs):
		values = {
			"minutes": 60,
			"kwh": 5,
			"water": 400,
			"temperature": 75,
			"max_load_kg": 20,
			"consumables": [
				{"item": SOAP, "qty_per_load": 1, "qty_per_kg": 0.5, "unit_price": 100},
				{"item": BLEACH, "qty_per_kg": 0.1, "unit_price": 200},
			],
		}
		return factories.make_program(self.washer.name, code=code(), **{**values, **kwargs})


class TestProgramNorm(NormCase):
	@bru("BRU-LIN-005")
	def test_dryer_program_has_no_water(self):
		with self.assertRaises(frappe.ValidationError):
			factories.make_program(self.dryer.name, code=code(), minutes=30, kwh=8, water=50)

	def test_dryer_norm_is_complete_without_chemicals_or_water(self):
		program = factories.make_program(self.dryer.name, code=code(), minutes=30, kwh=8, water=0)
		self.assertEqual(program.norm_status, "Complete")

	def test_washer_still_needs_a_chemical_for_a_complete_norm(self):
		self.assertEqual(self.wash(consumables=[]).norm_status, "Missing")

	def test_max_load_cannot_be_negative_or_above_the_machine(self):
		with self.assertRaises(frappe.ValidationError):
			self.wash(max_load_kg=-1)
		with self.assertRaises(frappe.ValidationError):
			self.wash(max_load_kg=31)

	def test_unit_price_cannot_be_negative(self):
		with self.assertRaises(frappe.ValidationError):
			self.wash(consumables=[{"item": SOAP, "qty_per_load": 1, "unit_price": -1}])

	def test_empty_unit_price_takes_the_item_valuation_and_an_entered_price_stays(self):
		frappe.db.set_value("Item", SOAP, "valuation_rate", 150)
		program = self.wash(
			consumables=[
				{"item": SOAP, "qty_per_load": 1},
				{"item": BLEACH, "qty_per_load": 1, "unit_price": 222},
			]
		)
		self.assertEqual(program.consumables[0].unit_price, 150)
		self.assertEqual(program.consumables[1].unit_price, 222)

	def test_unit_price_is_not_filled_on_sterilizer_programs(self):
		frappe.db.set_value("Item", SOAP, "valuation_rate", 150)
		sterilizer = factories.make_equipment(serial=frappe.generate_hash(length=10))
		program = factories.make_program(
			sterilizer.name, code=code(), consumables=[{"item": SOAP, "qty_per_load": 1}]
		)
		self.assertFalse(program.consumables[0].unit_price)

	def test_norm_quantities_add_per_batch_and_per_kg(self):
		norm = program_norm.of(self.wash().name, 10)
		self.assertEqual(norm["kwh"], 5)
		self.assertEqual(norm["water_l"], 400)
		self.assertEqual(norm["minutes"], 60)
		lines = {line["item"]: line for line in norm["lines"]}
		self.assertAlmostEqual(lines[SOAP]["qty"], 6)
		self.assertAlmostEqual(lines[BLEACH]["qty"], 1)

	def test_norm_quantities_convert_the_line_unit_to_the_stock_unit(self):
		stock_uom = frappe.db.get_value("Item", SOAP, "stock_uom")
		other = "TC Norm Unit"  # site CI mới chỉ có ĐVT tồn kho
		if not frappe.db.exists("UOM", other):
			frappe.get_doc({"doctype": "UOM", "uom_name": other}).insert(ignore_permissions=True)
		item = frappe.get_doc("Item", SOAP)
		item.append("uoms", {"uom": other, "conversion_factor": 0.001})
		item.save()
		program = self.wash(
			consumables=[{"item": SOAP, "uom": other, "qty_per_load": 500, "unit_price": 100}]
		)
		line = program_norm.of(program.name, 10)["lines"][0]
		self.assertAlmostEqual(line["qty"], 0.5)
		self.assertEqual(line["uom"], stock_uom)


class TestNormCost(NormCase):
	def rates(self, *extra):
		lines = [
			factories.rate_line(3000, "Electricity"),
			factories.rate_line(20, "Tap Water"),
			*extra,
		]
		return factories.make_cost_rate_version(rates=lines, submit=True)

	def test_norm_cost_per_batch_and_per_kg_at_the_program_max_load(self):
		self.rates()
		cost = from_laundry.norm_breakdown([self.wash().name])
		self.assertEqual(cost["kg"], 20)
		# 5 kWh x 3000; 400 L x 20; (1 + 0,5 x 20) x 100 + 0,1 x 20 x 200 = 1500
		self.assertEqual(cost["electricity"], 15000)
		self.assertEqual(cost["water"], 8000)
		self.assertEqual(cost["chemical"], 1500)
		self.assertEqual(cost["total"], 24500)
		self.assertEqual(cost["per_kg"], 1225)
		self.assertEqual(cost["missing"], ["Labor"])

	def test_water_price_is_also_shown_per_cubic_metre(self):
		self.rates()
		self.assertEqual(from_laundry.norm_breakdown([self.wash().name])["water_rate_m3"], 20000)

	def test_approved_price_list_wins_over_the_program_price(self):
		self.rates(factories.rate_line(1000, "Item", SOAP))
		cost = from_laundry.norm_breakdown([self.wash().name], kg=10)
		lines = {line["item"]: line for line in cost["lines"]}
		self.assertEqual(lines[SOAP]["unit_price"], 1000)
		self.assertEqual(lines[SOAP]["price_source"], "Price list")
		self.assertEqual(lines[BLEACH]["unit_price"], 200)
		self.assertEqual(lines[BLEACH]["price_source"], "Program")

	def test_missing_rates_are_listed_and_do_not_raise(self):
		cost = from_laundry.norm_breakdown([self.wash().name], kg=10)
		self.assertEqual(cost["electricity"], 0)
		self.assertEqual(cost["chemical"], 600 + 200)
		self.assertTrue(cost["missing"])

	def test_wash_and_dry_programs_add_up(self):
		self.rates()
		dry = factories.make_program(self.dryer.name, code=code(), minutes=30, kwh=8, water=0)
		cost = from_laundry.norm_breakdown([self.wash().name, dry.name], kg=10)
		self.assertEqual(cost["electricity"], 13 * 3000)
		self.assertEqual(cost["water"], 8000)

	def test_a_rate_change_is_read_by_effective_date(self):
		self.rates()
		day = add_days(today(), 10)
		factories.make_cost_rate_version(
			rates=[factories.rate_line(4000, "Electricity")], effective_from=day, submit=True
		)
		program = self.wash().name
		self.assertEqual(from_laundry.norm_breakdown([program], day=day)["electricity"], 20000)
		self.assertEqual(from_laundry.norm_breakdown([program])["electricity"], 15000)
