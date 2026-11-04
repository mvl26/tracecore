"""RPC tracecore.v1.print.*: nhãn thử và ack của Station Agent (role TC Agent, API key); nhãn QR đối tượng từ Desk."""

import base64

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import label_pdf as core_label_pdf
from tracecore.core import print as core_print
from tracecore.core import qr
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.v1 import codes
from tracecore.v1._common import (
	AGENT_ROLE,
	BadRequestError,
	desk_printer,
	job_names,
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
	"""Printer đang hoạt động mà R10 chọn; không có/không hoạt động → 400 (`_common.desk_printer`)."""
	return desk_printer(name)


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
	"""Xếp nhãn QR của đối tượng có mã `code` để in qua `objects_pdf` (Desk, R10/System Manager; A-114).

	Tạo Print Job ``Queued`` (ref = đối tượng); máy in `printer` tùy chọn, mặc định máy in nhãn chung; ZPL theo mẫu
	active chỉ dựng để lưu vết, mẫu thiếu/lỗi không chặn vì nhãn in ra PDF. Trả ``{"ok": true, "print_job", "status",
	"warning"}``. Từ chối nghiệp vụ như `codes.resolve_object`; `label_object`/`printer` sai → 400.
	"""
	require_any_role(*LABEL_ROLES)
	timestamp = parse_client_ts(client_ts)
	label_object = _label_object(label_object)
	row = _desk_printer(printer) if printer not in (None, "") else core_print.label_printer()
	try:
		target = codes.resolve_object(label_object, code)
	except BlockedError as error:
		return reject_block(error.block, raw=code if isinstance(code, str) else None, client_ts=timestamp)
	rendered, _block = _render_object(label_object, target, row) if row else (None, None)
	zpl, template = rendered or (None, None)
	name = core_print.create_job(
		row.get("station") if row else None,
		zpl,
		{
			"label_object": label_object,
			"code": target["code"],
			"title": target["title"],
			"subtitle": target["subtitle"],
		},
		template=template.name if template else None,
		printer=row["name"] if row else None,
		ref_doctype=target["ref_doctype"],
		ref_name=target["ref_name"],
	)
	return {"ok": True, "print_job": name, "status": "Queued", "warning": None}


@frappe.whitelist(methods=["POST"])
def test_pdf(client_ts=None):
	"""Nhãn thử PDF đúng khổ nhãn chung (A-114) để R10 kiểm khổ giấy, lề và driver của máy in; không ghi gì."""
	require_any_role(*LABEL_ROLES)
	width, height = core_label_pdf.label_size()
	try:
		pdf = core_label_pdf.qr_pdf(
			"TEST-LABEL",
			_("Test label"),
			[
				_("Label size {0} x {1} mm").format(f"{width:g}", f"{height:g}"),
				frappe.utils.now_datetime().strftime("%d/%m/%Y %H:%M"),
			],
		)
	except BlockedError as error:
		return reject_block(error.block)
	return {"ok": True, **core_label_pdf.encode(pdf, "TEST-LABEL.pdf")}


@frappe.whitelist(methods=["POST"])
def objects_pdf(print_jobs, client_ts=None):
	"""Một PDF nhiều trang cho các nhãn QR đối tượng vừa xếp (`object_label`), rồi ghi ``Printed``/``Browser`` (A-114).

	Không ``@idempotent`` (như `pack.waiting_labels_pdf`). Chỉ job ``Queued`` của nhãn đối tượng; job khác bị bỏ qua
	(``skipped``); không còn nhãn nào → ``LABEL_NOT_QUEUED``. Trả ``{"ok": true, "pdf_b64", "filename", "print_jobs",
	"skipped"}``.
	"""
	require_any_role(*LABEL_ROLES)
	names = [str(name) for name in _job_names(print_jobs)]
	pages, printed, skipped = [], [], []
	try:
		for name in names:
			job = frappe.db.get_value("Print Job", name, ["name", "status", "data"], as_dict=True)
			data = frappe.parse_json(job.data) if job and job.data else {}
			if (
				not job
				or job.status != "Queued"
				or not isinstance(data, dict)
				or data.get("label_object") not in core_print.OBJECT_LABELS
			):
				skipped.append(name)
				continue
			pages.append(
				core_label_pdf.object_pdf(
					data.get("code") or "", data.get("title") or "", data.get("subtitle") or ""
				)
			)
			printed.append(name)
		if not pages:
			raise BlockedError(
				Block(
					"LABEL_NOT_QUEUED",
					_("Label is not ready to print"),
					_("None of the {0} label(s) can be printed.").format(len(names)),
					_("Print the labels again from the record, or call R02."),
				)
			)
	except BlockedError as error:
		return reject_block(error.block, "Print Job", names[0])
	first = frappe.parse_json(frappe.db.get_value("Print Job", printed[0], "data"))["code"]
	filename = f"{first}.pdf" if len(printed) == 1 else f"{first}-{len(printed)}.pdf"
	pdf = core_label_pdf.merge(pages)
	for name in printed:
		core_print.mark_browser_output(name, filename)
	return {"ok": True, **core_label_pdf.encode(pdf, filename), "print_jobs": printed, "skipped": skipped}


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
	"""Tên Print Job, 1..MAX_STATUS_JOBS; sai → 400 (`_common.job_names`)."""
	return job_names(names, MAX_STATUS_JOBS)


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
