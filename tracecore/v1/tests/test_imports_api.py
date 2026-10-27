"""RPC tracecore.v1.imports.* (FEAT-011 Task 8): loại import, mẫu, kiểm, ghi sổ idempotent, kết quả lô (SCR-43)."""

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import frappe

from tracecore.core.tests.test_importer import workbook
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import imports as imports_api

HEADER = ["Department Name", "Ward"]


def now_ts():
	return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def upload(content, name="khoa.xlsx"):
	doc = frappe.get_doc({"doctype": "File", "file_name": name, "is_private": 1, "content": content}).insert(
		ignore_permissions=True
	)
	return doc.file_url


def department_file(*names):
	return upload(workbook(HEADER, [[name, "x"] for name in names]))


class ImportsApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		# R10 kèm HR Manager (Department của ERPNext chỉ HR Manager/HR User được tạo); quyền từng danh mục theo DocType
		frappe.set_user(make_user("imp-r10@example.com", roles=("TC R10", "HR Manager")))
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.response.pop("http_status_code", None)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)


class TestKindsAndTemplate(ImportsApiCase):
	def test_kinds_lists_catalogs(self):
		# R10 + R02 + HR Manager có quyền tạo mọi danh mục (Par Level cần R02, Department cần HR Manager)
		frappe.set_user(make_user("imp-all@example.com", roles=("TC R10", "TC R02", "HR Manager")))
		keys = [row["key"] for row in imports_api.kinds()]
		for key in (
			"department",
			"employee",
			"instrument",
			"set_type",
			"set_unit",
			"equipment",
			"program",
			"item",
			"par_level",
		):
			self.assertIn(key, keys)

	def test_other_roles_forbidden(self):
		frappe.set_user(make_user("imp-r04@example.com", roles=("TC R04",)))
		with self.assertRaises(frappe.PermissionError):
			imports_api.kinds()
		with self.assertRaises(frappe.PermissionError):
			imports_api.check(kind="department", file_url=department_file("K"))

	def test_import_needs_create_permission_of_the_catalog(self):
		"""Import không lách quyền: R10 không có quyền tạo Par Level / Department thì không import được hai loại đó."""
		frappe.set_user(make_user("imp-r10-only@example.com", roles=("TC R10",)))
		keys = [row["key"] for row in imports_api.kinds()]
		self.assertIn("instrument", keys)  # R10 có quyền tạo Instrument
		self.assertNotIn("par_level", keys)
		self.assertNotIn("department", keys)
		with self.assertRaises(frappe.PermissionError):
			imports_api.check(kind="par_level", file_url=department_file("K"))

	def test_template_is_xlsx_download(self):
		imports_api.template(kind="department")
		self.assertEqual(frappe.response["type"], "binary")
		self.assertTrue(frappe.response["filename"].endswith(".xlsx"))
		self.assertTrue(frappe.response["filecontent"].startswith(b"PK"))


class TestCheckAndRun(ImportsApiCase):
	def test_check_reports_rows(self):
		name = "Khoa API " + uuid.uuid4().hex[:6]
		result = imports_api.check(kind="department", file_url=department_file(name))
		self.assertIs(result["ok"], True)
		self.assertEqual((result["total"], result["valid"]), (1, 1))
		self.assertFalse(frappe.db.exists("Department", {"department_name": name}))

	def test_other_users_file_is_rejected(self):
		frappe.set_user("Administrator")
		file_url = department_file("Khoa của người khác")
		frappe.set_user("imp-r10@example.com")
		result = imports_api.check(kind="department", file_url=file_url)
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["code"], "IMPORT_FILE_INVALID")

	def test_run_same_key_creates_one_batch(self):
		name = "Khoa API " + uuid.uuid4().hex[:6]
		file_url = department_file(name)
		key, stamp = str(uuid.uuid4()), now_ts()
		with request_headers({"X-Idempotency-Key": key}):
			first = imports_api.run(kind="department", file_url=file_url, client_ts=stamp)
			second = imports_api.run(kind="department", file_url=file_url, client_ts=stamp)
		self.assertEqual(first["batch"], second["batch"])
		self.assertEqual(frappe.db.count("Department", {"department_name": name}), 1)
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "Import Batch", "ref_name": first["batch"]})
		)

	def test_batch_returns_status_and_rows(self):
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
			started = imports_api.run(
				kind="department",
				file_url=department_file("Khoa lô " + uuid.uuid4().hex[:6]),
				client_ts=now_ts(),
			)
		result = imports_api.batch(name=started["batch"])
		self.assertEqual((result["status"], result["created"]), ("Done", 1))
		self.assertEqual(result["rows"][0]["result"], "Created")

	def test_unknown_kind_is_bad_request(self):
		with self.assertRaises(frappe.ValidationError):
			imports_api.check(kind="no_such_kind", file_url=department_file("K"))
