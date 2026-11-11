"""Nhập danh sách phẫu thuật từ file HIS/phòng mổ qua Import Mapping Profile (FEAT-064; UC-49 A1; FR-M9-28, F-21; D3;
BRU-HAI-005; A-147 i)."""

import frappe

from tracecore.core import importer
from tracecore.hai_surveillance import ssi, ssi_imports
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import ssi_fixtures as s
from tracecore.tests.utils import IsolatedTestCase, bru

HEADER = "Ma BN,Ho ten,Nam sinh,Gioi,Khoa,Nhom PT,Ngay mo,ASA,Vet mo,Phut mo,KSDP,Phut truoc rach da,Ra vien"


def _csv(lines):
	return ("\n".join(lines) + "\n").encode("utf-8")


def _profile(name="Phòng mổ thử"):
	if frappe.db.exists("Import Mapping Profile", name):
		frappe.delete_doc("Import Mapping Profile", name, force=True, ignore_permissions=True)
	columns = (
		("Ma BN", "patient_code"),
		("Nam sinh", "birth_year"),
		("Gioi", "sex"),
		("Khoa", "department"),
		("Nhom PT", "procedure_group"),
		("Ngay mo", "surgery_date"),
		("ASA", "asa_score"),
		("Vet mo", "wound_class"),
		("Phut mo", "duration_min"),
		("KSDP", "prophylaxis_given"),
		("Phut truoc rach da", "prophylaxis_minutes_before_incision"),
		("Ra vien", "discharge_date"),
	)
	return (
		frappe.get_doc(
			{
				"doctype": "Import Mapping Profile",
				"profile_name": name,
				"import_kind": ssi_imports.KEY,
				"file_format": "CSV",
				"encoding": "UTF-8",
				"delimiter": ",",
				"date_format": "dd/mm/yyyy",
				"columns": [{"source_column": a, "target_field": b} for a, b in columns],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestSurgeryImport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.ward = f.make_ward("KSNK SSI Import")
		self.label = frappe.db.get_value("Department", self.ward, "department_name")
		s.make_group("T-APPY", name="Cắt ruột thừa test", t=60)
		s.set_threshold(60)
		self.profile = _profile()

	def _file(self):
		w = self.label
		return _csv(
			[
				HEADER,
				f"BN-0000007001,Nguyen Van A,1970,Male,{w},T-APPY,01/10/2026,2,Clean,70,1,30,03/10/2026",
				f"BN-0000007002,Tran Thi B,1985,Female,{w},T-APPY,02/10/2026,,,,0,,",
				f"BN-0000007003,Le Van C,1990,Male,{w},T-KHONGCO,02/10/2026,1,Clean,40,0,,",
				f"BN-0000007004,Pham D,1990,Male,{w},T-APPY,02/10/2026,7,Clean,40,0,,",
			]
		)

	@bru("BRU-HAI-005")
	def test_import_creates_surgeries_without_names(self):
		batch = frappe.get_doc(
			"Import Batch", importer.run(ssi_imports.KEY, self._file(), None, profile=self.profile)
		)
		self.assertEqual((batch.created, batch.failed), (2, 2))
		errors = {(row.row_no, row.error_code) for row in batch.rows if row.result == "Error"}
		self.assertIn((4, "VALUE_INVALID"), errors)  # nhóm phẫu thuật không có
		self.assertIn((5, "SSI_VALUE_INVALID"), errors)
		names = frappe.get_all(ssi.DOCTYPE, filters={"import_batch": batch.name}, pluck="name")
		docs = [frappe.get_doc(ssi.DOCTYPE, name) for name in names]
		full = next(doc for doc in docs if doc.patient_code_masked == "***7001")
		self.assertEqual(
			(full.source, full.nnis_index, full.data_complete, full.window_days), ("Import", "1", 1, 30)
		)
		self.assertEqual(len(full.followups), 2)  # 7 ngày + lần cuối
		partial = next(doc for doc in docs if doc.patient_code_masked == "***7002")
		self.assertEqual((partial.data_complete, partial.nnis_index), (0, ""))  # A1: R11 bổ sung sau
		dump = frappe.as_json([row.as_dict() for row in batch.rows])
		self.assertNotIn("Nguyen Van A", dump)
		self.assertNotIn("BN-0000007001", dump)

	def test_reimport_marks_existing(self):
		importer.run(ssi_imports.KEY, self._file(), None, profile=self.profile)
		result = importer.check(ssi_imports.KEY, self._file(), profile=self.profile)
		self.assertEqual(len(result["existing"]), 2)
		self.assertFalse(result["upsert"])

	def test_kind_roles_and_privacy(self):
		kind = importer.get_kind(ssi_imports.KEY)
		self.assertEqual(set(kind.roles), {"TC R11", "TC R01", "System Manager"})
		self.assertTrue(kind.purge_file)
		self.assertIn("ho ten", kind.ignored_columns)
