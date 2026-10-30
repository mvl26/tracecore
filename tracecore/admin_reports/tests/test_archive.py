"""Xuất hồ sơ tiệt khuẩn lưu trữ: ZIP PDF + CSV + manifest SHA-256 (FEAT-012, FR-M9-12, OTH-RET-001, UC-39, A-58)."""

import csv
import hashlib
import io
import json
import zipfile
from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime, today

from tracecore.admin_reports import archive
from tracecore.admin_reports.tests.test_sterilization_log import indicator, make_released_load
from tracecore.tests import factories as f
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
PATIENT = "BN12345678"


def blank_pdf(*_args, **_kwargs):
	from pypdf import PdfWriter

	writer, out = PdfWriter(), io.BytesIO()
	writer.add_blank_page(10, 10)
	writer.write(out)
	return out.getvalue()


def issue(pack, department):
	doc = frappe.get_doc(
		{
			"doctype": "Issue Note",
			"department": department,
			"issued_at": now_datetime(),
			"pack_count": 1,
			"recipient_name": "Điều dưỡng khoa",
			"packs": [{"pack": pack.name, "set_unit": pack.set_unit, "set_type": pack.set_type}],
		}
	)
	doc.flags.tc_issuing = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def usage(pack, department, code=PATIENT):
	doc = frappe.get_doc(
		{
			"doctype": "Usage Record",
			"pack": pack.name,
			"set_unit": pack.set_unit,
			"department": department,
			"used_at": now_datetime(),
			"patient_code": code,
			"surgery_code": "PT-01",
		}
	)
	doc.flags.tc_usage = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def export(**fields):
	values = {
		"doctype": "Archive Export",
		"scope_type": "Period",
		"from_date": add_days(today(), -7),
		"to_date": today(),
	}
	values.update(fields)
	with patch("frappe.enqueue"):
		return frappe.get_doc(values).insert()


def unzip(doc):
	content = frappe.get_doc("File", {"file_url": doc.archive_file}).get_content()
	return zipfile.ZipFile(io.BytesIO(content)), content


def read_csv(zf, name):
	return list(csv.DictReader(io.StringIO(zf.read(name).decode("utf-8-sig"))))


class ArchiveCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")
		self.department = f.make_department("Khoa lưu trữ test")
		self.load = make_released_load()
		indicator(self.load, "biological", "Pass", "BI-77")
		self.pack = frappe.get_doc("Pack", self.load.packs[0].pack)
		self.issue = issue(self.pack, self.department)
		self.usage = usage(self.pack, self.department)

	def build(self, doc):
		with patch("frappe.utils.pdf.get_pdf", side_effect=blank_pdf):
			archive.build(doc.name)
		return frappe.get_doc("Archive Export", doc.name)


