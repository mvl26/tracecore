"""Import cơ số (Par Level) từ Excel (FEAT-011 Task 7; FR-M9-11, FR-M8-01; A-41 Q3)."""

import uuid

import frappe

from tracecore.core import importer
from tracecore.core.tests.test_importer import workbook
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Department"]

HEADER = (
	"Par Kind",
	"Target Type",
	"Target",
	"Department",
	"Max Cycles",
	"Source",
	"Min Stock Qty",
	"Max Stock Qty",
)


class TestParImport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.instrument = factories.make_instrument("PI-" + uuid.uuid4().hex[:6].upper()).name
		self.set_type = factories.make_set_type(
			"PI" + uuid.uuid4().hex[:4].upper(), bom=[(self.instrument, 1)]
		).name
		self.department = factories.make_department("Khoa cơ số import")

	def run_rows(self, rows):
		return frappe.get_doc(
			"Import Batch", importer.run("par_level", workbook(list(HEADER), rows), "f.xlsx")
		)

	def test_reprocessing_and_stock_par_levels_created(self):
		batch = self.run_rows(
			[
				["Reprocessing", "Instrument", self.instrument, None, 400, "IFU", None, None],
				["Department Stock", "Instrument Set Type", self.set_type, self.department, None, None, 2, 5],
			]
		)
		self.assertEqual(batch.created, 2, batch.rows)
		self.assertEqual(frappe.db.get_value("Par Level", batch.rows[0].ref_name, "max_cycles"), 400)
		stock = frappe.get_doc("Par Level", batch.rows[1].ref_name)
		self.assertEqual((stock.department, stock.min_qty, stock.max_qty), (self.department, 2, 5))

	def test_same_target_on_reimport_is_existing(self):
		row = ["Reprocessing", "Instrument", self.instrument, None, 400, "IFU", None, None]
		self.run_rows([row])
		self.assertEqual(self.run_rows([row]).skipped, 1)

	def test_rule_violation_is_row_error(self):
		row = ["Department Stock", "Instrument Set Type", self.set_type, self.department, None, None, 9, 3]
		batch = self.run_rows([row])
		self.assertEqual((batch.created, batch.failed), (0, 1))

	def test_unknown_target_is_row_error(self):
		result = importer.check(
			"par_level",
			workbook(list(HEADER), [["Reprocessing", "Instrument", "KHONG-CO", None, 10, "IFU", None, None]]),
		)
		self.assertEqual([i["code"] for i in result["issues"]], ["TARGET_NOT_FOUND"])
