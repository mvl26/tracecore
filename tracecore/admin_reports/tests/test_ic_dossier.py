"""Gói hồ sơ KSNK cho đoàn kiểm tra: ZIP PDF + Excel + manifest, mã BN che, dấu Tạm, chỉ R01 (FEAT-074; FR-M9-30,
FR-M9-30.1; BRU-RPT-002; UC-57 bước 8, A1, E5; A-152)."""

import hashlib
import io
import json
import zipfile
from unittest.mock import patch

import frappe
from openpyxl import load_workbook

from tracecore.admin_reports import archive, ic_dossier, indicator
from tracecore.admin_reports.tests.test_archive import blank_pdf
from tracecore.core.dossier import DossierSection, ExportField
from tracecore.tests import factories as f
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Department", "User", "Employee"]
MONTHS = ("2026-01", "2026-02")


def dossier_export(**fields):
	values = {
		"doctype": "Archive Export",
		"scope_type": "IC Dossier",
		"from_date": "2026-01-01",
		"to_date": "2026-02-28",
	}
	values.update(fields)
	with patch("frappe.enqueue"):
		return frappe.get_doc(values).insert()


def lock(month, locked=1):
	name = f"KY-{month}"
	if frappe.db.exists("IC Reporting Period", name):
		frappe.db.set_value("IC Reporting Period", name, "locked", locked)
		return
	frappe.get_doc(
		{"doctype": "IC Reporting Period", "name": name, "month": month, "locked": locked}
	).db_insert()


def value_row(period, department=None, value=80.0, code="HH-TEST"):
	doc = frappe.get_doc(
		{
			"doctype": "IC Indicator Value",
			"indicator": code,
			"indicator_name": "Tuân thủ vệ sinh tay (test)",
			"period": period,
			"department": department,
			"value": value,
			"numerator": 8,
			"denominator": 10,
			"sample_size": 10,
			"locked": 1,
		}
	)
	doc.db_insert()
	return doc


class DossierCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")

	def build(self, doc):
		with (
			patch("frappe.utils.pdf.get_pdf", side_effect=blank_pdf),
			patch.object(indicator, "compute_period"),
		):
			archive.build(doc.name)
		return frappe.get_doc("Archive Export", doc.name)

	def unzip(self, doc):
		content = frappe.get_doc("File", {"file_url": doc.archive_file}).get_content()
		return zipfile.ZipFile(io.BytesIO(content)), content


