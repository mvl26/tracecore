"""Import dụng cụ, loại bộ & BOM, Set Unit từ Excel (FEAT-011 Task 4-5; FR-M9-11, UC-39; A-41 Q3, D3, D5)."""

import uuid

import frappe

from tracecore.core import importer
from tracecore.core.tests.test_importer import workbook
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Department", "Instrument", "Instrument Set Type"]

INSTRUMENT_HEADER = (
	"Instrument Code",
	"Instrument Name",
	"Spaulding Class",
	"Compatible Methods",
	"Max Cycles",
)
SET_TYPE_HEADER = (
	"Type Code",
	"Set Type Name",
	"Method",
	"Department",
	"Default Pack Type",
	"Instrument",
	"Quantity",
	"Position",
)


def code(prefix="IM"):
	return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


def run(key, header, rows):
	return frappe.get_doc("Import Batch", importer.run(key, workbook(list(header), rows), "f.xlsx"))


class ImportCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")


class TestInstrumentImport(ImportCase):
	def test_instruments_created_with_methods(self):
		first, second = code(), code()
		batch = run(
			"instrument",
			INSTRUMENT_HEADER,
			[
				[first.lower(), "Kéo Mayo", "Critical", "Steam 134, Plasma", 500],
				[second, "Kẹp Kelly", "Semi-critical", "Steam 121", None],
			],
		)
		self.assertEqual(batch.created, 2, batch.rows)
		doc = frappe.get_doc("Instrument", first)  # mã chuẩn hóa viết hoa như nhập tay
		self.assertEqual(sorted(row.method for row in doc.compatible_methods), ["Plasma", "Steam 134"])
		self.assertEqual(doc.max_cycles, 500)

	def test_invalid_code_and_method_are_row_errors(self):
		result = importer.check(
			"instrument",
			workbook(
				list(INSTRUMENT_HEADER),
				[["BAD CODE!", "X", "Critical", "Steam 134", None], [code(), "Y", "Critical", "Gamma", None]],
			),
		)
		self.assertEqual(
			[(i["row"], i["code"]) for i in result["issues"]], [(2, "CODE_INVALID"), (3, "VALUE_INVALID")]
		)

	def test_existing_instrument_skipped(self):
		existing = factories.make_instrument(code()).name
		batch = run("instrument", INSTRUMENT_HEADER, [[existing, "Đã có", "Critical", "Steam 134", None]])
		self.assertEqual((batch.created, batch.skipped), (0, 1))


class TestSetTypeImport(ImportCase):
	def setUp(self):
		super().setUp()
		self.department = factories.make_department("Khoa import loại bộ")
		self.pack_type = factories.make_pack_type()
		self.a = factories.make_instrument(code(), methods=("Steam 134",)).name
		self.b = factories.make_instrument(code(), methods=("Steam 134",)).name

	def head(self, type_code, **over):
		values = {
			"Type Code": type_code,
			"Set Type Name": "Bộ phẫu thuật " + type_code,
			"Method": "Steam",
			"Department": self.department,
			"Default Pack Type": self.pack_type,
		}
		values.update(over)
		return values

	def row(self, head, instrument, qty, position=None):
		values = {**head, "Instrument": instrument, "Quantity": qty, "Position": position}
		return [values.get(name) for name in SET_TYPE_HEADER]

	def test_set_type_with_bom_from_several_rows(self):
		type_code = "IT" + uuid.uuid4().hex[:4].upper()
		head = self.head(type_code)
		follow = {"Type Code": type_code}
		batch = run("set_type", SET_TYPE_HEADER, [self.row(head, self.a, 2), self.row(follow, self.b, 1)])
		self.assertEqual(batch.created, 1, batch.rows)
		lines = frappe.get_all(
			"Set BOM Item", filters={"set_type": type_code}, fields=["instrument", "qty"], order_by="position"
		)
		self.assertEqual([(line.instrument, line.qty) for line in lines], [(self.a, 2), (self.b, 1)])

	def test_unknown_instrument_points_to_its_excel_row(self):
		type_code = "IT" + uuid.uuid4().hex[:4].upper()
		head = self.head(type_code)
		result = importer.check(
			"set_type",
			workbook(
				list(SET_TYPE_HEADER),
				[self.row(head, self.a, 2), self.row({"Type Code": type_code}, "KHONG-CO", 1)],
			),
		)
		self.assertEqual([(i["row"], i["field"]) for i in result["issues"]], [(3, "instrument")])

	def test_header_conflict_between_rows(self):
		type_code = "IT" + uuid.uuid4().hex[:4].upper()
		rows = [
			self.row(self.head(type_code), self.a, 1),
			self.row(self.head(type_code, Method="Plasma"), self.b, 1),
		]
		result = importer.check("set_type", workbook(list(SET_TYPE_HEADER), rows))
		self.assertEqual([(i["row"], i["code"]) for i in result["issues"]], [(3, "GROUP_CONFLICT")])

	def test_existing_set_type_skipped(self):
		existing = factories.make_set_type("IT" + uuid.uuid4().hex[:4].upper(), bom=[(self.a, 1)]).name
		batch = run("set_type", SET_TYPE_HEADER, [self.row(self.head(existing), self.a, 1)])
		self.assertEqual(batch.skipped, 1)


class TestSetUnitImport(ImportCase):
	HEADER = ("Type Code", "Count", "Department", "Max Cycles")

	def setUp(self):
		super().setUp()
		instrument = factories.make_instrument(code(), methods=("Steam 134",)).name
		self.set_type = factories.make_set_type(
			"SU" + uuid.uuid4().hex[:4].upper(), bom=[(instrument, 1)]
		).name

	@bru("BRU-ID-006")
	def test_set_units_issued_with_generated_set_ids(self):
		before = frappe.db.count("Set Unit", {"set_type": self.set_type})
		batch = run("set_unit", self.HEADER, [[self.set_type, 3, None, 300]])
		self.assertEqual(batch.created, 1, batch.rows)
		self.assertEqual(frappe.db.count("Set Unit", {"set_type": self.set_type}), before + 3)
		self.assertTrue(frappe.db.exists("Set Unit", batch.rows[0].ref_name))

	def test_count_out_of_range_is_row_error(self):
		result = importer.check("set_unit", workbook(list(self.HEADER), [[self.set_type, 0, None, 300]]))
		self.assertEqual([i["code"] for i in result["issues"]], ["COUNT_OUT_OF_RANGE"])

	@bru("BRU-ID-006")
	def test_set_id_column_rejected(self):
		with self.assertRaises(importer.ImportFileError):
			importer.parse(importer.get_kind("set_unit"), workbook([*self.HEADER, "Set ID"], []))
