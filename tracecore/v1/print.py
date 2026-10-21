"""RPC tracecore.v1.print.*: nhãn thử và ack của Station Agent (role TC Agent, API key); nhãn QR đối tượng từ Desk."""

import base64

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import print as core_print
from tracecore.core import print_server, qr
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.v1 import codes
from tracecore.v1._common import (
	AGENT_ROLE,
	BadRequestError,
	reject_block,
	require_agent_for,
	require_any_role,
	require_role,
	require_station,
)

LABEL_ROLES = ("TC R10", "System Manager")  # in nhãn đối tượng (A-05 R8)
PREVIEW_ROLES = ("TC R10", "TC R02", "System Manager")  # R02 chỉ xem trước
MAX_STATUS_JOBS = 50  # cùng giới hạn lô in của Desk (tracecore.codes.MAX_BULK)
STATUS_FIELDS = ["name", "status", "attempts", "error", "printed_at"]


@frappe.whitelist(methods=["POST"])
@idempotent
def test_label(station, client_ts=None):
	"""Tạo Print Job nhãn thử cho trạm; trả ZPL và ảnh xem trước (base64)."""
	require_role(AGENT_ROLE)
	require_agent_for(station)  # trước require_station: agent không dò được trạm khác (tồn tại, đang tắt)
	require_station(station)
	label = core_print.render_test_label(station)
	job = core_print.create_job(
		station, label["zpl"], {"giai": label["giai"], "hri": label["hri"]}, "test-label"
	)
	return {
		"print_job": job,
		"giai": label["giai"],
		"zpl": label["zpl"],
		"preview_png_b64": base64.b64encode(label["preview_png"]).decode("ascii"),
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def ack(print_job, status, output_mode, client_ts=None, output_ref=None, error=None):
	"""Agent báo kết quả in — chỉ cho Print Job thuộc trạm của chính agent."""
	require_role(AGENT_ROLE)
	station = frappe.db.get_value("Print Job", print_job, "station")
	if station:
		require_agent_for(station)
	return core_print.ack(print_job, status, output_mode, output_ref=output_ref, error=error)


# ---------------------------------------------------------------------------------------------------------
# Nhãn QR đối tượng từ Desk (FEAT-005, A-05 R1/R2/R4/R8)
# ---------------------------------------------------------------------------------------------------------


def _label_object(value):
	if not isinstance(value, str) or value not in core_print.OBJECT_LABELS:
		raise BadRequestError(
			_("label_object must be one of {0}.").format(", ".join(core_print.OBJECT_LABELS))
		)
	return value


def _desk_printer(name):
	"""Printer đang hoạt động mà R10 chọn; không có/không hoạt động → 400 (tham số sai, chưa ghi gì)."""
	if not isinstance(name, str) or not name:
		raise BadRequestError(_("printer must be a printer name."))
	row = frappe.db.get_value(
		"Printer", name, ["name", "station", "language", "supports_unicode", "is_active"], as_dict=True
	)
	if not row or not cint(row.is_active):
		raise BadRequestError(_("Printer {0} does not exist or is not active.").format(name))
	return row


def _render_object(label_object, target, printer=None):
	"""`((zpl, mẫu đã dùng), None)` hoặc `(None, Block LABEL_RENDER_FAILED)` (chưa có mẫu active, mẫu lỗi), không msgprint."""
	logged = len(frappe.local.message_log)
	try:
		return core_print.render_object(
			label_object,
			target["code"],
			target["title"],
			target["subtitle"],
			printer=printer,
			with_template=True,
		), None
	except frappe.ValidationError as error:
		del frappe.local.message_log[logged:]
		return None, Block(
			"LABEL_RENDER_FAILED",
			_("Label could not be rendered"),
			str(error),
			_("Ask R10 to check the active label template for this object."),
		)


def _resolve_and_render(label_object, code, printer=None, client_ts=None):
	"""``(target, (zpl, mẫu), None)`` hoặc ``(None, None, body từ chối)`` (Audit Log `Reject` + mã HTTP)."""
	try:
		target = codes.resolve_object(label_object, code)
	except BlockedError as error:
		raw = code if isinstance(code, str) else None
		return None, None, reject_block(error.block, raw=raw, client_ts=client_ts)
	rendered, block = _render_object(label_object, target, printer)
	if block:
		return None, None, reject_block(block, target["ref_doctype"], target["ref_name"], client_ts=client_ts)
	return target, rendered, None


@frappe.whitelist(methods=["POST"])
@idempotent
def object_label(label_object, code, printer=None, client_ts=None):
	"""In nhãn QR của đối tượng có mã `code` ra máy in `printer` (Desk, R10/System Manager).

	Tạo Print Job (ref = đối tượng, mẫu active của `label_object`). Máy in có địa chỉ mạng → ``Queued`` và gửi qua
	đường server (`print_server.enqueue_server_dispatch`, cron thử lại); máy in chỉ qua agent → ``Waiting`` kèm cảnh
	báo ``PRINTER_AGENT_ONLY`` (không phải lỗi HTTP). Trả ``{"ok": true, "print_job", "status", "warning"}``.
	Từ chối nghiệp vụ như `codes.resolve_object` và ``LABEL_RENDER_FAILED`` (422); `label_object`/`printer` sai → 400.
	"""
	require_any_role(*LABEL_ROLES)
	timestamp = parse_client_ts(client_ts)
	label_object = _label_object(label_object)
	row = _desk_printer(printer)
	target, rendered, rejected = _resolve_and_render(label_object, code, row, timestamp)
	if rejected:
		return rejected
	zpl, template = rendered  # đúng mẫu đã render, không tra lại (mẫu có thể vừa bị tắt → None.name)
	job = {
		"station": row.station,
		"data": {"label_object": label_object, "code": target["code"]},
		"template": template.name,
		"printer": row.name,
		"ref_doctype": target["ref_doctype"],
		"ref_name": target["ref_name"],
	}
	if print_server.printer_address(row.name) is None:
		name = core_print.create_job(zpl=None, status="Waiting", **job)
		warning = {
			"code": "PRINTER_AGENT_ONLY",
			"title": _("Printer not reachable from Desk"),
			"reason": _(
				"Printer {0} has no network address the server can send to; it only prints through the Station Agent."
			).format(row.name),
			"action": _(
				"Choose a printer with a network address, or ask R10 to set the printer host and port."
			),
		}
		return {"ok": True, "print_job": name, "status": "Waiting", "warning": warning}
	name = core_print.create_job(zpl=zpl, status="Queued", **job)
	print_server.enqueue_server_dispatch(name)
	return {"ok": True, "print_job": name, "status": "Queued", "warning": None}


@frappe.whitelist(methods=["POST"])
def object_preview(label_object, code):
	"""Xem trước nhãn QR của đối tượng (chỉ đọc; R10, R02, System Manager): ``{"ok", "png_b64", "zpl", "hri"}``.

	ZPL dựng như máy in không Unicode (bỏ dấu); PNG vẽ QR + chữ bỏ dấu theo bố cục mẫu mặc định. Từ chối như
	`object_label` (mã ``Disabled``/thiết bị ``Retired`` không xem trước được vì không in được).
	"""
	require_any_role(*PREVIEW_ROLES)
	label_object = _label_object(label_object)
	target, rendered, rejected = _resolve_and_render(label_object, code)
	if rejected:
		return rejected
	zpl = rendered[0]
	png = qr.label_preview_png(
		target["code"],
		[
			(36, 40, target["code"]),
			(96, 28, core_print.fold(target["title"])),
			(212, 24, core_print.fold(target["subtitle"])),
		],
	)
	return {
		"ok": True,
		"png_b64": base64.b64encode(png).decode("ascii"),
		"zpl": zpl,
		"hri": target["code"],
	}


def _job_names(names):
	"""Tên Print Job (list hoặc chuỗi JSON của list; tên là số tự tăng, nhận số hoặc chuỗi), 1..MAX_STATUS_JOBS; sai → 400."""
	if isinstance(names, str):
		try:
			names = frappe.parse_json(names)
		except ValueError:
			names = None
	if (
		not isinstance(names, list)
		or not 0 < len(names) <= MAX_STATUS_JOBS
		or not all(_job_name(name) for name in names)
	):
		raise BadRequestError(_("names must be a list of 1 to {0} print job names.").format(MAX_STATUS_JOBS))
	return [_job_name(name) for name in names]


def _job_name(value):
	if isinstance(value, bool):
		return None
	if isinstance(value, int):
		return str(value) if value > 0 else None
	return value.strip() if isinstance(value, str) and value.strip() else None


@frappe.whitelist()
def job_status(names):
	"""Kết quả các Print Job mà Desk vừa tạo (chỉ đọc; R10/System Manager, kiểm quyền trước).

	Trả ``{"ok": true, "jobs": {tên: {"status", "attempts", "error", "printed_at"}}}``; tên không có thì bỏ qua.
	`printed_at` là chuỗi ``YYYY-MM-DD HH:MM:SS`` (giờ hệ thống) hoặc None. Hộp thoại in của Desk hỏi lại vài giây một
	lần tới khi job ``Printed``/``Failed`` để R10 thấy "Đã in" hay "Không in được: lý do" thay vì dừng ở "Đã xếp hàng".
	"""
	require_any_role(*LABEL_ROLES)
	names = _job_names(names)
	rows = frappe.get_all("Print Job", filters={"name": ["in", names]}, fields=STATUS_FIELDS)
	return {
		"ok": True,
		"jobs": {
			str(row.name): {
				"status": row.status,
				"attempts": cint(row.attempts),
				"error": row.error or None,
				"printed_at": str(row.printed_at) if row.printed_at else None,
			}
			for row in rows
		},
	}
