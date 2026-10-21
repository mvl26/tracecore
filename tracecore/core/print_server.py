"""Đường in từ server (A-05 R1, ADR-006 dự phòng): background job gửi ZPL của Print Job tới máy in nhãn qua TCP.

Dùng khi lệnh in không đi qua kiosk/Station Agent (in nhãn đối tượng từ Desk). Quy tắc:

- **Địa chỉ chỉ từ Printer**: host/port lấy từ DocType Printer của job, máy in phải đang hoạt động, host không rỗng,
  port trong 1..65535. Không hàm công khai nào nhận host/port; `data` của job không bao giờ được đọc làm địa chỉ.
  Máy in chỉ-qua-agent (host rỗng) → server không gửi, job giữ nguyên.
- **Thử tối đa 3 lần**: mỗi lần mở kết nối với timeout `SEND_TIMEOUT_S`; lỗi mạng (`OSError`, gồm timeout/từ chối)
  → `attempts + 1` và ghi `error`, còn dưới `MAX_ATTEMPTS` thì giữ `Queued`, đủ thì `ack(..., "Failed")`.
- **Không gửi trùng**: chỉ job `Queued` được gửi; dòng job bị khóa (`FOR UPDATE`) trong lúc gửi nên hai worker cùng
  job (enqueue + quét định kỳ) không in hai lần; job đã `Printed`/`Failed` trả nguyên trạng thái.
- **Quét định kỳ** (`dispatch_pending`, cron mỗi phút): chỉ job đã đánh dấu đi đường server
  (`enqueue_server_dispatch`) và không đổi trong 1 phút — job của kiosk/Station Agent không bao giờ bị server gửi.
"""

import socket
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tracecore.core import print as core_print

SEND_TIMEOUT_S = 5
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=1)
SERVER_ROUTE = "server"  # giá trị khóa `dispatch` trong `Print Job.data`
DISPATCH_METHOD = "tracecore.core.print_server.dispatch_job"
PENDING_SCAN_FACTOR = 5  # đọc dư để lọc job đường server trong Python (`data` là JSON)


def _result(doc):
	return {"status": doc.status, "attempts": cint(doc.attempts)}


def _data(value):
	data = frappe.parse_json(value) if value else {}
	return data if isinstance(data, dict) else {}


def printer_address(printer):
	"""`(host, port)` của Printer đang hoạt động có host và port hợp lệ, hoặc None (không gửi từ server được)."""
	if not printer:
		return None
	row = frappe.db.get_value("Printer", printer, ["host", "port", "is_active"], as_dict=True)
	if not row or not cint(row.is_active):
		return None
	host = (row.host or "").strip()
	port = cint(row.port)
	if not host or any(char.isspace() for char in host) or not 1 <= port <= 65535:
		return None
	return host, port


def _send(host, port, payload):
	# host/port chỉ từ Printer do R10/System Manager cấu hình (printer_address), không từ client hay `data` của job
	with socket.create_connection((host, port), timeout=SEND_TIMEOUT_S) as conn:
		conn.sendall(payload.encode("utf-8"))


def dispatch_job(job):
	"""Gửi ZPL của Print Job `Queued` tới máy in của job; trả `{"status", "attempts"}` sau lần gửi.

	Job không `Queued`, không có payload, hoặc máy in không gửi được từ server (không có, không hoạt động, host rỗng,
	port sai) → không gửi, trả trạng thái hiện tại. Thành công → `Printed` với `output_ref = "host:port"`.
	"""
	doc = frappe.get_doc("Print Job", job, for_update=True)
	if doc.status != "Queued" or not doc.payload:
		return _result(doc)
	address = printer_address(doc.printer)
	if address is None:
		return _result(doc)
	host, port = address
	output_ref = f"{host}:{port}"
	try:
		_send(host, port, doc.payload)
	except OSError as error:
		reason = _("Printer {0} at {1} could not be reached: {2}").format(doc.printer, output_ref, error)
		if cint(doc.attempts) + 1 >= MAX_ATTEMPTS:
			core_print.ack(doc.name, "Failed", "Printer", output_ref=output_ref, error=reason)
		else:
			doc.update({"attempts": cint(doc.attempts) + 1, "error": reason})
			doc.save(ignore_permissions=True)
	else:
		core_print.ack(doc.name, "Printed", "Printer", output_ref=output_ref)
	return _result(frappe.get_doc("Print Job", doc.name))


def enqueue_server_dispatch(job):
	"""Đánh dấu Print Job đi đường server và xếp `dispatch_job` vào hàng `short` sau khi transaction commit."""
	doc = frappe.get_doc("Print Job", job)
	data = _data(doc.data)
	data["dispatch"] = SERVER_ROUTE
	doc.db_set("data", frappe.as_json(data))
	frappe.enqueue(
		DISPATCH_METHOD,
		queue="short",
		enqueue_after_commit=True,
		job_id=f"tc-print-job-{doc.name}",
		deduplicate=True,
		job=str(doc.name),
	)


def _pending_jobs(limit):
	"""Job `Queued` đường server không đổi trong `RETRY_AFTER`, cũ nhất trước, máy in gửi được từ server."""
	rows = frappe.get_all(
		"Print Job",
		filters={
			"status": "Queued",
			"printer": ["is", "set"],
			"attempts": ["<", MAX_ATTEMPTS],
			"modified": ["<", now_datetime() - RETRY_AFTER],
		},
		fields=["name", "printer", "data"],
		order_by="modified asc, name asc",
		limit=limit * PENDING_SCAN_FACTOR,
	)
	addresses = {}
	names = []
	for row in rows:
		if _data(row.data).get("dispatch") != SERVER_ROUTE:
			continue
		if row.printer not in addresses:
			addresses[row.printer] = printer_address(row.printer)
		if addresses[row.printer] is not None:
			names.append(str(row.name))
		if len(names) >= limit:
			break
	return names


def dispatch_pending(limit=20):
	"""Scheduler mỗi phút: gửi lại các job đường server còn `Queued`; trả số job đã thử gửi.

	Lỗi bất ngờ của một job (không phải lỗi mạng) được hoàn tác tới savepoint, ghi Error Log, rồi làm tiếp job khác:
	một job hỏng không được hủy kết quả `Printed` của các job đã in trong cùng lần quét.
	"""
	dispatched = 0
	for name in _pending_jobs(cint(limit)):
		savepoint = f"tc_print_dispatch_{name}"
		frappe.db.savepoint(savepoint)
		try:
			dispatch_job(name)
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			frappe.log_error(title=_("Print job {0} could not be dispatched").format(name))
			continue
		dispatched += 1
	return dispatched
