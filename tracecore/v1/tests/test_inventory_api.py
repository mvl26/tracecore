"""RPC tracecore.v1.inventory.* (FEAT-041 Task 4): mẫu, kiểm và ghi nhập kho hàng loạt từ Excel."""

import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_days, today

from tracecore.tests import factories
from tracecore.tests.factories import attach_private_file, make_receipt_workbook, make_user
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import inventory as inventory_api

test_ignore = [
	"Item",
	"Batch",
	"Stock Entry",
	"Warehouse",
	"Company",
	"Supplier",
	"Stock Entry Type",
	"Fiscal Year",
]

FAR = add_days(today(), 400)


def now_ts():
	return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def http_status():
	return frappe.local.response.get("http_status_code")


def call(fn, key=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4())}):
		return fn(**kwargs)


def as_user(roles, fn, **kwargs):
	email = make_user(
		f"inv-api-{'-'.join(r.lower().replace(' ', '') for r in roles) or 'none'}@example.com", roles
	)
	frappe.set_user(email)
	try:
		return fn(**kwargs)
	finally:
		frappe.set_user("Administrator")


class InventoryApiCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.masters = factories.ensure_stock_masters()
		self.warehouse = self.masters["warehouse"]
		self.supplier = factories.make_supplier("F41 NCC API")
		factories.make_item("F41-A-1", "Chemical", apply_rules=True)

	def row(self, lot, expiry=FAR, qty=10, rate=1000, doc="PGH-API", item="F41-A-1"):
		return [item, lot, expiry, qty, rate, self.supplier, doc, self.warehouse]

	def upload(self, rows, name="nhap.xlsx", user=None):
		content = make_receipt_workbook(rows)
		frappe.set_user(user or make_user("inv-api-tcr09@example.com", ["TC R09"]))
		try:
			return attach_private_file(content, name)
		finally:
			frappe.set_user("Administrator")

	def stock(self):
		return frappe.db.get_value("Bin", {"item_code": "F41-A-1", "warehouse": self.warehouse}, "actual_qty")


class TestReceiptTemplate(InventoryApiCase):
	def test_template_endpoint_returns_xlsx_for_r09_not_r04(self):
		as_user(["TC R09"], inventory_api.receipt_template)
		self.assertEqual(frappe.local.response["type"], "binary")
		self.assertTrue(frappe.local.response["filename"].endswith(".xlsx"))
		self.assertEqual(frappe.local.response["filecontent"][:2], b"PK")
		frappe.local.response.pop("filecontent")
		with self.assertRaises(frappe.PermissionError):
			as_user(["TC R04"], inventory_api.receipt_template)
		self.assertNotIn("filecontent", frappe.local.response)


