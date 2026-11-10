"""Import mẫu số ngày từ file HIS qua Import Mapping Profile (FEAT-062; FR-M13-02, FR-M13-02.2, FR-M9-28, EI-SW-010;
A-141 Q2: import lại cập nhật bản có sẵn)."""

import frappe
from frappe.utils import add_days, formatdate, getdate, today

from tracecore.core import importer
from tracecore.hai_surveillance import imports
from tracecore.hai_surveillance.tests import factories as f
from tracecore.tests.utils import IsolatedTestCase, bru

HEADER = "Ngay,Khoa,So NB,Tho may,CVC,Thong tieu,Nhap vien"


def _csv(lines):
	return ("\n".join(lines) + "\n").encode("utf-8")


def _profile(name="Mẫu số HIS thử"):
	if frappe.db.exists("Import Mapping Profile", name):
		frappe.delete_doc("Import Mapping Profile", name, force=True, ignore_permissions=True)
	columns = (
		("Ngay", "census_date"),
		("Khoa", "department"),
		("So NB", "patient_count"),
		("Tho may", "vent_count"),
		("CVC", "cvc_count"),
		("Thong tieu", "urinary_catheter_count"),
		("Nhap vien", "admissions"),
	)
	return (
		frappe.get_doc(
			{
				"doctype": "Import Mapping Profile",
				"profile_name": name,
				"import_kind": imports.KEY,
				"file_format": "CSV",
				"encoding": "UTF-8",
				"delimiter": ",",
				"date_format": "dd/mm/yyyy",
				"columns": [{"source_column": s, "target_field": t} for s, t in columns],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestCensusImport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.ward = f.make_ward("KSNK Import ICU")
		frappe.db.delete("Ward Daily Census", {"department": self.ward})
		self.label = frappe.db.get_value("Department", self.ward, "department_name")
		self.profile = _profile()
		self.d1 = getdate(add_days(today(), -3))
		self.d2 = getdate(add_days(today(), -2))

	def _file(self, patients=16):
		w, d1, d2 = self.label, formatdate(self.d1, "dd/mm/yyyy"), formatdate(self.d2, "dd/mm/yyyy")
		return _csv(
			[
				HEADER,
				f"{d1},{w},{patients},7,10,12,2",
				f"{d2},{w},16,7,9,17,1",
				f"{d2},Khoa không có,16,7,9,11,1",
			]
		)

	def test_check_reports_row_errors(self):
		result = importer.check(imports.KEY, self._file(), profile=self.profile)
		self.assertEqual((result["total"], result["valid"]), (3, 1))
		codes = {(issue["row"], issue["code"], issue["field"]) for issue in result["issues"]}
		self.assertIn((3, "CENSUS_COUNT_INVALID", "urinary_catheter_count"), codes)
		self.assertIn((4, "DEPARTMENT_NOT_FOUND", "department"), codes)
		self.assertEqual(frappe.db.count("Ward Daily Census", {"department": self.ward}), 0)

	@bru("BRU-HAI-002")
	def test_reimport_updates_existing_without_duplicates(self):
		batch = frappe.get_doc("Import Batch", importer.run(imports.KEY, self._file(), None, profile=self.profile))
		self.assertEqual((batch.created, batch.updated, batch.failed), (1, 0, 2))
		name = frappe.db.get_value("Ward Daily Census", {"department": self.ward, "census_date": self.d1})
		doc = frappe.get_doc("Ward Daily Census", name)
		self.assertEqual((doc.source, doc.import_batch, doc.patient_count), ("Import", batch.name, 16))
		again = frappe.get_doc(
			"Import Batch", importer.run(imports.KEY, self._file(patients=18), None, profile=self.profile)
		)
		self.assertEqual((again.created, again.updated), (0, 1))
		self.assertEqual([row.result for row in again.rows if row.row_no == 2], ["Updated"])
		self.assertEqual(frappe.db.count("Ward Daily Census", {"department": self.ward}), 1)
		self.assertEqual(frappe.db.get_value("Ward Daily Census", name, "patient_count"), 18)

	def test_manual_census_is_updated_by_import(self):
		f.make_census(self.ward, self.d1, patients=30)
		batch = frappe.get_doc("Import Batch", importer.run(imports.KEY, self._file(), None, profile=self.profile))
		self.assertEqual(batch.updated, 1)
		row = frappe.db.get_value(
			"Ward Daily Census", {"department": self.ward, "census_date": self.d1}, ["patient_count", "source"]
		)
		self.assertEqual(row, (16, "Import"))

	@bru("BRU-HAI-002")
	def test_locked_census_is_a_row_error(self):
		doc = f.make_census(self.ward, self.d1, patients=30)
		frappe.db.set_value("Ward Daily Census", doc.name, "locked", 1)
		batch = frappe.get_doc("Import Batch", importer.run(imports.KEY, self._file(), None, profile=self.profile))
		self.assertEqual((batch.created, batch.updated), (0, 0))
		errors = {(row.row_no, row.error_code) for row in batch.rows if row.result == "Error"}
		self.assertIn((2, "CENSUS_PERIOD_LOCKED"), errors)
		self.assertEqual(frappe.db.get_value("Ward Daily Census", doc.name, "patient_count"), 30)

	def test_kind_for_infection_control(self):
		kind = importer.get_kind(imports.KEY)
		self.assertIn("TC R11", kind.roles)
		self.assertTrue(kind.upsert)

	def test_duplicate_row_in_file(self):
		w, d1 = self.label, formatdate(self.d1, "dd/mm/yyyy")
		content = _csv([HEADER, f"{d1},{w},16,7,10,12,2", f"{d1},{w},17,7,10,12,2"])
		result = importer.check(imports.KEY, content, profile=self.profile)
		self.assertEqual([issue["code"] for issue in result["issues"]], ["DUPLICATE_IN_FILE"])
