"""RPC tracecore.v1.instrument.get_image (FEAT-014 Task 3, FR-M1-01.6, A-06 I12): URL ảnh, thumbnail và etag."""

import inspect
import io

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tracecore.tests.factories import attach_instrument_file, make_instrument, make_user
from tracecore.tests.utils import request_headers
from tracecore.v1 import instrument as instrument_api

# Instrument liên kết Item (ERPNext) và User (owner): site CI chưa chạy Setup Wizard
test_ignore = ["Item", "User", "Batch"]


def get_image(instrument):
	frappe.local.response.pop("http_status_code", None)
	with request_headers({}):
		return instrument_api.get_image(instrument=instrument)


def http_status():
	return frappe.local.response.get("http_status_code")


def _png(color=(20, 120, 20)):
	buffer = io.BytesIO()
	Image.new("RGB", (640, 480), color).save(buffer, format="PNG")
	return buffer.getvalue()


def _with_photo(code):
	make_instrument(code, name=f"Dụng cụ {code}")
	source = attach_instrument_file(code, "image", _png(), f"{code.lower()}.png")
	doc = frappe.get_doc("Instrument", code)
	doc.image = source.file_url
	doc.save()
	return doc


class TestInstrumentApi(FrappeTestCase):
	def test_get_image_returns_urls_and_etag(self):
		doc = _with_photo("API-IMG")
		result = get_image("API-IMG")
		thumb_hash = frappe.db.get_value(
			"File", {"file_url": doc.image_thumbnail, "attached_to_name": "API-IMG"}, "content_hash"
		)
		self.assertEqual(
			result,
			{
				"ok": True,
				"instrument": "API-IMG",
				"image_url": doc.image,
				"thumbnail_url": doc.image_thumbnail,
				"etag": thumb_hash,
				"has_image": True,
			},
		)
		self.assertTrue(result["etag"])
		self.assertIsNone(http_status())
		# R04 (trạm T4) đọc được
		frappe.set_user(make_user("api-img-r04@example.com", roles=("TC R04",)))
		try:
			self.assertTrue(get_image("API-IMG")["ok"])
		finally:
			frappe.set_user("Administrator")

	def test_get_image_without_photo(self):
		make_instrument("API-NOIMG")
		result = get_image("API-NOIMG")
		self.assertEqual(
			result,
			{
				"ok": True,
				"instrument": "API-NOIMG",
				"image_url": None,
				"thumbnail_url": None,
				"etag": None,
				"has_image": False,
			},
		)
		self.assertIsNone(http_status())

	def test_get_image_unknown_404_with_audit(self):
		result = get_image("API-NONE-404")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "INSTRUMENT_NOT_FOUND")
		self.assertIn("API-NONE-404", result["error"]["reason"])
		self.assertTrue(result["error"]["title"] and result["error"]["action"])
		self.assertEqual(http_status(), 404)
		log = frappe.get_all(
			"Audit Log",
			filters={"action": "Reject", "reason": "INSTRUMENT_NOT_FOUND", "ref_name": "API-NONE-404"},
			fields=["ref_doctype", "new_value"],
		)
		self.assertEqual(len(log), 1)
		self.assertEqual(log[0].ref_doctype, "Instrument")
		self.assertEqual(frappe.parse_json(log[0].new_value)["raw"], "API-NONE-404")
		# tham số không phải chuỗi: cũng 404, không 500
		self.assertEqual(get_image(None)["error"]["code"], "INSTRUMENT_NOT_FOUND")

	def test_get_image_requires_read_permission(self):
		make_instrument("API-PERM")
		before = frappe.db.count("Audit Log", {"action": "Reject"})
		frappe.set_user(make_user("api-img-nobody@example.com"))
		try:
			with self.assertRaises(frappe.PermissionError):
				get_image("API-PERM")
			with self.assertRaises(frappe.PermissionError):
				get_image("API-UNKNOWN")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Audit Log", {"action": "Reject"}), before)

	def test_get_image_is_get_only(self):
		self.assertEqual(frappe.get_attr("tracecore.v1.instrument.get_image"), instrument_api.get_image)
		self.assertIn(instrument_api.get_image, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[instrument_api.get_image], ["GET"])
		# đọc thuần: không bọc @idempotent
		self.assertNotIn("core.idempotency", inspect.getsource(instrument_api))
