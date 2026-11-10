"""Import hóa chất KSNK từ file khoa Dược qua Import Mapping Profile (FEAT-066 AC-2; FR-M12-12, FR-M9-28, EI-SW-010)."""

import frappe

from tracecore.compliance_audit import chemical_import, chemicals
from tracecore.compliance_audit.tests import chemical_factories as cf
from tracecore.core import importer
from tracecore.tests.factories import make_department
from tracecore.tests.utils import IsolatedTestCase

HEADER = "Ngày xuất;Khoa;Mã hàng;SL;ĐVT;Số phiếu"


def _csv(lines):
	return ("\n".join(lines) + "\n").encode("utf-8")


class TestChemicalImport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.department = make_department("KSNK Test Khoa Nội")
		self.ward = frappe.db.get_value("Department", self.department, "department_name")
		self.rub = cf.make_chemical("TC-HC-VST", "Hand Rub")
		self.surface = cf.make_chemical("TC-HC-BM", "Surface Disinfectant", stock_uom=cf.BOTTLE, litre_factor=2)
		cf.make_chemical("TC-HC-NOTYPE", None)
		if frappe.db.exists("Import Mapping Profile", "Hóa chất khoa Dược thử"):
			frappe.delete_doc("Import Mapping Profile", "Hóa chất khoa Dược thử", force=True, ignore_permissions=True)
		self.profile = (
			frappe.get_doc(
				{
					"doctype": "Import Mapping Profile",
					"profile_name": "Hóa chất khoa Dược thử",
					"import_kind": chemical_import.KEY,
					"file_format": "CSV",
					"encoding": "UTF-8",
					"delimiter": ";",
					"date_format": "dd/mm/yyyy",
					"columns": [
						{"source_column": s, "target_field": t}
						for s, t in (
							("Ngày xuất", "issue_date"),
							("Khoa", "department"),
							("Mã hàng", "item"),
							("SL", "qty"),
							("ĐVT", "uom"),
							("Số phiếu", "document_no"),
						)
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def file(self):
		w = self.ward
		return _csv(
			[
				HEADER,
				f"03/08/2026;{w};TC-HC-VST;12,5;;PX-001",
				f"03/08/2026;{w};TC-HC-BM;6;{cf.BOTTLE};PX-001",
				f"04/08/2026;Khoa không có;TC-HC-VST;1;;PX-002",
				f"04/08/2026;{w};TC-HC-NOTYPE;1;;PX-002",
				f"05/08/2026;{w};TC-HC-VST;0;;PX-003",
			]
		)

	def test_kind_is_registered(self):
		self.assertIn(chemical_import.KEY, importer.kinds())

	def test_check_reports_row_errors_without_writing(self):
		result = importer.check(chemical_import.KEY, self.file(), profile=self.profile)
		self.assertEqual((result["total"], result["valid"]), (5, 2))
		rows = {issue["row"] for issue in result["issues"]}
		self.assertEqual(rows, {4, 5, 6})
		self.assertFalse(frappe.db.exists(chemicals.DOCTYPE, {"source": chemicals.IMPORT, "source_ref": "PX-001"}))

	def test_run_records_import_source_and_reimport_creates_none(self):
		batch = frappe.get_doc(
			"Import Batch", importer.run(chemical_import.KEY, self.file(), None, profile=self.profile)
		)
		self.assertEqual((batch.created, batch.failed), (2, 3))
		rows = frappe.get_all(
			chemicals.DOCTYPE,
			filters={"source": chemicals.IMPORT, "import_batch": batch.name},
			fields=["item", "qty", "qty_litre", "period", "department", "docstatus", "source_ref"],
			order_by="item asc",
		)
		self.assertEqual(
			[(r.item, r.qty, r.qty_litre, r.period, r.docstatus, r.source_ref) for r in rows],
			[
				("TC-HC-BM", 6, 3, "2026-08", 1, "PX-001"),
				("TC-HC-VST", 12.5, 12.5, "2026-08", 1, "PX-001"),
			],
		)
		again = frappe.get_doc(
			"Import Batch", importer.run(chemical_import.KEY, self.file(), None, profile=self.profile)
		)
		self.assertEqual((again.created, again.skipped), (0, 2))

	def test_unknown_uom_is_a_row_error(self):
		content = _csv([HEADER, f"03/08/2026;{self.ward};TC-HC-VST;1;Thùng;PX-009"])
		result = importer.check(chemical_import.KEY, content, profile=self.profile)
		self.assertEqual(result["valid"], 0)
		self.assertEqual([i["field"] for i in result["issues"]], ["uom"])
