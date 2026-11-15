"""A-159: ảnh của màn trạm tải qua phiên thẻ (`tracecore.v1.station.upload_photo`), không qua upload_file của Desk.

Ticket 13/11/2026: cookie Desk về Guest thì `/api/method/upload_file` trả 403 nên T2/T3/T5/test hằng ngày không đính
được ảnh, trong khi phiên thẻ trạm vẫn còn.
"""

import base64
import io
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import frappe
from PIL import Image

from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import station as station_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
STATION = "TR-004"


def png_b64(size=(6, 6)):
	buffer = io.BytesIO()
	Image.new("RGB", size, (10, 10, 10)).save(buffer, format="PNG")
	return base64.b64encode(buffer.getvalue()).decode()


class TestStationPhotoUpload(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.user = make_user("photo.operator@example.test", ("TC R04",))
		self.session = make_station_session(self.user, STATION)
		self.token = self.session["token"]
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def upload(self, key=None, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		kwargs.setdefault("client_ts", datetime.now(timezone.utc).isoformat())
		kwargs.setdefault("station", STATION)
		kwargs.setdefault("token", self.token)
		kwargs.setdefault("file_name", "printout.png")
		kwargs.setdefault("content", png_b64())
		with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": STATION}):
			return station_api.upload_photo(**kwargs)

	def assert_block(self, result, code, status):
		self.assertIs(result["ok"], False, msg=result)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(frappe.local.response.get("http_status_code"), status)
		for part in ("title", "reason", "action"):
			self.assertTrue(result["error"][part], msg=part)

	def files(self):
		return frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Station Session"},
			fields=["name", "file_url", "is_private", "attached_to_name", "file_name"],
		)

	def test_guest_with_a_live_card_session_uploads_a_private_photo(self):
		frappe.set_user("Guest")  # cookie Desk đã hết: chỉ còn phiên thẻ
		result = self.upload(file_name="../../etc/passwd.png")
		self.assertTrue(result["ok"], result)
		self.assertTrue(result["file_url"].startswith("/private/files/"), result)
		frappe.set_user("Administrator")
		(file,) = self.files()
		self.assertEqual(file.file_url, result["file_url"])
		self.assertEqual(file.is_private, 1)
		self.assertEqual(
			file.attached_to_name, self.session["session"]
		)  # chỉ gắn vào phiên của chính người quét thẻ
		self.assertNotIn("/", file.file_name)
		self.assertNotIn("passwd", file.file_name)  # tên file do server đặt
		self.assertTrue(file.file_name.endswith(".png"))  # đuôi theo nội dung
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "File", "ref_name": file.name, "action": "Create"})
		)

	def test_invalid_or_missing_session_is_401_and_stores_nothing(self):
		frappe.set_user("Guest")
		self.assert_block(self.upload(token="not-a-token"), "SESSION_INVALID", 401)
		self.assert_block(self.upload(token=None), "SESSION_INVALID", 401)
		frappe.set_user("Administrator")
		self.assertEqual(self.files(), [])

	def test_session_of_another_station_is_refused(self):
		self.assert_block(self.upload(station="TR-005"), "SESSION_STATION_MISMATCH", 403)
		self.assertEqual(self.files(), [])

	def test_role_without_station_photos_is_refused(self):
		user = make_user("photo.ward@example.test", ("TC R08",))
		self.token = make_station_session(user, STATION)["token"]
		with self.assertRaises(frappe.PermissionError):
			self.upload()
		self.assertEqual(self.files(), [])

	def test_not_an_image_is_refused(self):
		svg = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>").decode()
		for content in ("AAAA", "not base64 !", svg, ""):
			with self.subTest(content=content[:10]):
				self.assert_block(self.upload(content=content), "PHOTO_INVALID", 422)
		self.assertEqual(self.files(), [])

	def test_photo_larger_than_the_limit_is_refused(self):
		with patch("tracecore.core.photo.MAX_BYTES", 64):
			self.assert_block(self.upload(content=png_b64((64, 64))), "PHOTO_INVALID", 422)
		with patch("tracecore.core.photo.MAX_PIXELS", 100):
			self.assert_block(self.upload(content=png_b64((20, 20))), "PHOTO_INVALID", 422)
		self.assertEqual(self.files(), [])

	def test_target_document_cannot_be_chosen_by_the_client(self):
		for extra in (
			{"attached_to_doctype": "User"},
			{"doctype": "Employee", "docname": "x"},
			{"folder": "Home"},
		):
			with self.subTest(extra=extra), self.assertRaises(TypeError):
				self.upload(**extra)
		self.assertEqual(self.files(), [])

	def test_replay_with_the_same_key_returns_the_same_file(self):
		key, content = str(uuid.uuid4()), png_b64()
		ts = datetime.now(timezone.utc).isoformat()
		first = self.upload(key=key, content=content, client_ts=ts)
		second = self.upload(key=key, content=content, client_ts=ts)
		self.assertEqual(first["file_url"], second["file_url"])
		self.assertEqual(len(self.files()), 1)
