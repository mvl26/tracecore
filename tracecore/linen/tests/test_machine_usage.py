"""Sử dụng theo máy và báo cáo định mức thiết bị giặt là (#1847 DV-04, DV-05; FR-M3-10; A-104 D10)."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.linen import laundry, machine_usage
from tracecore.linen.report.laundry_cost_per_kg import laundry_cost_per_kg
from tracecore.linen.report.laundry_equipment_norms import laundry_equipment_norms
from tracecore.tests import factories
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import laundry as laundry_api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SOAP = "HC-1847-SOAP"
BLEACH = "HC-1847-BLE"


def code():
	return "LD-" + frappe.generate_hash(length=6).upper()


class UsageCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.make_item(SOAP, "Chemical")
		factories.make_item(BLEACH, "Chemical")
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
		self.normal = factories.make_program(
			self.washer.name,
			code=code(),
			program_name="Giặt thường",
			minutes=60,
			kwh=5,
			water=400,
			temperature=75,
			consumables=[{"item": SOAP, "qty_per_kg": 0.5, "unit_price": 100}],
		)
		self.surgical = factories.make_program(
			self.washer.name,
			code=code(),
			program_name="Giặt đồ mổ",
			minutes=90,
			kwh=7,
			water=600,
			temperature=80,
			consumables=[{"item": BLEACH, "qty_per_load": 2, "unit_price": 200}],
		)
		self.dry = factories.make_program(
			self.dryer.name,
			code=code(),
			program_name="Sấy nhiệt cao",
			minutes=30,
			kwh=8,
			water=0,
			temperature=80,
		)
		factories.make_cost_rate_version(
			rates=[factories.rate_line(3000, "Electricity"), factories.rate_line(20, "Tap Water")],
			submit=True,
		)

	def run_batch(self, program=None, kg=10, **actual):
		doc = laundry.start(
			self.station,
			self.operator,
			[{"kg": kg, "contaminated": 1}],
			equipment=self.washer.name,
			program=(program or self.normal).name,
		)
		return laundry.complete(
			doc.name,
			dryer=self.dryer.name,
			dry_program=self.dry.name,
			clean_ok=1,
			dry_ok=1,
			deviation_reason="Lý do",
			**actual,
		)


class TestMachineUsage(UsageCase):
	def test_washer_day_shows_batches_programs_kg_water_power_cost(self):
		self.run_batch(actual_kwh=6, actual_water_l=500)  # thường: 10 kg
		self.run_batch(program=self.surgical, kg=20)  # đồ mổ: 20 kg
		usage = machine_usage.usage(self.washer.name, today(), today())
		self.assertEqual(usage["totals"]["batches"], 2)
		self.assertEqual(usage["totals"]["weight_kg"], 30)
		self.assertEqual(usage["totals"]["power_actual"], 13)
		self.assertEqual(usage["totals"]["power_norm"], 12)
		self.assertEqual(usage["totals"]["water_actual_m3"], 1.1)
		self.assertEqual(usage["totals"]["water_norm_m3"], 1)
		self.assertEqual({row["program"] for row in usage["days"]}, {self.normal.name, self.surgical.name})
		self.assertEqual(usage["days"][0]["date"], getdate(today()))
		chemicals = {row["item"]: row for row in usage["chemicals"]}
		self.assertEqual(chemicals[SOAP]["actual"], 5)
		self.assertEqual(chemicals[BLEACH]["actual"], 2)
		self.assertEqual(len(usage["history"]), 2)

	def test_washer_cost_takes_its_power_water_chemicals(self):
		self.run_batch(actual_kwh=6, actual_water_l=500)
		totals = machine_usage.usage(self.washer.name, today(), today())["totals"]
		# 6 kWh x 3000 + 500 L x 20 + 5 x 100
		self.assertAlmostEqual(totals["cost_actual"], 28500)
		# 5 kWh x 3000 + 400 L x 20 + 5 x 100
		self.assertAlmostEqual(totals["cost_norm"], 23500)

	def test_dryer_takes_only_its_own_power(self):
		self.run_batch(actual_dry_kwh=10)
		totals = machine_usage.usage(self.dryer.name, today(), today())["totals"]
		self.assertEqual(totals["batches"], 1)
		self.assertEqual(totals["power_actual"], 10)
		self.assertEqual(totals["power_norm"], 8)
		self.assertEqual(totals["water_actual_m3"], 0)
		self.assertAlmostEqual(totals["cost_actual"], 30000)
		self.assertAlmostEqual(totals["cost_norm"], 24000)

	def test_machine_costs_add_up_to_the_batch(self):
		batch = self.run_batch(actual_kwh=6)
		washer = machine_usage.usage(self.washer.name, today(), today())["totals"]
		dryer = machine_usage.usage(self.dryer.name, today(), today())["totals"]
		self.assertAlmostEqual(washer["cost_actual"] + dryer["cost_actual"], batch.cost_total)
		self.assertAlmostEqual(washer["cost_norm"] + dryer["cost_norm"], batch.norm_cost_total)

	def test_other_days_running_and_cancelled_batches_are_left_out(self):
		cancelled = self.run_batch()
		cancelled.flags.ignore_links = True
		cancelled.cancel()
		laundry.start(
			self.station,
			self.operator,
			[{"kg": 10, "contaminated": 1}],
			equipment=self.washer.name,
			program=self.normal.name,
		)
		self.run_batch()
		tomorrow = add_days(today(), 1)
		self.assertEqual(machine_usage.usage(self.washer.name, tomorrow, tomorrow)["totals"]["batches"], 0)
		self.assertEqual(machine_usage.usage(self.washer.name, today(), today())["totals"]["batches"], 1)

	def test_rpc_needs_read_access_to_batches(self):
		self.assertEqual(
			laundry_api.machine_usage(self.washer.name, today(), today())["totals"]["batches"], 0
		)
		frappe.set_user(make_user("laundry-usage-r03@example.com", roles=("TC R03",)))
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			laundry_api.machine_usage(self.washer.name, today(), today())


class TestNormsReport(UsageCase):
	def report(self, **filters):
		return laundry_equipment_norms.execute({"from_date": today(), "to_date": today(), **filters})

	def test_norm_actual_and_difference_per_machine_and_program(self):
		self.run_batch(actual_kwh=6, actual_water_l=500)
		self.run_batch(actual_kwh=4, actual_water_l=300)
		columns, rows = self.report(equipment=self.washer.name, program=self.normal.name)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row["machine"], self.washer.name)
		self.assertEqual(row["batches"], 2)
		self.assertEqual(row["weight_kg"], 20)
		self.assertEqual(row["power_norm"], 10)
		self.assertEqual(row["power_actual"], 10)
		self.assertEqual(row["power_difference"], 0)
		self.assertEqual(row["water_norm_m3"], 0.8)
		self.assertEqual(row["water_actual_m3"], 0.8)
		self.assertAlmostEqual(row["cost_actual"], 47000)
		self.assertAlmostEqual(row["cost_norm"], 47000)
		fieldnames = [column["fieldname"] for column in columns]
		self.assertIn("chem_0_norm", fieldnames)
		self.assertAlmostEqual(row["chem_0_norm"], 10)
		self.assertAlmostEqual(row["chem_0_actual"], 10)

	def test_difference_shows_above_and_below(self):
		self.run_batch(actual_kwh=6)
		row = self.report(equipment=self.washer.name)[1][0]
		self.assertEqual(row["power_difference"], 1)
		self.assertAlmostEqual(row["cost_difference"], 3000)

	def test_without_a_machine_filter_the_batch_shows_on_washer_and_dryer(self):
		self.run_batch()
		machines = {row["machine"] for row in self.report()[1]}
		self.assertEqual(machines, {self.washer.name, self.dryer.name})

	def test_program_filter_keeps_only_that_program(self):
		self.run_batch()
		self.run_batch(program=self.surgical)
		rows = self.report(program=self.surgical.name)[1]
		self.assertEqual({row["program"] for row in rows}, {self.surgical.name})

	def test_dates_are_required(self):
		with self.assertRaises(frappe.ValidationError):
			laundry_equipment_norms.execute({})

	def test_report_roles_match_the_cost_report(self):
		roles = set(frappe.get_all("Has Role", {"parent": "Laundry Equipment Norms"}, pluck="role"))
		self.assertEqual(roles, {"TC R01", "TC R02", "TC R07", "TC R09", "TC R10", "System Manager"})

	def test_report_is_in_the_linen_menu(self):
		frappe.set_user(make_user("laundry-usage-r02@example.com", roles=("TC R02",)))
		self.addCleanup(frappe.set_user, "Administrator")
		from tracecore.v1 import navigation

		routes = [link["route"] for link in navigation.context()["management"]]
		self.assertIn("/app/query-report/Laundry Equipment Norms", routes)


class TestCostPerKgMachineDetail(UsageCase):
	def filters(self, **kwargs):
		return {"from_date": today(), "to_date": today(), **kwargs}

	def test_machine_detail_adds_one_row_per_washer_under_the_month(self):
		first = self.run_batch()
		rows = laundry_cost_per_kg.execute(self.filters(machine_detail=1))[1]
		self.assertEqual(len(rows), 2)
		self.assertFalse(rows[0].get("machine"))
		self.assertEqual(rows[1]["machine"], self.washer.name)
		self.assertEqual(rows[1]["batches"], 1)
		self.assertEqual(rows[1]["weight_kg"], first.weight_kg)
		self.assertAlmostEqual(rows[1]["cost_per_kg"], round(first.cost_per_kg))

	def test_without_the_filter_the_report_stays_one_row_per_month(self):
		self.run_batch()
		rows = laundry_cost_per_kg.execute(self.filters())[1]
		self.assertEqual(len(rows), 1)
		self.assertNotIn("machine", rows[0])


class TestAcceptance(UsageCase):
	"""Tiêu chí nghiệm thu của ticket #1847, chạy nối từ khai báo đến báo cáo."""

	def test_two_machines_two_programs_each_batch_cost_machine_view_and_report(self):
		second_dry = factories.make_program(
			self.dryer.name,
			code=code(),
			program_name="Sấy thường",
			minutes=20,
			kwh=5,
			water=0,
			temperature=60,
		)
		for program in (self.normal, self.surgical, self.dry, second_dry):
			self.assertEqual(frappe.db.get_value("Process Program", program.name, "norm_status"), "Complete")

		batch = self.run_batch(actual_kwh=5.5)
		# điện (5,5 + 8) x 3000; nước 400 x 20; hóa chất 5 x 100
		self.assertAlmostEqual(batch.cost_total, 40500 + 8000 + 500)
		self.assertAlmostEqual(batch.cost_per_kg, 4900)
		self.assertAlmostEqual(batch.norm_cost_total, 39000 + 8000 + 500)
		self.assertAlmostEqual(batch.norm_cost_per_kg, 4750)

		usage = machine_usage.usage(self.washer.name, today(), today())
		self.assertEqual(usage["days"][0]["batches"], 1)
		self.assertEqual(usage["days"][0]["program"], self.normal.name)
		self.assertEqual(usage["chemicals"][0]["item"], SOAP)
		self.assertEqual(usage["totals"]["water_actual_m3"], 0.4)
		self.assertEqual(usage["totals"]["power_actual"], 5.5)

		row = laundry_equipment_norms.execute(
			{"from_date": today(), "to_date": today(), "equipment": self.washer.name}
		)[1][0]
		self.assertEqual((row["power_norm"], row["power_actual"], row["power_difference"]), (5, 5.5, 0.5))
		self.assertAlmostEqual(row["cost_difference"], 1500)
