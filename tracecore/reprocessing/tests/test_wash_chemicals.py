"""Hóa chất của chương trình rửa tại T2: tình trạng tồn, tra lại lô mới nhập (ticket T2 31/10/2026; A-72, FR-M2-03.5)."""

import frappe

from tracecore.reprocessing import washing
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
]

ENZYME = "HC-WC-ENZ"
DISINFECTANT = "HC-WC-DIS"
RINSE = "HC-WC-RIN"


class WashChemicalCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.use_stock_company(self)
		factories.ensure_stock_masters()
		self.machine = factories.make_wash_machine()
		frappe.db.set_value("Equipment", self.machine.name, "status", "Ready")

	def program(self, chemical, consumables, code=None):
		return factories.make_wash_program(
			self.machine.name,
			chemical=chemical,
			code=code or "WC-" + frappe.generate_hash(length=5).upper(),
			consumables=consumables,
		)

	def status_of(self, program, item):
		rows = washing.program_chemicals(program.name)
		return next(row for row in rows if row["item"] == item)


@bru("BRU-INV-001")
class TestProgramChemicals(WashChemicalCase):
	def test_lists_every_chemical_of_the_program_with_name_and_state(self):
		factories.make_chemical_batch(ENZYME, "WC-ENZ-1", expiry_days=30, qty=10)
		factories.make_chemical_batch(DISINFECTANT, "WC-DIS-OLD", expiry_days=-5, qty=0)
		factories.make_chemical_batch(RINSE, "WC-RIN-1", expiry_days=30, qty=1)
		program = self.program(
			ENZYME,
			[
				{"item": ENZYME, "qty_per_load": 2},
				{"item": DISINFECTANT, "qty_per_load": 1},
				{"item": RINSE, "qty_per_load": 5},
			],
		)
		rows = washing.program_chemicals(program.name)
		self.assertEqual([row["item"] for row in rows], [ENZYME, DISINFECTANT, RINSE])
		self.assertTrue(all(row["item_name"] for row in rows))
		self.assertEqual(
			[row["status"] for row in rows], ["ok", "short", "short"]
		)  # đủ / hết tồn / còn 1, cần 5

	def test_stock_that_exists_only_in_expired_lots_is_reported_as_expired(self):
		factories.make_chemical_batch(ENZYME, "WC-ENZ-EXP", expiry_days=30, qty=10)
		frappe.db.set_value(
			"Batch", "WC-ENZ-EXP", "expiry_date", frappe.utils.add_days(frappe.utils.today(), -1)
		)
		program = self.program(ENZYME, [{"item": ENZYME, "qty_per_load": 1}])
		self.assertEqual(self.status_of(program, ENZYME)["status"], "expired")

	def test_non_chemical_consumables_are_not_listed(self):
		factories.make_chemical_batch(ENZYME, "WC-ENZ-2", expiry_days=30, qty=10)
		factories.make_item("VT-WC-IND", "Chemical Indicator")
		program = self.program(
			ENZYME, [{"item": ENZYME, "qty_per_load": 1}, {"item": "VT-WC-IND", "qty_per_load": 1}]
		)
		self.assertEqual([row["item"] for row in washing.program_chemicals(program.name)], [ENZYME])

	def test_program_without_chemicals_has_an_empty_list(self):
		program = self.program(None, [])
		self.assertEqual(washing.program_chemicals(program.name), [])


@bru("BRU-INV-001")
class TestScanAndRefresh(WashChemicalCase):
	def test_scan_machine_carries_the_chemical_list_of_each_program(self):
		factories.make_chemical_batch(ENZYME, "WC-ENZ-3", expiry_days=30, qty=10)
		program = self.program(ENZYME, [{"item": ENZYME, "qty_per_load": 1}])
		scanned = washing.scan_machine(self.machine.name)
		listed = next(row for row in scanned["programs"] if row["program_code"] == program.name)
		self.assertEqual([c["item"] for c in listed["chemicals"]], [ENZYME])

	def test_refresh_finds_a_lot_received_after_the_machine_was_scanned(self):
		factories.make_item(ENZYME, "Chemical", has_batch_no=1, apply_rules=True)
		program = self.program(ENZYME, [{"item": ENZYME, "qty_per_load": 1}])
		before = washing.refresh_lots(self.machine.name)
		self.assertEqual(before["chemical_lots"], [])
		factories.make_chemical_batch(ENZYME, "WC-ENZ-NEW", expiry_days=30, qty=10)
		after = washing.refresh_lots(self.machine.name)
		self.assertEqual([lot["batch_no"] for lot in after["chemical_lots"]], ["WC-ENZ-NEW"])
		listed = next(row for row in after["programs"] if row["program_code"] == program.name)
		self.assertEqual(listed["chemicals"][0]["status"], "ok")

	def test_refresh_refuses_a_machine_that_is_not_a_washer(self):
		from tracecore.core.errors import BlockedError

		with self.assertRaises(BlockedError):
			washing.refresh_lots("TB-NOT-THERE")