class TestArchiveExport(ArchiveCase):
	def test_period_package_has_pdfs_csvs_and_a_manifest_with_checksums(self):
		doc = self.build(export())
		self.assertEqual(doc.status, "Completed", doc.error)
		zf, content = unzip(doc)
		self.assertEqual(doc.sha256, hashlib.sha256(content).hexdigest())
		names = set(zf.namelist())
		for name in (
			"manifest.json",
			"sterilization_log.pdf",
			"ksnk_summary.pdf",
			"loads.csv",
			"indicators.csv",
			"machine_data.csv",
			"load_packs.csv",
			"issues.csv",
			"usage.csv",
			"audit.csv",
		):
			self.assertIn(name, names)
		manifest = json.loads(zf.read("manifest.json"))
		self.assertEqual(manifest["export"], doc.name)
		self.assertEqual(manifest["generated_by"], "Administrator")
		self.assertIn("+07:00", manifest["generated_at"])
		for entry in manifest["files"]:
			self.assertEqual(entry["sha256"], hashlib.sha256(zf.read(entry["name"])).hexdigest())
		self.assertIn(self.load.name, {row["load"] for row in read_csv(zf, "loads.csv")})
		self.assertIn("BI-77", {row["lot"] for row in read_csv(zf, "indicators.csv")})
		self.assertIn("134", {row["value"] for row in read_csv(zf, "machine_data.csv")})
		self.assertIn(self.issue.name, {row["issue_note"] for row in read_csv(zf, "issues.csv")})
		audit_refs = {row["ref_name"] for row in read_csv(zf, "audit.csv")}
		self.assertIn(self.issue.name, audit_refs)
		self.assertTrue(frappe.get_doc("File", {"file_url": doc.archive_file}).is_private)

	def test_package_with_real_pdfs(self):
		doc = export()
		archive.build(doc.name)  # wkhtmltopdf thật, không giả lập
		doc.reload()
		self.assertEqual(doc.status, "Completed", doc.error)
		zf, _content = unzip(doc)
		self.assertTrue(zf.read("sterilization_log.pdf").startswith(b"%PDF"))
		self.assertTrue(zf.read("ksnk_summary.pdf").startswith(b"%PDF"))

	def test_patient_code_is_masked_by_default(self):
		zf, _content = unzip(self.build(export()))
		codes = {row["patient_code"] for row in read_csv(zf, "usage.csv")}
		self.assertNotIn(PATIENT, codes)
		self.assertIn("BN1****678", codes)

	def test_r01_with_a_reason_exports_full_codes_and_it_is_audited(self):
		frappe.set_user(make_user("archive-r01@example.com", ["TC R01"]))
		with self.assertRaises(frappe.ValidationError):
			export(full_patient_code=1)
		doc = export(full_patient_code=1, patient_code_reason="Đoàn thanh tra yêu cầu")
		frappe.set_user("Administrator")
		zf, _content = unzip(self.build(doc))
		self.assertIn(PATIENT, {row["patient_code"] for row in read_csv(zf, "usage.csv")})
		self.assertTrue(frappe.db.exists("Audit Log", {"action": "View Patient Code", "ref_name": doc.name}))

	def test_r10_cannot_export_full_codes(self):
		frappe.set_user(make_user("archive-r10@example.com", ["TC R10"]))
		with self.assertRaises(frappe.ValidationError):
			export(full_patient_code=1, patient_code_reason="Lý do")

	def test_single_load_scope_has_only_that_load(self):
		other = make_released_load()
		zf, _content = unzip(self.build(export(scope_type="Load", sterilization_load=self.load.name)))
		loads = {row["load"] for row in read_csv(zf, "loads.csv")}
		self.assertEqual(loads, {self.load.name})
		self.assertNotIn(other.name, loads)
		self.assertNotIn("ksnk_summary.pdf", zf.namelist())

	def test_recall_scope_follows_the_recall_load(self):
		recall = frappe.get_doc(
			{
				"doctype": "Recall Order",
				"trigger": "Opened Manually",
				"sterilization_load": self.load.name,
				"reason": "Test",
				"opened_at": now_datetime(),
				"packs": [{"pack": self.pack.name, "set_unit": self.pack.set_unit, "load": self.load.name}],
			}
		)
		recall.flags.tc_recall = True
		recall.flags.ignore_mandatory = True
		recall.insert(ignore_permissions=True)
		make_released_load()
		zf, _content = unzip(self.build(export(scope_type="Recall Order", recall_order=recall.name)))
		self.assertEqual({row["load"] for row in read_csv(zf, "loads.csv")}, {self.load.name})

	def test_scope_choices_limit_the_files(self):
		zf, _content = unzip(self.build(export(inc_usage=0, inc_audit=0)))
		self.assertNotIn("usage.csv", zf.namelist())
		self.assertNotIn("audit.csv", zf.namelist())

	def test_scope_needs_its_target_and_something_to_export(self):
		for fields in (
			{"from_date": None},
			{"from_date": today(), "to_date": add_days(today(), -1)},
			{"scope_type": "Load"},
			{"scope_type": "Recall Order"},
			{
				"inc_loads": 0,
				"inc_indicators": 0,
				"inc_machine_data": 0,
				"inc_issues": 0,
				"inc_usage": 0,
				"inc_audit": 0,
			},
		):
			with self.assertRaises(frappe.ValidationError, msg=fields):
				export(**fields)

	def test_creation_queues_a_long_job_and_records_the_requester(self):
		with patch("frappe.enqueue") as enqueue:
			doc = frappe.get_doc(
				{
					"doctype": "Archive Export",
					"scope_type": "Period",
					"from_date": today(),
					"to_date": today(),
				}
			).insert()
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		self.assertEqual((doc.status, doc.requested_by), ("Queued", "Administrator"))

	def test_export_cannot_be_changed_or_deleted(self):
		doc = export()
		doc.to_date = add_days(today(), -1)
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Archive Export", doc.name)

	def test_failure_is_recorded_and_notified(self):
		doc = export()
		with patch.object(archive, "_files", side_effect=RuntimeError("boom")):
			archive.build(doc.name)
		doc.reload()
		self.assertEqual(doc.status, "Failed")
		self.assertIn("boom", doc.error)
		self.assertTrue(
			frappe.db.exists("Notification Log", {"for_user": "Administrator", "document_name": doc.name})
		)

	def test_provisional_until_the_period_is_locked(self):
		frappe.db.set_single_value("TraceCore Settings", "report_locked_until", None)
		self.assertEqual(self.build(export()).provisional, 1)
		frappe.db.set_single_value("TraceCore Settings", "report_locked_until", today())
		self.assertEqual(self.build(export()).provisional, 0)

	def test_verify_checksum(self):
		doc = self.build(export())
		self.assertTrue(archive.verify(doc.name)["ok"])
		frappe.db.set_value("Archive Export", doc.name, "sha256", "0" * 64)
		self.assertFalse(archive.verify(doc.name)["ok"])

	def test_permissions_follow_the_matrix(self):
		assert_permission_matrix(self, "Archive Export")
		self.assertFalse(
			frappe.has_permission(
				"Archive Export", "create", user=make_user("archive-r02@example.com", ["TC R02"])
			)
		)


class TestArchiveApi(ArchiveCase):
	def test_rpc_creates_the_export_and_verifies(self):
		from tracecore.v1 import archive as archive_api

		with patch("frappe.enqueue"):
			result = archive_api.export(
				scope_type="Load", sterilization_load=self.load.name, include=json.dumps(["loads", "audit"])
			)
		doc = frappe.get_doc("Archive Export", result["name"])
		self.assertEqual((doc.inc_loads, doc.inc_audit, doc.inc_usage), (1, 1, 0))
		self.build(doc)
		self.assertTrue(archive_api.verify(doc.name)["ok"])
		frappe.set_user(make_user("archive-r04@example.com", ["TC R04"]))
		with self.assertRaises(frappe.PermissionError):
			archive_api.verify(doc.name)
