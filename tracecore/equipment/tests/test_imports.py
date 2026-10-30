"""Import thiết bị và chương trình xử lý từ Excel (FEAT-011 Task 6; FR-M9-11, UC-39; A-41 Q3, D3, D5)."""

import uuid

import frappe

from tracecore.core import importer
from tracecore.core.tests.test_importer import workbook
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Asset"]

EQUIPMENT_HEADER = (
	"Equipment Name",
	"Equipment Type",
	"Manufacturer",
	"Model",
	"Serial No",
	"Zone In",
	"Zone Out",
	"Purchase Value",
	"Depreciation Years",
	"Planned Loads per Year",
)
PROGRAM_HEADER = (
	"Program Code",
	"Program Name",
	"Equipment Serial No",
	"Duration (min)",
	"Parameter",
	"Unit",
	"Min",
	"Max",
	"Required Parameter",
)


def serial():
	return "IMP-SN-" + uuid.uuid4().hex[:6].upper()


def run(key, header, rows):
	return frappe.get_doc("Import Batch", importer.run(key, workbook(list(header), rows), "f.xlsx"))


class EquipmentImportCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def equipment_row(self, number, **over):
		values = {
			"Equipment Name": "Máy hấp import",
			"Equipment Type": "Steam Sterilizer",
			"Manufacturer": "Getinge",
			"Model": "GSS67",
			"Serial No": number,
			"Zone In": "ZONE-CLEAN",
			"Zone Out": "ZONE-STERILE",
			"Purchase Value": 600000000,
			"Depreciation Years": 10,
			"Planned Loads per Year": 3000,
			**over,
		}
		return [values[name] for name in EQUIPMENT_HEADER]


class TestEquipmentImport(EquipmentImportCase):
	@bru("BRU-ID-006")
	def test_equipment_created_with_generated_code(self):
		number = serial()
		batch = run("equipment", EQUIPMENT_HEADER, [self.equipment_row(number)])
		self.assertEqual(batch.created, 1, batch.rows)
		name = batch.rows[0].ref_name
		self.assertRegex(name, r"^TB-\d{4}$")
		self.assertEqual(frappe.db.get_value("Equipment", name, "serial_no"), number)

	def test_same_serial_is_existing(self):
		number = serial()
		factories.make_equipment(serial=number)
		self.assertEqual(run("equipment", EQUIPMENT_HEADER, [self.equipment_row(number)]).skipped, 1)

	def test_unknown_zone_is_row_error(self):
		result = importer.check(
			"equipment",
			workbook(list(EQUIPMENT_HEADER), [self.equipment_row(serial(), **{"Zone In": "ZONE-NONE"})]),
		)
		self.assertEqual([(i["row"], i["code"]) for i in result["issues"]], [(2, "ZONE_NOT_FOUND")])

	@bru("BRU-ID-006")
	def test_equipment_code_column_rejected(self):
		with self.assertRaises(importer.ImportFileError):
			importer.parse(
				importer.get_kind("equipment"), workbook([*EQUIPMENT_HEADER, "Equipment Code"], [])
			)


class TestProgramImport(EquipmentImportCase):
	def setUp(self):
		super().setUp()
		self.serial = serial()
		self.machine = factories.make_equipment(serial=self.serial).name

	def test_program_with_parameters_from_several_rows(self):
		code = "IMP-" + uuid.uuid4().hex[:5].upper()
		rows = [
			[code, "Hấp 134", self.serial, 4, "Sterilization temperature", "°C", 132, 138, 1],
			[code, None, None, None, "Pressure", "bar", 0, 2.3, 1],
		]
		batch = run("program", PROGRAM_HEADER, rows)
		self.assertEqual(batch.created, 1, batch.rows)
		doc = frappe.get_doc("Process Program", batch.rows[0].ref_name)
		self.assertEqual(doc.equipment, self.machine)
		self.assertEqual(
			[row.parameter_name for row in doc.parameters], ["Sterilization temperature", "Pressure"]
		)

	def test_unknown_equipment_serial_is_row_error(self):
		result = importer.check(
			"program",
			workbook(list(PROGRAM_HEADER), [["P-X", "X", "NO-SUCH-SN", 4, None, None, None, None, None]]),
		)
		self.assertEqual([i["code"] for i in result["issues"]], ["EQUIPMENT_NOT_FOUND"])

	def test_existing_program_skipped(self):
		code = "IMP-" + uuid.uuid4().hex[:5].upper()
		factories.make_program(self.machine, code=code)
		row = [code, "Đã có", self.serial, 4, None, None, None, None, None]
		self.assertEqual(run("program", PROGRAM_HEADER, [row]).skipped, 1)