class TestIcDossier(DossierCase):
	def test_package_has_pdf_excel_and_manifest(self):
		value_row("2026-01")
		value_row("2025-12", value=10.0)  # ngoài dải
		doc = self.build(dossier_export())
		self.assertEqual(doc.status, "Completed", doc.error)
		self.assertEqual(doc.ic_months, "2026-01..2026-02")
		zf, content = self.unzip(doc)
		self.assertEqual(set(zf.namelist()), {"ksnk_dossier.pdf", "ksnk_dossier.xlsx", "manifest.json"})
		self.assertEqual(hashlib.sha256(content).hexdigest(), doc.sha256)
		manifest = json.loads(zf.read("manifest.json"))
		self.assertEqual(manifest["scope"]["type"], "IC Dossier")
		self.assertEqual(manifest["scope"]["months"], list(MONTHS))
		self.assertIn("indicators", manifest["scope"]["sections"])
		self.assertRegex(manifest["generated_at"], r"[+-]\d{2}:\d{2}$")
		for item in manifest["files"]:
			self.assertEqual(item["sha256"], hashlib.sha256(zf.read(item["name"])).hexdigest())
		book = load_workbook(io.BytesIO(zf.read("ksnk_dossier.xlsx")), read_only=True)
		self.assertGreaterEqual(len(book.sheetnames), 8)
		rows = list(book[book.sheetnames[0]].iter_rows(values_only=True))
		periods = {row[2] for row in rows[1:]}
		self.assertIn("2026-01", periods)
		self.assertNotIn("2025-12", periods)

	def test_real_pdf_and_excel_of_a_small_dossier(self):
		value_row("2026-01")
		doc = dossier_export(ic_sections=json.dumps(["indicators"]))
		with patch.object(indicator, "compute_period"):
			files, provisional, scope = ic_dossier.build_files(doc, "2026-03-01T08:00:00+07:00")
		names = {name: content for name, content, _rows in files}
		self.assertTrue(names["ksnk_dossier.pdf"].startswith(b"%PDF"))
		self.assertEqual(provisional, 1)
		self.assertEqual(scope["section_rows"]["indicators"], 1)

	def test_chosen_sections_only(self):
		doc = self.build(dossier_export(ic_sections=json.dumps(["indicators", "exposures"])))
		zf, _content = self.unzip(doc)
		book = load_workbook(io.BytesIO(zf.read("ksnk_dossier.xlsx")), read_only=True)
		self.assertEqual(len(book.sheetnames), 2)
		self.assertEqual(
			json.loads(zf.read("manifest.json"))["scope"]["sections"], ["indicators", "exposures"]
		)

	def test_unknown_section_or_bad_months_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			dossier_export(ic_sections=json.dumps(["zzz"]))
		with self.assertRaises(frappe.ValidationError):
			dossier_export(from_date="2026-03-01", to_date="2026-01-31")
		with self.assertRaises(frappe.ValidationError):
			dossier_export(to_date=None)

	def test_dates_are_widened_to_whole_months(self):
		doc = dossier_export(from_date="2026-01-15", to_date="2026-02-03")
		self.assertEqual((str(doc.from_date), str(doc.to_date)), ("2026-01-01", "2026-02-28"))
		self.assertEqual(doc.inc_loads, 0)

	def test_provisional_until_every_month_is_locked(self):
		lock("2026-01")
		lock("2026-02", 0)
		doc = self.build(dossier_export())
		self.assertEqual(doc.provisional, 1)
		self.assertTrue(json.loads(doc.manifest)["provisional"])
		lock("2026-02")
		self.assertEqual(self.build(dossier_export()).provisional, 0)

	def test_unlocked_months_are_computed_provisionally(self):
		lock("2026-01")
		with (
			patch("frappe.utils.pdf.get_pdf", side_effect=blank_pdf),
			patch.object(indicator, "compute_period") as compute,
		):
			archive.build(dossier_export().name)
		self.assertEqual([call.args[0] for call in compute.call_args_list], ["2026-02"])

	def test_pdf_cover_shows_provisional_and_row_counts(self):
		value_row("2026-01")
		html = ic_dossier.render_html(
			ic_dossier.collect(dossier_export(ic_sections=json.dumps(["indicators"]))),
			provisional=True,
			generated_at="2026-03-01T08:00:00+07:00",
			requested_by="Administrator",
		)
		self.assertIn(frappe._("PROVISIONAL"), html)
		self.assertIn("01/2026", html)
		self.assertIn("HH-TEST", html)

	@bru("BRU-RPT-002")
	def test_a_section_leaking_a_patient_code_blocks_the_export(self):
		leaky = DossierSection(
			key="leaky",
			label="Leaky",
			order=1,
			fields=[ExportField("patient_code_masked", "Patient Code")],
			rows=lambda ctx: [{"patient_code_masked": "BN12345678"}],
		)
		with patch("tracecore.core.dossier.extension.run", return_value=[[leaky]]):
			doc = self.build(dossier_export())
		self.assertEqual(doc.status, "Failed")
		self.assertFalse(doc.archive_file)
		self.assertIn("leaky", doc.error)

	@bru("BRU-RPT-002")
	def test_only_r01_and_never_full_patient_codes(self):
		r10 = make_user("dossier-r10@example.com", ["TC R10"])
		r01 = make_user("dossier-r01@example.com", ["TC R01"])
		frappe.set_user(r10)
		with self.assertRaises(frappe.ValidationError):
			dossier_export()
		frappe.set_user(r01)
		with self.assertRaises(frappe.ValidationError):
			dossier_export(full_patient_code=1, patient_code_reason="Đoàn kiểm tra")
		doc = dossier_export()
		self.assertEqual(doc.requested_by, "dossier-r01@example.com")

	def test_indicator_rows_by_department(self):
		department = f.make_department("Khoa gói hồ sơ test")
		value_row("2026-02", department=department, value=50.0)
		ctx = frappe._dict(months=list(MONTHS), years=[2026])
		rows = ic_dossier.indicator_rows(ctx)
		self.assertIn((department, 50.0), {(row["department"], row["value"]) for row in rows})


class TestIcDossierRpc(DossierCase):
	def test_rpc_sections_export_and_list(self):
		from tracecore.v1 import archive as api

		r13 = make_user("dossier-api-r13@example.com", ["TC R13"])
		frappe.set_user(make_user("dossier-api-r01@example.com", ["TC R01"]))
		keys = [row["key"] for row in api.ic_dossier_sections()["sections"]]
		self.assertIn("indicators", keys)
		with patch("frappe.enqueue"):
			result = api.ic_dossier_export(
				from_month="2026-01", to_month="2026-02", sections=json.dumps(["indicators"])
			)
		self.assertTrue(result["ok"])
		listed = api.ic_dossiers()["dossiers"]
		self.assertEqual(listed[0]["name"], result["name"])
		self.assertEqual(listed[0]["months"], "2026-01..2026-02")
		frappe.set_user(r13)
		with self.assertRaises(frappe.PermissionError):
			api.ic_dossier_sections()
		with self.assertRaises(frappe.PermissionError):
			api.ic_dossiers()
