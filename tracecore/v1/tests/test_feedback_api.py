"""RPC tracecore.v1.feedback.create (FEAT-013, FR-M9-15, A-56 D1, D7, D8).

Người đã quét thẻ gửi phản hồi/báo lỗi phần mềm từ trạm → ERPNext Issue loại `TraceCore Software` gắn trạm, nhân viên,
ngữ cảnh đã lọc và ảnh chụp màn hình private; R10 nhận thông báo `SOFTWARE_FEEDBACK`.
"""

import base64
import io
import uuid
from datetime import timedelta

import frappe
from frappe.utils import add_to_date, now_datetime
from PIL import Image

from tracecore.core import station_auth
from tracecore.tests.factories import make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.ui import feedback
from tracecore.v1 import feedback as api
from tracecore.v1 import station as station_api

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
STATION = "TR-004"
CARD = "FEEDBACK-CARD"
CLIENT_TS = "2026-10-30T09:00:00+07:00"


def image_bytes(fmt):
	buffer = io.BytesIO()
	Image.new("RGB", (8, 8), (200, 200, 200)).save(buffer, format=fmt)
	return buffer.getvalue()


PNG = image_bytes("PNG")
JPEG = image_bytes("JPEG")


def data_url(content, mime="image/png"):
	return f"data:{mime};base64," + base64.b64encode(content).decode()


class TestFeedbackCreate(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.user = make_user("feedback-r05@example.com", ["TC R05"])
		self.r10 = make_user("feedback-r10@example.com", ["TC R10"])
		self.employee = make_employee(card=CARD, first_name="Phản hồi", user_id=self.user).name
		now = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": self.employee,
				"station": STATION,
				"valid_from": now - timedelta(hours=1),
				"valid_until": now + timedelta(hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(station_auth.clear_pin_rate_limit, self.employee)
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)
		self.token = station_api.login(CARD, STATION, client_ts=CLIENT_TS)["session"]["token"]

	def create(self, key=None, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		args = {
			"station": STATION,
			"kind": "Bug",
			"description": "The label printer button does nothing",
			"screenshot": data_url(PNG),
			"context": {"screen": "T4", "online": True, "last_error": "PACK_NOT_FOUND", "secret": "drop me"},
			"client_ts": CLIENT_TS,
			"token": self.token,
		}
		args.update(kwargs)
		with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": STATION}):
			return api.create(**args)

	def assert_block(self, result, code, status):
		self.assertIs(result["ok"], False)
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(result["error"]["http_status"], status)
		for field in ("title", "reason", "action"):
			self.assertTrue(result["error"][field])

	def test_creates_software_issue_with_station_employee_and_context(self):
		result = self.create()
		self.assertTrue(result["ok"])
		issue = frappe.get_doc("Issue", result["issue"])
		self.assertEqual(issue.issue_type, feedback.ISSUE_TYPE)
		self.assertEqual(
			(issue.tc_station, issue.tc_employee, issue.tc_feedback_kind, issue.raised_by),
			(STATION, self.employee, "Bug", self.user),
		)
		self.assertIn(STATION, issue.subject)
		self.assertIn("The label printer button does nothing", issue.description)
		self.assertIn("PACK_NOT_FOUND", issue.description)
		self.assertNotIn("drop me", issue.description)

	def test_screenshot_is_private_file_on_issue(self):
		result = self.create()
		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Issue", "attached_to_name": result["issue"]},
			fields=["is_private", "file_name"],
		)
		self.assertEqual(len(files), 1)
		self.assertEqual(files[0].is_private, 1)
		self.assertTrue(files[0].file_name.endswith(".png"))

	def test_jpeg_and_no_screenshot_are_accepted(self):
		self.assertTrue(self.create(screenshot=data_url(JPEG, "image/jpeg"))["ok"])
		result = self.create(screenshot=None, kind="Suggestion", description="Please make the font larger")
		self.assertTrue(result["ok"])
		self.assertFalse(
			frappe.get_all(
				"File", filters={"attached_to_doctype": "Issue", "attached_to_name": result["issue"]}
			)
		)

	def test_r10_is_notified(self):
		result = self.create()
		rows = frappe.get_all(
			"Notification Delivery",
			filters={"event_code": "SOFTWARE_FEEDBACK", "ref_name": result["issue"]},
			pluck="recipient",
		)
		self.assertIn(self.r10, rows)

	def test_replay_with_same_key_creates_one_issue(self):
		key = str(uuid.uuid4())
		first = self.create(key=key)
		second = self.create(key=key)
		self.assertEqual(first["issue"], second["issue"])
		self.assertEqual(frappe.db.count("Issue", {"tc_employee": self.employee}), 1)

	def test_description_length_is_checked(self):
		for text in ("too short", "x" * 2001, "   "):
			self.assert_block(self.create(description=text), "FEEDBACK_INVALID", 422)

	def test_kind_is_checked(self):
		self.assert_block(self.create(kind="Praise"), "FEEDBACK_INVALID", 422)

	def test_screenshot_must_be_small_png_or_jpeg(self):
		for value in (
			data_url(b"GIF89a" + b"\x00" * 10, "image/gif"),
			data_url(b"not an image", "image/png"),
			data_url(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64),
			data_url(PNG, "image/jpeg"),
			"data:image/png;base64,@@@",
			"https://example.com/shot.png",
			data_url(PNG + b"\x00" * (feedback.MAX_SCREENSHOT_BYTES + 1)),
		):
			self.assert_block(self.create(screenshot=value), "SCREENSHOT_INVALID", 422)

	def test_rate_limit_per_employee_per_hour(self):
		for _n in range(feedback.RATE_LIMIT):
			self.assertTrue(self.create(screenshot=None)["ok"])
		self.assert_block(self.create(screenshot=None), "FEEDBACK_RATE_LIMIT", 429)
		frappe.db.set_value(
			"Issue",
			{"tc_employee": self.employee},
			"creation",
			add_to_date(now_datetime(), hours=-2),
		)
		self.assertTrue(self.create(screenshot=None)["ok"])

	def test_needs_station_session(self):
		result = self.create(token="not-a-token")
		self.assertIs(result["ok"], False)
		self.assertTrue(result["error"]["code"].startswith("SESSION_"))
		self.assertFalse(frappe.db.count("Issue", {"tc_employee": self.employee}))

	def test_context_accepts_json_string_and_trims_values(self):
		result = self.create(context='{"screen": "' + "y" * 500 + '", "viewport": "1366x768"}')
		description = frappe.db.get_value("Issue", result["issue"], "description")
		self.assertIn("1366x768", description)
		self.assertNotIn("y" * 201, description)

	def test_description_is_escaped(self):
		result = self.create(description="<script>alert(1)</script> broken screen")
		description = frappe.db.get_value("Issue", result["issue"], "description")
		self.assertNotIn("<script>", description)

	def test_r10_can_read_issue(self):
		result = self.create()
		frappe.set_user(self.r10)
		self.assertTrue(frappe.has_permission("Issue", "read", result["issue"]))
		self.assertTrue(frappe.has_permission("Help Article", "write"))

	def test_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[api.create], ["POST"])