class TestReceiptCheck(InventoryApiCase):
	def test_check_requires_role(self):
		url = self.upload([self.row("CK-0")])
		before = frappe.db.count("Audit Log")
		with self.assertRaises(frappe.PermissionError):
			as_user(["TC R04"], inventory_api.receipt_check, file_url=url, warehouse=self.warehouse)
		self.assertEqual(frappe.db.count("Audit Log"), before)

	def test_check_ok_writes_nothing(self):
		url = self.upload([self.row("CK-1"), self.row("CK-2", doc="PGH-2")])
		before = (frappe.db.count("Stock Entry"), frappe.db.count("Batch"))
		result = as_user(["TC R09"], inventory_api.receipt_check, file_url=url)
		self.assertEqual((result["ok"], result["rows"], result["documents"]), (True, 2, 2))
		self.assertEqual(result["warnings"], [])
		self.assertEqual((frappe.db.count("Stock Entry"), frappe.db.count("Batch")), before)

	def test_check_returns_row_errors_with_http_422(self):
		url = self.upload([self.row("CK-3"), self.row("CK-4", add_days(today(), -1)), self.row("", FAR)])
		frappe.local.response.pop("http_status_code", None)
		with request_headers({}):
			result = as_user(["TC R09"], inventory_api.receipt_check, file_url=url)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "IMPORT_ROWS_INVALID")
		self.assertEqual(http_status(), 422)
		self.assertEqual(
			[(i["row"], i["code"], i["field"]) for i in result["error"]["items"]],
			[(3, "EXPIRY_PAST", "expiry_date"), (4, "BATCH_REQUIRED", "batch_id")],
		)
		self.assertTrue(all(i["reason"] for i in result["error"]["items"]))

	def test_check_file_errors_are_import_file_invalid(self):
		with request_headers({}):
			bad = as_user(
				["TC R09"], inventory_api.receipt_check, file_url=attach_private_file(b"not excel", "x.xlsx")
			)
			self.assertEqual((bad["error"]["code"], http_status()), ("IMPORT_FILE_INVALID", 422))
			wrong_ext = as_user(
				["TC R09"],
				inventory_api.receipt_check,
				file_url=attach_private_file(make_receipt_workbook([self.row("X-1")]), "nhap.csv"),
			)
			self.assertEqual(wrong_ext["error"]["code"], "IMPORT_FILE_INVALID")
			missing = as_user(
				["TC R09"], inventory_api.receipt_check, file_url="/private/files/khong-co.xlsx"
			)
			self.assertEqual(missing["error"]["code"], "IMPORT_FILE_INVALID")

	def test_check_bad_arguments_are_400(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			as_user(["TC R09"], inventory_api.receipt_check, file_url=["x"])
		self.assertEqual(ctx.exception.http_status_code, 400)


class TestReceiptImport(InventoryApiCase):
	def test_import_creates_documents_and_returns_names(self):
		url = self.upload([self.row("IM-1"), self.row("IM-2", doc="PGH-API-2", qty=5)])
		result = self.import_as(["TC R09"], url)
		self.assertTrue(result["ok"])
		self.assertEqual(result["rows"], 2)
		self.assertEqual(len(result["stock_entries"]), 2)
		self.assertTrue(
			all(frappe.db.get_value("Stock Entry", n, "docstatus") == 1 for n in result["stock_entries"])
		)
		self.assertEqual(self.stock(), 15)

	def import_as(self, roles, url, key=None, ts=None, **kwargs):
		ts = ts or now_ts()
		email = make_user(
			f"inv-api-{'-'.join(r.lower().replace(' ', '') for r in roles) or 'none'}@example.com", roles
		)
		frappe.set_user(email)
		try:
			return call(inventory_api.receipt_import, key, file_url=url, client_ts=ts, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def upload_as(self, roles, rows):
		email = make_user(
			f"inv-api-{'-'.join(r.lower().replace(' ', '') for r in roles) or 'none'}@example.com", roles
		)
		return self.upload(rows, user=email)

	def test_r06_and_r09_can_import(self):
		for roles, lot in ((["TC R06"], "IM-R6"), (["TC R09"], "IM-R9")):
			url = self.upload_as(roles, [self.row(lot, doc=f"PGH-{lot}")])
			result = self.import_as(roles, url)
			self.assertTrue(result["ok"], result)
		self.assertEqual(self.stock(), 20)

	@bru("BRU-INV-001")
	def test_import_same_idempotency_key_does_not_double_stock(self):
		url = self.upload_as(["TC R09"], [self.row("ID-1", qty=7)])
		key, ts = str(uuid.uuid4()), now_ts()
		first = self.import_as(["TC R09"], url, key, ts)
		second = self.import_as(["TC R09"], url, key, ts)
		self.assertEqual(first, second)
		self.assertEqual(self.stock(), 7)
		self.assertEqual(frappe.db.count("Stock Entry", {"tc_document_no": "PGH-API"}), 1)

	def test_import_new_key_second_time_adds_stock(self):
		url = self.upload_as(["TC R09"], [self.row("ID-2", qty=7)])
		self.import_as(["TC R09"], url)
		self.import_as(["TC R09"], url)  # khóa mới = lần nhập thứ hai theo thiết kế
		self.assertEqual(self.stock(), 14)

	def test_import_rejects_foreign_or_public_file(self):
		other = make_user("inv-api-owner@example.com", ["TC R09"])
		foreign = self.upload([self.row("FO-1")], user=other)  # file của người khác
		public = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "cong-khai.xlsx",
				"content": make_receipt_workbook([self.row("FO-2")]),
				"is_private": 0,
			}
		).insert(ignore_permissions=True)
		for url in (foreign, public.file_url):
			result = self.import_as(["TC R09"], url)
			self.assertEqual(result["error"]["code"], "IMPORT_FILE_INVALID")
			self.assertEqual(http_status(), 422)
		self.assertIsNone(self.stock())

	def test_import_missing_idempotency_key_400(self):
		url = self.upload([self.row("MK-1")])
		frappe.local.response.pop("http_status_code", None)
		with request_headers({}), self.assertRaises(frappe.ValidationError) as ctx:
			as_user(["TC R09"], inventory_api.receipt_import, file_url=url, client_ts=now_ts())
		self.assertEqual(ctx.exception.http_status_code, 400)

	def test_import_requires_role_before_any_write(self):
		url = self.upload([self.row("RR-1")])
		keys, entries = frappe.db.count("Idempotency Key"), frappe.db.count("Stock Entry")
		with self.assertRaises(frappe.PermissionError):
			self.import_as(["TC R04"], url)
		self.assertEqual(
			(frappe.db.count("Idempotency Key"), frappe.db.count("Stock Entry")), (keys, entries)
		)

	def test_company_not_configured_409(self):
		url = self.upload_as(["TC R09"], [self.row("CN-1")])
		with patch("erpnext.get_default_company", return_value=None):
			result = self.import_as(["TC R09"], url)
		self.assertEqual(result["error"]["code"], "COMPANY_NOT_CONFIGURED")
		self.assertEqual(http_status(), 409)
		self.assertIsNone(self.stock())

	def test_reject_writes_audit_log(self):
		url = self.upload_as(["TC R09"], [self.row("AU-1"), self.row("AU-2", add_days(today(), -2))])
		before = frappe.db.count("Audit Log", {"action": "Reject", "reason": "IMPORT_ROWS_INVALID"})
		result = self.import_as(["TC R09"], url)
		self.assertEqual(result["error"]["code"], "IMPORT_ROWS_INVALID")
		self.assertEqual(
			frappe.db.count("Audit Log", {"action": "Reject", "reason": "IMPORT_ROWS_INVALID"}), before + 1
		)
		self.assertIsNone(self.stock())

	def test_invalid_import_replay_returns_same_error_and_status(self):
		url = self.upload_as(["TC R09"], [self.row("RP-1", add_days(today(), -2))])
		key, ts = str(uuid.uuid4()), now_ts()
		first = self.import_as(["TC R09"], url, key, ts)
		second = self.import_as(["TC R09"], url, key, ts)
		self.assertEqual(first, second)
		self.assertEqual(http_status(), 422)
