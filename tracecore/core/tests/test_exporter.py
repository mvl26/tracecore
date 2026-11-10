"""Khung xuất báo cáo theo hồ sơ ánh xạ cột `Report Export Profile` (FEAT-064; FR-M13-12, 12.1; BRU-RPT-002; UC-49 E3;
A-147 Q1)."""

import csv
import io
from unittest.mock import patch

import frappe
from frappe.utils import getdate
from openpyxl import load_workbook

from tracecore.core import exporter
from tracecore.core.errors import BlockedError
from tracecore.tests.utils import IsolatedTestCase, bru

KIND = exporter.ExportKind(
	key="test_kind",
	label="Test report",
	fields=[
		exporter.ExportField("code", "Code"),
		exporter.ExportField("day", "Day", kind="date"),
		exporter.ExportField("count", "Count", kind="int"),
		exporter.ExportField("flag", "Flag", kind="check"),
		exporter.ExportField("patient_code_masked", "Patient Code"),
	],
	rows=lambda filters: [
		{
			"code": "A-1",
			"day": getdate("2026-10-28"),
			"count": 3,
			"flag": 1,
			"patient_code_masked": "***6612",
		},
		{"code": "Đ-2", "day": None, "count": None, "flag": 0, "patient_code_masked": "***0001"},
	],
	roles=("TC R11", "System Manager"),
)


def _profile(name="Mẫu Sở Y tế thử", fmt="CSV", columns=(("count", "SO LUONG"), ("code", "MA")), **extra):
	if frappe.db.exists(exporter.PROFILE_DOCTYPE, name):
		frappe.delete_doc(exporter.PROFILE_DOCTYPE, name, force=True, ignore_permissions=True)
	return frappe.get_doc(
		{
			"doctype": exporter.PROFILE_DOCTYPE,
			"profile_name": name,
			"export_kind": KIND.key,
			"file_format": fmt,
			"columns": [{"source_field": a, "header": b} for a, b in columns],
			**extra,
		}
	).insert(ignore_permissions=True)


class TestExporter(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		patcher = patch.object(exporter, "kinds", return_value={KIND.key: KIND})
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_default_columns_excel(self):
		name, content, _type = exporter.build(KIND.key, {})
		self.assertTrue(name.endswith(".xlsx"))
		sheet = load_workbook(io.BytesIO(content)).active
		rows = list(sheet.iter_rows(values_only=True))
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[1][0:3], ("A-1", "28/10/2026", 3))

	def test_profile_reorders_and_renames_csv(self):
		profile = _profile(
			delimiter=";",
			encoding="Windows-1258",
			date_format="yyyy-mm-dd",
			columns=(("count", "SO LUONG"), ("code", "MA"), ("day", "NGAY")),
		)
		name, content, _type = exporter.build(KIND.key, {}, profile.name)
		self.assertTrue(name.endswith(".csv"))
		rows = list(csv.reader(io.StringIO(content.decode("cp1258")), delimiter=";"))
		self.assertEqual(rows[0], ["SO LUONG", "MA", "NGAY"])
		self.assertEqual(rows[1], ["3", "A-1", "2026-10-28"])
		self.assertEqual(rows[2], ["", "Đ-2", ""])

	@bru("BRU-RPT-002")
	def test_profile_with_clear_patient_code_or_name_is_blocked(self):
		for field in ("patient_code", "patient_name", "ho_ten"):
			with self.assertRaises(BlockedError) as caught:
				_profile(columns=((field, "MA BN"),))
			self.assertEqual(caught.exception.block.code, "EXPORT_COLUMN_FORBIDDEN")

	def test_unknown_column_or_kind_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			_profile(columns=(("nope", "X"),))
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": exporter.PROFILE_DOCTYPE,
					"profile_name": "Sai loại",
					"export_kind": "nope",
					"columns": [{"source_field": "code", "header": "MA"}],
				}
			).insert(ignore_permissions=True)

	def test_profile_of_other_kind_rejected(self):
		profile = _profile()
		frappe.db.set_value(exporter.PROFILE_DOCTYPE, profile.name, "export_kind", "other")
		with self.assertRaises(frappe.ValidationError):
			exporter.build(KIND.key, {}, profile.name)

	@bru("BRU-RPT-002")
	def test_forbidden_field_in_kind_rejected_at_build(self):
		bad = exporter.ExportKind(
			key="bad", label="Bad", fields=[exporter.ExportField("patient_code", "Code")], rows=lambda f: []
		)
		with patch.object(exporter, "kinds", return_value={"bad": bad}):
			with self.assertRaises(BlockedError):
				exporter.build("bad", {})

	def test_role_required(self):
		user = "export-r08@test.local"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "R08"}).insert(
				ignore_permissions=True
			)
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			exporter.build(KIND.key, {})
