"""Hồ sơ ánh xạ cột cho nhập file ngoài (FEAT-056 AC-10, AC-11; FR-M9-28, FR-M9-28.1; F-21; EI-SW-010; plan D2).

Dùng một loại import giả (mẫu số ngày theo khoa) ghi vào bộ nhớ: FEAT-056 chỉ làm cơ chế, loại thật ở FEAT 062/064/066/067.
"""

import unicodedata
from unittest.mock import patch

import frappe

from tracecore.core import importer
from tracecore.core.importer import Column, ImportKind, Issue
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix

KEY = "tc_test_census"
STORE: dict = {}


def _validate(unit):
	values = unit[0].values
	if values.get("patients") is not None and values["patients"] < 0:
		return [Issue(unit[0].row, "VALUE_INVALID", "patients", "patients < 0")]
	return []


def _write(unit):
	values = unit[0].values
	STORE[f"{values['ward']}|{values['census_date']}"] = values
	# không có bản ghi DB thật để Import Batch Row liên kết


def _cp1258(text):
	"""Mã hóa như Windows-1258 thật: chữ có mũ/móc/trăng dựng sẵn, dấu thanh là ký tự tổ hợp."""
	out = b""
	for char in text:
		try:
			out += char.encode("cp1258")
			continue
		except UnicodeEncodeError:
			pass
		parts = unicodedata.normalize("NFD", char)
		base, marks = parts[0], list(parts[1:])
		for index, mark in enumerate(marks):
			combined = unicodedata.normalize("NFC", base + mark)
			try:
				combined.encode("cp1258")
			except UnicodeEncodeError:
				continue
			base = combined
			del marks[index]
			break
		out += (base + "".join(marks)).encode("cp1258")
	return out


FAKE_KIND = ImportKind(
	key=KEY,
	label="Daily ward census (test)",
	doctype="Import Batch",
	columns=[
		Column("census_date", "Census Date", required=True, kind="date"),
		Column("ward", "Ward", required=True),
		Column("patients", "Patients", required=True, kind="int"),
	],
	code_field="ward",
	code_of=lambda v: f"{v.get('ward')}|{v.get('census_date')}"
	if v.get("ward") and v.get("census_date")
	else "",
	exists=lambda code: code in STORE,
	validate=_validate,
	write=_write,
	roles=("TC R10", "TC R11", "System Manager"),
	can_import=lambda: True,
)


def _profile(name="HIS mẫu số", file_format="CSV", encoding="UTF-8", date_format="yyyy-mm-dd", delimiter=","):
	if frappe.db.exists("Import Mapping Profile", name):
		frappe.db.delete("Import Mapping Profile Column", {"parent": name})
		frappe.db.delete("Import Mapping Profile", {"name": name})
	return frappe.get_doc(
		{
			"doctype": "Import Mapping Profile",
			"profile_name": name,
			"import_kind": KEY,
			"file_format": file_format,
			"encoding": encoding,
			"delimiter": delimiter,
			"date_format": date_format,
			"columns": [
				{"source_column": "Ngày", "target_field": "census_date"},
				{"source_column": "Khoa", "target_field": "ward"},
				{"source_column": "Số NB", "target_field": "patients"},
			],
		}
	).insert(ignore_permissions=True)


def _csv(rows, encoding="utf-8", delimiter=","):
	lines = [delimiter.join(["Ngày", "Khoa", "Số NB"])] + [delimiter.join(map(str, r)) for r in rows]
	text = "\n".join(lines) + "\n"
	return _cp1258(text) if encoding == "cp1258" else text.encode(encoding)


def _five_hundred_rows_three_bad():
	rows = []
	for n in range(500):
		day = f"2026-10-{n % 28 + 1:02d}"
		ward = f"Khoa {n // 28:02d}"
		patients = n % 40
		if n in (10, 250, 499):
			patients = "abc"  # lỗi giá trị ô
		rows.append((day, ward, patients))
	return rows


