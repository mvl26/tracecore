"""Phản hồi / báo lỗi phần mềm từ trạm (FEAT-013, FR-M9-15, A-55 D1, D7, D8).

Lưu thành ERPNext `Issue` loại `TraceCore Software` (không dùng Incident CAPA để lỗi phần mềm không lẫn vào NC/CAPA
tái xử lý), gắn trạm, nhân viên, ngữ cảnh đã lọc và ảnh chụp màn hình private; báo R10 qua `SOFTWARE_FEEDBACK`.
Ảnh do kiosk chụp đã che ô mã bệnh nhân / PIN (D9); ở đây chỉ nhận PNG/JPEG đúng magic bytes và giới hạn cỡ.
"""

import base64
import binascii
import json
import io
import re

import frappe
from frappe import _
from frappe.utils import add_to_date, escape_html, now_datetime
from PIL import Image, UnidentifiedImageError

from tracecore.core import notification
from tracecore.core.errors import Block, BlockedError

ISSUE_TYPE = "TraceCore Software"
EVENT = "SOFTWARE_FEEDBACK"
KINDS = ("Bug", "Suggestion")
MIN_TEXT, MAX_TEXT = 10, 2000
MAX_SCREENSHOT_BYTES = 1_500_000
RATE_LIMIT = 10  # phản hồi / nhân viên / giờ
CONTEXT_KEYS = ("screen", "step", "online", "last_error", "app_version", "user_agent", "viewport")
CONTEXT_VALUE_MAX = 200
_DATA_URL = re.compile(r"^data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)$")
_MAGIC = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff"}


def _invalid(reason, action):
	return BlockedError(Block("FEEDBACK_INVALID", _("Feedback not sent"), reason, action))


def _screenshot(value):
	"""data URL PNG/JPEG → (đuôi file, bytes); không hợp lệ → `SCREENSHOT_INVALID`."""
	match = _DATA_URL.match(value or "") if isinstance(value, str) else None
	content = None
	if match:
		try:
			content = base64.b64decode(re.sub(r"\s", "", match.group(2)), validate=True)
		except (binascii.Error, ValueError):
			content = None
	kind = match.group(1) if match else None
	valid = bool(content) and content.startswith(_MAGIC[kind]) and len(content) <= MAX_SCREENSHOT_BYTES
	if valid:
		# magic bytes đúng chưa đủ: ảnh phải mở được và đúng định dạng đã khai
		try:
			with Image.open(io.BytesIO(content)) as image:
				image.verify()
				valid = image.format == kind.upper()
		except (UnidentifiedImageError, OSError, SyntaxError):
			valid = False
	if not valid:
		raise BlockedError(
			Block(
				"SCREENSHOT_INVALID",
				_("Screenshot not accepted"),
				_("The screenshot must be a PNG or JPEG image of at most {0} MB.").format("1,5"),
				_("Untick Attach screenshot and send again."),
			)
		)
	return ("jpg" if kind == "jpeg" else "png"), content


def _context(value):
	if isinstance(value, str):
		try:
			value = json.loads(value) if value.strip() else {}
		except ValueError:
			value = {}
	if not isinstance(value, dict):
		return {}
	return {
		key: str(value[key])[:CONTEXT_VALUE_MAX]
		for key in CONTEXT_KEYS
		if key in value and value[key] is not None
	}


def _check_rate(employee):
	since = add_to_date(now_datetime(), hours=-1)
	if frappe.db.count("Issue", {"tc_employee": employee, "creation": [">=", since]}) >= RATE_LIMIT:
		raise BlockedError(
			Block(
				"FEEDBACK_RATE_LIMIT",
				_("Feedback not sent"),
				_("You have sent {0} reports in the last hour.").format(RATE_LIMIT),
				_("Wait a while or tell R10 directly."),
			)
		)


def ensure_issue_type():
	if not frappe.db.exists("Issue Type", ISSUE_TYPE):
		frappe.get_doc(
			{
				"doctype": "Issue Type",
				"__newname": ISSUE_TYPE,
				"description": _("Software feedback and bug reports sent from TraceCore stations."),
			}
		).insert(ignore_permissions=True)
	return ISSUE_TYPE


def _description(text, context, station, employee):
	rows = [(_("Station"), station), (_("Employee"), employee), *context.items()]
	table = "".join(f"<tr><td>{escape_html(str(k))}</td><td>{escape_html(str(v))}</td></tr>" for k, v in rows)
	return f"<p>{escape_html(text)}</p><table>{table}</table>"


def create(kind, description, station, employee, user, screenshot=None, context=None):
	"""Tạo Issue phản hồi; trả tên Issue. Từ chối nghiệp vụ là `BlockedError` (FEEDBACK_*, SCREENSHOT_INVALID)."""
	if kind not in KINDS:
		raise _invalid(_("The feedback type is not valid."), _("Choose Bug or Suggestion."))
	text = (description or "").strip() if isinstance(description, str) else ""
	if not MIN_TEXT <= len(text) <= MAX_TEXT:
		raise _invalid(
			_("The description must have {0} to {1} characters.").format(MIN_TEXT, MAX_TEXT),
			_("Describe what you did and what went wrong."),
		)
	shot = _screenshot(screenshot) if screenshot else None
	_check_rate(employee)
	details = _context(context)
	issue = frappe.get_doc(
		{
			"doctype": "Issue",
			"subject": _("[{0}] {1}: {2}").format(station, _(kind), text[:80]),
			"raised_by": user,
			"issue_type": ensure_issue_type(),
			"description": _description(text, details, station, employee),
			"tc_station": station,
			"tc_employee": employee,
			"tc_feedback_kind": kind,
		}
	).insert(ignore_permissions=True)
	if shot:
		extension, content = shot
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"feedback-{issue.name}.{extension}",
				"content": content,
				"is_private": 1,
				"attached_to_doctype": "Issue",
				"attached_to_name": issue.name,
			}
		).insert(ignore_permissions=True)
	notification.emit(EVENT, doc=issue, subject=issue.subject)
	return issue.name
