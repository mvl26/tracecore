"""RPC `tracecore.v1.print.batch_labels_pdf`: nhãn QR của lô vật tư/chỉ thị (FEAT-082, A-118, FR-M6-09)."""

import base64
import io

import frappe
from frappe.utils import add_days, today
from pypdf import PdfReader

from tracecore.core import qr
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import print as print_api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
ITEM = "VT-NHAN-CI-2"


class TestBatchLabelsPdf(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		# test đổi người dùng phải trả lại Administrator, không thì module chạy sau (putaway, purchase request) lỗi quyền
		self.addCleanup(frappe.set_user, "Administrator")
		factories.make_item(ITEM, "Chemical Indicator")
		self.valid = factories.make_batch(ITEM, "LOT-RPC-OK", expiry_date=add_days(today(), 30)).name
		self.expired = factories.make_batch(ITEM, "LOT-RPC-OLD", expiry_date=add_days(today(), -1)).name

	def test_returns_a_pdf_with_the_lot_qr_and_lists_skipped_lots(self):
		result = print_api.batch_labels_pdf([self.valid, self.expired])
		self.assertTrue(result["ok"])
		self.assertEqual(result["printed"], [self.valid])
		self.assertEqual([row["batch"] for row in result["skipped"]], [self.expired])
		page = PdfReader(io.BytesIO(base64.b64decode(result["pdf_b64"]))).pages[0]
		self.assertEqual(qr.decode_png(page.images[0].data), self.valid)
		self.assertEqual(result["filename"], f"{self.valid}.pdf")

	def test_accepts_a_json_list_from_the_desk(self):
		result = print_api.batch_labels_pdf(frappe.as_json([self.valid]))
		self.assertTrue(result["ok"])

	def test_nothing_printable_is_a_clear_block(self):
		result = print_api.batch_labels_pdf([self.expired])
		self.assertFalse(result["ok"])
		error = result["error"]
		self.assertEqual(error["code"], "CONSUMABLE_LOT_INVALID")
		self.assertTrue(error["title"] and error["reason"] and error["action"])

	def test_bad_input_is_a_bad_request(self):
		for bad in ([], "khong-phai-json", [1, 2], ["a"] * 51, None):
			with self.assertRaises(Exception):
				print_api.batch_labels_pdf(bad)

	def test_user_without_a_label_role_is_refused(self):
		user = factories.make_user("tc-no-label@example.com")
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			print_api.batch_labels_pdf([self.valid])
