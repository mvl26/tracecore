"""Mở rộng khung import cho file vi sinh (FEAT-067; A-136 Q6, Q7; FR-M14-01; UC-51 E3).

- ``group_of``: gom nhiều dòng thành một đơn vị theo khóa nhiều cột (lab_sample_id, organism);
- ``extra_columns``: cột không khai báo (cột kháng sinh dạng rộng WHONET, đích ``ab:<MÃ>``) vẫn được đọc;
- ``ignored_columns``: cột họ tên bị bỏ, cảnh báo, không chặn file;
- ``purge_file``: file nguồn có mã người bệnh bị xóa sau khi ghi sổ (ADR-010 mở rộng).

Dùng loại import giả ghi vào bộ nhớ như ``test_importer_profile``.
"""

from unittest.mock import patch

import frappe

from tracecore.core import importer
from tracecore.core.importer import Column, ImportKind
from tracecore.tests.utils import IsolatedTestCase

KEY = "tc_test_culture"
STORE: dict = {}
BATCHES: list = []


def _key(values):
	return f"{values.get('sample') or ''}|{(values.get('bug') or '').upper()}"


def _write(unit):
	STORE[_key(unit[0].values)] = [row.values for row in unit]
	BATCHES.append(frappe.flags.tc_import_batch)


FAKE_KIND = ImportKind(
	key=KEY,
	label="Culture results (test)",
	doctype="Import Batch",
	columns=[
		Column("sample", "Sample", required=True),
		Column("bug", "Bug", required=True),
		Column("ward", "Ward"),
		Column("drug", "Drug"),
		Column("sir", "SIR"),
	],
	code_field="sample",
	code_of=_key,
	group_of=_key,
	group_fields=("ward",),
	exists=lambda code: code in STORE,
	validate=lambda unit: [],
	write=_write,
	extra_columns=lambda header: str(header or "").startswith("ab:"),
	ignored_columns=("Patient Name", "Họ tên"),
	purge_file=True,
	roles=("TC R11", "System Manager"),
	can_import=lambda: True,
)


def _csv(lines):
	return ("\n".join(lines) + "\n").encode("utf-8")


class TestImporterWide(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		STORE.clear()
		BATCHES.clear()
		patcher = patch.object(importer, "kinds", return_value={KEY: FAKE_KIND})
		patcher.start()
		self.addCleanup(patcher.stop)
		name = "Vi sinh thử"
		if frappe.db.exists("Import Mapping Profile", name):
			frappe.delete_doc("Import Mapping Profile", name, force=True, ignore_permissions=True)
		self.profile = frappe.get_doc(
			{
				"doctype": "Import Mapping Profile",
				"profile_name": name,
				"import_kind": KEY,
				"file_format": "CSV",
				"encoding": "UTF-8",
				"delimiter": ",",
				"date_format": "dd/mm/yyyy",
				"columns": [
					{"source_column": "SPEC_NUM", "target_field": "sample"},
					{"source_column": "ORGANISM", "target_field": "bug"},
					{"source_column": "WARD", "target_field": "ward"},
					{"source_column": "MEM_NM", "target_field": "ab:MEM"},
					{"source_column": "CIP_ND5", "target_field": "ab:CIP"},
				],
			}
		).insert(ignore_permissions=True)

	def test_profile_accepts_extra_target_but_rejects_unknown(self):
		self.profile.append("columns", {"source_column": "XYZ", "target_field": "nonsense"})
		with self.assertRaises(frappe.ValidationError):
			self.profile.save(ignore_permissions=True)

	def test_wide_columns_are_read_into_extra(self):
		content = _csv(["SPEC_NUM,ORGANISM,WARD,MEM_NM,CIP_ND5,OTHER", "L1,kpn,ICU,R (>8),S,zzz"])
		rows, issues = importer.parse(FAKE_KIND, content, importer.load_profile(self.profile.name, KEY))
		self.assertEqual(issues, [])
		self.assertEqual(rows[0].values["_extra"], {"ab:MEM": "R (>8)", "ab:CIP": "S"})

	def test_rows_grouped_by_multi_column_key(self):
		content = _csv(
			[
				"SPEC_NUM,ORGANISM,WARD,MEM_NM",
				"L1,kpn,ICU,R",
				"L1,KPN,,S",
				"L1,eco,ICU,S",
				"L2,kpn,ICU,S",
			]
		)
		result = importer.check(KEY, content, profile=self.profile.name)
		self.assertEqual((result["total"], result["units"], result["valid"]), (4, 3, 3))

	def test_group_conflict_reports_the_row(self):
		content = _csv(["SPEC_NUM,ORGANISM,WARD", "L1,kpn,ICU", "L1,kpn,ER"])
		result = importer.check(KEY, content, profile=self.profile.name)
		self.assertEqual([(i["row"], i["code"]) for i in result["issues"]], [(3, "GROUP_CONFLICT")])

	def test_name_column_is_ignored_with_a_warning(self):
		content = _csv(["SPEC_NUM,ORGANISM,Họ tên,Patient name", "L1,kpn,Nguyễn Văn A,Nguyen Van A"])
		profile = importer.load_profile(self.profile.name, KEY)
		warnings = []
		rows, _issues = importer.parse(FAKE_KIND, content, profile, warnings=warnings)
		self.assertNotIn("Nguyễn Văn A", frappe.as_json([row.values for row in rows]))
		self.assertEqual(len(warnings), 1)
		result = importer.check(KEY, content, profile=self.profile.name)
		self.assertEqual(result["valid"], 1)
		self.assertEqual(len(result["warnings"]), 1)

	def test_run_twice_creates_nothing_the_second_time_and_passes_the_batch(self):
		content = _csv(["SPEC_NUM,ORGANISM,MEM_NM", "L1,kpn,R", "L2,eco,S"])
		first = frappe.get_doc("Import Batch", importer.run(KEY, content, None, profile=self.profile.name))
		self.assertEqual((first.created, first.skipped), (2, 0))
		self.assertEqual(set(BATCHES), {first.name})
		second = frappe.get_doc("Import Batch", importer.run(KEY, content, None, profile=self.profile.name))
		self.assertEqual((second.created, second.skipped), (0, 2))
		self.assertIsNone(frappe.flags.tc_import_batch)

	def test_source_file_is_deleted_after_a_purging_import(self):
		content = _csv(["SPEC_NUM,ORGANISM", "L9,kpn"])
		file = frappe.get_doc(
			{"doctype": "File", "file_name": "vi-sinh.csv", "is_private": 1, "content": content}
		).insert(ignore_permissions=True)
		batch = frappe.get_doc(
			"Import Batch", importer.run(KEY, content, file.file_url, profile=self.profile.name)
		)
		self.assertEqual(batch.created, 1)
		self.assertFalse(frappe.db.exists("File", file.name))
		self.assertFalse(batch.file)
