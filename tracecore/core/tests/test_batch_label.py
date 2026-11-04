"""Nhãn QR của lô vật tư/chỉ thị (FEAT-082, A-118, FR-M6-09): QR chứa đúng tên Batch."""

import base64
import io

import frappe
from frappe.utils import add_days, today
from pypdf import PdfReader

from tracecore.core import batch_label, lots, qr
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
ITEM = "VT-NHAN-CI-1"


class TestBatchLabel(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		factories.make_item(ITEM, "Chemical Indicator")
		self.valid = factories.make_batch(ITEM, "LOT-OK-261104", expiry_date=add_days(today(), 90)).name
		self.expired = factories.make_batch(ITEM, "LOT-OLD-250101", expiry_date=add_days(today(), -5)).name

	@bru("BRU-INV-004")
	def test_valid_batch_has_a_label(self):
		self.assertIsNone(batch_label.problem(self.valid))

	def test_unknown_batch_is_refused_with_a_reason(self):
		self.assertIn("KHONG-CO", batch_label.problem("KHONG-CO"))

	def test_expired_batch_is_refused(self):
		self.assertTrue(batch_label.problem(self.expired))

	def test_disabled_batch_is_refused(self):
		frappe.db.set_value("Batch", self.valid, "disabled", 1)
		self.assertTrue(batch_label.problem(self.valid))

	def test_name_that_cannot_be_a_qr_payload_is_refused(self):
		factories.make_batch(ITEM, "LOT CO KHOANG TRANG", expiry_date=add_days(today(), 30))
		self.assertTrue(batch_label.problem("LOT CO KHOANG TRANG"))

	def test_pdf_is_one_page_per_batch_and_qr_is_the_batch_name(self):
		other = factories.make_batch(ITEM, "LOT-OK2-261104", expiry_date=add_days(today(), 60)).name
		pdf, printed, skipped = batch_label.pdf([self.valid, other, self.expired])
		reader = PdfReader(io.BytesIO(pdf))
		self.assertEqual(len(reader.pages), 2)
		self.assertEqual(printed, [self.valid, other])
		self.assertEqual([row["batch"] for row in skipped], [self.expired])
		self.assertEqual(qr.decode_png(reader.pages[0].images[0].data), self.valid)
		self.assertIn(self.valid, reader.pages[0].extract_text())

	def test_nothing_printable_returns_no_pdf(self):
		pdf, printed, skipped = batch_label.pdf([self.expired])
		self.assertIsNone(pdf)
		self.assertEqual(printed, [])
		self.assertEqual(len(skipped), 1)

	def test_scanning_the_label_gives_the_same_lot_code(self):
		payload = qr.decode_png(
			PdfReader(io.BytesIO(batch_label.pdf([self.valid])[0])).pages[0].images[0].data
		)
		self.assertEqual(lots.lot_code(payload), self.valid)

	def test_each_printed_batch_is_audited(self):
		batch_label.pdf([self.valid])
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "Batch", "ref_name": self.valid, "reason": "BatchLabelPrinted"}
			)
		)

	def test_pdf_b64_roundtrip_helper(self):
		result = batch_label.render([self.valid])
		self.assertTrue(base64.b64decode(result["pdf_b64"]).startswith(b"%PDF"))
		self.assertEqual(result["printed"], [self.valid])
