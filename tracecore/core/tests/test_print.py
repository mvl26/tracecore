import io

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tracecore.core import code_registry, gs1
from tracecore.core import print as core_print


class TestCorePrint(FrappeTestCase):
	def test_render_test_label(self):
		label = core_print.render_test_label("TR-004")
		giai = label["giai"]
		self.assertTrue(giai.startswith(gs1.configured_company_prefix() + "TEST"))
		self.assertEqual(label["hri"], "(8004)" + giai)
		zpl = label["zpl"]
		self.assertTrue(zpl.startswith("^XA"))
		self.assertTrue(zpl.endswith("^XZ"))
		for part in ("^CI28", "^PW590", "^BXN", "^FD_18004" + giai, "TraceCore TEST", "TR-004"):
			self.assertIn(part, zpl)
		image = Image.open(io.BytesIO(label["preview_png"]))
		self.assertEqual(image.size, (590, 354))
		self.assertEqual(gs1.decode_datamatrix_png(label["preview_png"]), "\x1d8004" + giai)

	def test_label_text_fits_inside_label(self):
		from PIL import ImageFont

		giai = gs1.make_giai(gs1.configured_company_prefix(), "TEST" + "9" * 12)
		for x, y, size, text in core_print.label_layout(giai, "TR-004"):
			width = ImageFont.load_default(size=size).getlength(text)
			self.assertLessEqual(x + width, core_print.LABEL_WIDTH_DOTS, msg=text)
			self.assertLessEqual(y + size, core_print.LABEL_HEIGHT_DOTS, msg=text)

	def test_test_label_does_not_consume_codes(self):
		label = core_print.render_test_label("TR-004")
		self.assertFalse(code_registry.is_issued(label["giai"]))

	def test_create_job_and_ack_printed(self):
		job = core_print.create_job("TR-004", "^XA^XZ", {"k": 1}, "test-label")
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual((doc.status, doc.attempts, doc.station), ("Queued", 0, "TR-004"))

		result = core_print.ack(job, "Printed", "File", output_ref="/tmp/1.zpl")
		self.assertEqual(result, {"ok": True, "status": "Printed"})
		doc.reload()
		self.assertEqual(
			(doc.status, doc.output_mode, doc.output_ref, doc.attempts), ("Printed", "File", "/tmp/1.zpl", 1)
		)
		self.assertIsNotNone(doc.printed_at)

	def test_ack_failed_records_error(self):
		job = core_print.create_job("TR-004", "^XA^XZ")
		core_print.ack(job, "Failed", "Printer", error="timeout")
		doc = frappe.get_doc("Print Job", job)
		self.assertEqual((doc.status, doc.error, doc.attempts), ("Failed", "timeout", 1))
		self.assertIsNone(doc.printed_at)

	def test_ack_rejects_invalid_values(self):
		job = core_print.create_job("TR-004", "^XA^XZ")
		with self.assertRaises(frappe.ValidationError):
			core_print.ack(job, "Weird", "File")
		with self.assertRaises(frappe.ValidationError):
			core_print.ack(job, "Printed", "Fax")

	def test_ack_unknown_job(self):
		with self.assertRaises(frappe.DoesNotExistError):
			core_print.ack("987654321", "Printed", "File")