class TestImportMappingProfile(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		STORE.clear()
		kinds = {**importer.kinds(), KEY: FAKE_KIND}
		self.kinds = patch("tracecore.core.importer.kinds", return_value=kinds)
		self.kinds.start()
		self.addCleanup(self.kinds.stop)

	def test_profile_validates_kind_and_target_fields(self):
		profile = _profile()
		self.assertEqual(profile.name, "HIS mẫu số")
		bad = frappe.get_doc(
			{
				"doctype": "Import Mapping Profile",
				"profile_name": "Sai cột",
				"import_kind": KEY,
				"columns": [{"source_column": "X", "target_field": "not_a_field"}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			bad.insert(ignore_permissions=True)
		dup = frappe.get_doc(
			{
				"doctype": "Import Mapping Profile",
				"profile_name": "Trùng đích",
				"import_kind": KEY,
				"columns": [
					{"source_column": "A", "target_field": "ward"},
					{"source_column": "B", "target_field": "ward"},
				],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			dup.insert(ignore_permissions=True)
		unknown = frappe.get_doc(
			{"doctype": "Import Mapping Profile", "profile_name": "Không loại", "import_kind": "no_such_kind"}
		)
		with self.assertRaises(frappe.ValidationError):
			unknown.insert(ignore_permissions=True)

	def test_csv_columns_renamed_and_dates_parsed_by_profile(self):
		profile = _profile()
		result = importer.check(KEY, _csv([("2026-11-02", "Hồi sức", 18)]), profile=profile.name)
		self.assertEqual((result["total"], result["valid"], result["issues"]), (1, 1, []))

	def test_without_profile_csv_is_rejected_as_before(self):
		with self.assertRaises(importer.ImportFileError):
			importer.check(KEY, _csv([("2026-11-02", "Hồi sức", 18)]))

	def test_windows_1258_and_semicolon(self):
		profile = _profile(
			name="HIS cp1258", encoding="Windows-1258", delimiter=";", date_format="dd/mm/yyyy"
		)
		content = _csv([("02/11/2026", "Sơ sinh", 9)], encoding="cp1258", delimiter=";")
		result = importer.check(KEY, content, profile=profile.name)
		self.assertEqual(result["valid"], 1, result["issues"])

	def test_profile_must_match_kind(self):
		profile = _profile()
		other = ImportKind(**{**FAKE_KIND.__dict__, "key": "tc_test_other"})
		with patch("tracecore.core.importer.kinds", return_value={KEY: FAKE_KIND, other.key: other}):
			with self.assertRaises(importer.ImportFileError):
				importer.check(other.key, _csv([("2026-11-02", "Hồi sức", 18)]), profile=profile.name)
			with self.assertRaises(importer.ImportFileError):
				importer.check(KEY, _csv([("2026-11-02", "Hồi sức", 18)]), profile="Không có hồ sơ này")

	def test_500_rows_with_3_errors_writes_497_and_reimport_creates_none(self):
		"""FR-M9-28.1: 497 dòng ghi, 3 dòng lỗi kèm số dòng; nhập lại cùng file không tạo trùng."""
		profile = _profile()
		content = _csv(_five_hundred_rows_three_bad())
		with patch("tracecore.core.importer.BACKGROUND_ROWS", 10_000):
			first = importer.run(KEY, content, None, profile=profile.name)
			batch = frappe.get_doc("Import Batch", first)
			self.assertEqual((batch.created, batch.failed, batch.skipped), (497, 3, 0))
			self.assertEqual(batch.mapping_profile, profile.name)
			self.assertEqual(sorted(r.row_no for r in batch.rows if r.result == "Error"), [12, 252, 501])
			second = frappe.get_doc("Import Batch", importer.run(KEY, content, None, profile=profile.name))
		self.assertEqual((second.created, second.skipped, second.failed), (0, 497, 3))
		self.assertEqual(len(STORE), 497)

	def test_api_lists_profiles_and_reads_csv_upload(self):
		from tracecore.v1 import imports as api

		profile = _profile()
		self.assertEqual([row.name for row in api.profiles(KEY)["profiles"]], [profile.name])
		content = _csv([("2026-11-02", "Hồi sức", 18)])
		with patch("tracecore.core.importer.read_upload", return_value=content) as read:
			result = api.check(KEY, "/private/files/census.csv", profile=profile.name)
		self.assertTrue(result["ok"])
		self.assertEqual(result["valid"], 1)
		read.assert_called_with("/private/files/census.csv", extensions=(".csv",))

	def test_permission_matrix(self):
		assert_permission_matrix(self, "Import Mapping Profile")
