"""Import kết quả vi sinh qua Import Mapping Profile (FEAT-067 AC-1..AC-5; FR-M14-01 .1 .2 .3; UC-51 E1..E3; A-136 Q6)."""

import frappe

from tracecore.core import importer, notification
from tracecore.microbiology import imports
from tracecore.microbiology.tests.factories import make_organism, make_rule
from tracecore.tests.factories import make_department, make_user
from tracecore.tests.utils import IsolatedTestCase, bru

LONG_HEADER = "Mã mẫu,Mã VK,Mã BN,Năm sinh,Khoa,Bệnh phẩm,Ngày lấy,KS,KQ,MIC"
WIDE_HEADER = "SPEC_NUM,ORGANISM,PATIENT_ID,LAST_NAME,WARD,SPEC_TYPE,SPEC_DATE,MEM_NM,CIP_ND5"


def _csv(lines):
	return ("\n".join(lines) + "\n").encode("utf-8")


def _profile(name, columns):
	if frappe.db.exists("Import Mapping Profile", name):
		frappe.delete_doc("Import Mapping Profile", name, force=True, ignore_permissions=True)
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


class TestMicrobiologyImport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		make_organism()
		make_organism("eco", "Escherichia coli", "Enterobacterales")
		notification.ensure_default_rules()
		frappe.db.delete("MDRO Rule", {"rule_code": ["not like", "T-%"]})
		self.department = make_department("Khoa Hồi sức vi sinh")
		self.ward = frappe.db.get_value("Department", self.department, "department_name")
		self.long = _profile(
			"VS dài thử",
			[
				("Mã mẫu", "lab_sample_id"),
				("Mã VK", "organism"),
				("Mã BN", "patient_code"),
				("Năm sinh", "birth_year"),
				("Khoa", "department"),
				("Bệnh phẩm", "specimen_type"),
				("Ngày lấy", "collected_on"),
				("KS", "antibiotic"),
				("KQ", "result"),
				("MIC", "mic"),
			],
		)
		self.wide = _profile(
			"WHONET thử",
			[
				("SPEC_NUM", "lab_sample_id"),
				("ORGANISM", "organism"),
				("PATIENT_ID", "patient_code"),
				("WARD", "department"),
				("SPEC_TYPE", "specimen_type"),
				("SPEC_DATE", "collected_on"),
				("MEM_NM", "ab:MEM"),
				("CIP_ND5", "ab:CIP"),
			],
		)

	def long_file(self):
		w = self.ward
		return _csv(
			[
				LONG_HEADER,
				f"LAB1,kpn,BN0001234,1960,{w},Máu,03/08/2026,MEM,R,>8",
				"LAB1,kpn,,,,,,CIP,S,",
				f"LAB2,eco,BN0005678,1972,{w},Nước tiểu,04/08/2026,MEM,S,",
				f"LAB3,,BN0009999,1980,{w},Đờm,05/08/2026,MEM,S,",
				f"LAB4,xyz,BN0009999,1980,{w},Đờm,05/08/2026,MEM,S,",
			]
		)

	def test_check_reports_valid_rows_and_row_errors_before_writing(self):
		result = importer.check(imports.KEY, self.long_file(), profile=self.long)
		self.assertEqual((result["total"], result["valid"]), (5, 2))
		codes = {(issue["row"], issue["code"]) for issue in result["issues"]}
		self.assertEqual(codes, {(5, "REQUIRED"), (6, "ORGANISM_NOT_FOUND")})
		self.assertEqual(frappe.db.count("Microbiology Isolate", {"lab_sample_id": ["like", "LAB%"]}), 0)

	def test_import_creates_isolates_with_antibiogram_and_reimport_creates_none(self):
		make_rule("T-CRE", label="CRE")
		batch = frappe.get_doc(
			"Import Batch", importer.run(imports.KEY, self.long_file(), None, profile=self.long)
		)
		self.assertEqual((batch.created, batch.skipped, batch.failed), (2, 0, 2))
		name = frappe.db.get_value("Microbiology Isolate", {"lab_sample_id": "LAB1"}, "name")
		doc = frappe.get_doc("Microbiology Isolate", name)
		self.assertEqual(
			[(r.antibiotic, r.result, r.mic) for r in doc.susceptibility],
			[("MEM", "R", ">8"), ("CIP", "S", None)],
		)
		self.assertEqual((doc.source, doc.import_batch, doc.mdro_flags), ("Import", batch.name, "CRE"))
		self.assertEqual(doc.patient_code_masked, "***1234")
		self.assertNotIn("BN0001234", frappe.as_json(batch.as_dict()))
		again = frappe.get_doc(
			"Import Batch", importer.run(imports.KEY, self.long_file(), None, profile=self.long)
		)
		self.assertEqual((again.created, again.skipped), (0, 2))

	def test_missing_organism_row_is_reported_with_its_row_number(self):
		batch = frappe.get_doc(
			"Import Batch", importer.run(imports.KEY, self.long_file(), None, profile=self.long)
		)
		errors = {(row.row_no, row.error_code) for row in batch.rows if row.result == "Error"}
		self.assertIn((5, "REQUIRED"), errors)
		self.assertFalse(frappe.db.exists("Microbiology Isolate", {"lab_sample_id": "LAB3"}))

	def test_wide_whonet_file_with_name_column(self):
		w = self.ward
		content = _csv(
			[
				WIDE_HEADER,
				f"W1,kpn,BN0001111,Nguyen,{w},Blood,10/08/2026,R (>8),S",
				f"W2,eco,BN0002222,Tran,{w},Urine,11/08/2026,>=32 R,",
				f"W3,eco,BN0003333,Le,{w},Urine,11/08/2026,8,S",
			]
		)
		result = importer.check(imports.KEY, content, profile=self.wide)
		self.assertEqual(result["valid"], 2)
		self.assertEqual(len(result["warnings"]), 1)
		self.assertEqual([(i["row"], i["field"]) for i in result["issues"]], [(4, "ab:MEM")])
		importer.run(imports.KEY, content, None, profile=self.wide)
		doc = frappe.get_doc("Microbiology Isolate", {"lab_sample_id": "W1"})
		self.assertEqual(
			[(r.antibiotic, r.result, r.mic) for r in doc.susceptibility],
			[("MEM", "R", ">8"), ("CIP", "S", None)],
		)
		self.assertEqual(
			frappe.get_doc("Microbiology Isolate", {"lab_sample_id": "W2"}).susceptibility[0].mic, ">=32"
		)

	def test_conflicting_results_and_bad_values_are_row_errors(self):
		w = self.ward
		content = _csv(
			[
				LONG_HEADER,
				f"C1,kpn,BN1,1960,{w},Máu,03/08/2026,MEM,R,",
				"C1,kpn,,,,,,MEM,S,",
				"C2,kpn,BN2,1800,Khoa không có,Máu,03/08/2099,MEM,X,",
			]
		)
		result = importer.check(imports.KEY, content, profile=self.long)
		codes = {(i["row"], i["code"], i["field"]) for i in result["issues"]}
		self.assertIn((3, "ANTIBIOTIC_CONFLICT", "antibiotic"), codes)
		self.assertTrue(
			{(4, "DEPARTMENT_NOT_FOUND", "department"), (4, "VALUE_INVALID", "collected_on")} <= codes
		)
		self.assertIn((4, "VALUE_INVALID", "birth_year"), codes)
		self.assertIn((4, "VALUE_INVALID", "result"), codes)

	@bru("BRU-HAI-005")
	def test_only_r11_can_import(self):
		kind = importer.get_kind(imports.KEY)
		self.assertEqual(tuple(kind.roles), ("TC R11", "System Manager"))
		for role, allowed in (("TC R11", True), ("TC R13", False), ("TC R12", False), ("TC R01", False)):
			frappe.set_user(make_user(f"micro-imp-{role[-2:]}@example.com", [role]))
			self.assertEqual(importer.can_import(kind), allowed, role)
			frappe.set_user("Administrator")

	def test_cell_parser(self):
		self.assertEqual(imports.parse_cell("R (>8)"), ("R", ">8"))
		self.assertEqual(imports.parse_cell("s"), ("S", None))
		self.assertEqual(imports.parse_cell("≥32 R"), ("R", "≥32"))
		self.assertEqual(imports.parse_cell("16"), (None, "16"))
		self.assertTrue(imports.is_extra("ab:MEM"))
		self.assertFalse(imports.is_extra("ab:"))
