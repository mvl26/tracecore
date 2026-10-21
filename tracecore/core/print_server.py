"""Đường in từ server (A-05 R1, ADR-006 dự phòng): background job gửi ZPL của Print Job tới máy in nhãn qua TCP.

Dùng khi lệnh in không đi qua kiosk/Station Agent (in nhãn đối tượng từ Desk). Quy tắc:

- **Địa chỉ chỉ từ Printer**: host/port lấy từ DocType Printer của job, máy in phải đang hoạt động, host không rỗng,
  port trong 1..65535. Không hàm công khai nào nhận host/port; `data` của job không bao giờ được đọc làm địa chỉ.
  Máy in chỉ-qua-agent (host rỗng) → server không gửi, job giữ nguyên.
- **Thử tối đa 3 lần**: mỗi lần mở kết nối với timeout `SEND_TIMEOUT_S`; lỗi mạng (`OSError`, gồm timeout/từ chối)
  → `attempts + 1` và ghi `error`, còn dưới `MAX_ATTEMPTS` thì giữ `Queued`, đủ thì `ack(..., "Failed")`.
  Lỗi bất ngờ khác (vd `UnicodeEncodeError`) trong lần quét định kỳ cũng tính một lần thử — không thử lại vô hạn.
- **Không gửi trùng**: chỉ job `Queued` được gửi; dòng job bị khóa (`FOR UPDATE`) trong lúc gửi nên hai worker cùng
  job (enqueue + quét định kỳ) không in hai lần; job đã `Printed`/`Failed` trả nguyên trạng thái. Kết quả mỗi lần
  gửi được **commit ngay** (đây là đường worker, không phải request): nhãn đã ra giấy thì `Printed` không bị một lỗi
  hay rollback sau đó hoàn tác, nên không in lại.
- **Quét định kỳ** (`dispatch_pending`, cron mỗi phút): chỉ job đã đánh dấu đi đường server
  (`enqueue_server_dispatch`) và không đổi trong 1 phút — job của kiosk/Station Agent không bao giờ bị server gửi.

**Ngữ nghĩa giao nhận: ít nhất một lần (at-least-once), không phải đúng một lần.** Raw TCP 9100 không có ack ở tầng
ứng dụng: `sendall` thành công chỉ nghĩa là byte đã vào bộ đệm TCP. Nếu máy in nhận một phần (hoặc toàn bộ) ZPL rồi
kết nối mới bị timeout/reset, server ghi lần thử lỗi và gửi lại ở lần sau → máy in có thể ra **hai nhãn giống hệt**
(cùng mã, cùng QR). Chấp nhận được vì nhãn QR đối tượng chỉ mang mã trần, in trùng không sinh mã mới hay đổi dữ liệu;
R10 bỏ nhãn thừa. Ngược lại không bao giờ có chuyện job `Printed` mà không gửi byte nào.
"""

import socket
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tracecore.core import print as core_print

# Timeout cho MỖI địa chỉ mà create_connection thử, không bao phân giải tên (getaddrinfo không bị giới hạn):
# cấu hình Printer.host bằng địa chỉ IP để worker không treo khi DNS chậm.
SEND_TIMEOUT_S = 5
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=1)
SERVER_ROUTE = "server"  # giá trị khóa `dispatch` trong `Print Job.data`
DISPATCH_METHOD = "tracecore.core.print_server.dispatch_job"
PENDING_SCAN_FACTOR = (
	5  # cỡ một trang đọc = limit * hệ số; đọc tiếp trang sau tới khi đủ `limit` job gửi được
)
# chuỗi đúng như `frappe.as_json` ghi khóa đánh dấu (indent=1, separators ", " / ": ") — lọc trước bằng SQL LIKE
SERVER_MARK = f'"dispatch": "{SERVER_ROUTE}"'


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


def _record_printed(job, output_ref):
	"""Ghi `Printed` sau khi byte đã gửi. `ack` lỗi → vẫn ghi tối thiểu bằng `db.set_value` để job không bị gửi lại."""
	savepoint = f"tc_print_ack_{job}"
	frappe.db.savepoint(savepoint)
	try:
		core_print.ack(job, "Printed", "Printer", output_ref=output_ref)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		attempts = cint(frappe.db.get_value("Print Job", job, "attempts"))
		frappe.db.set_value(
			"Print Job",
			job,
			{
				"status": "Printed",
				"output_mode": "Printer",
				"output_ref": output_ref,
				"error": None,
				"attempts": attempts + 1,
				"printed_at": now_datetime(),
			},
		)
		frappe.log_error(
			title=_("Print job {0} was printed but its result could not be saved normally").format(job)
		)


def dispatch_job(job):
	"""Gửi ZPL của Print Job `Queued` tới máy in của job; trả `{"status", "attempts"}` sau lần gửi.

	Job không `Queued`, không có payload, hoặc máy in không gửi được từ server (không có, không hoạt động, host rỗng,
	port sai) → không gửi, trả trạng thái hiện tại. Thành công → `Printed` với `output_ref = "host:port"`.
	Chỉ chạy trong background job/scheduler: kết quả lần gửi được `frappe.db.commit()` ngay.
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
		_record_printed(doc.name, output_ref)
	frappe.db.commit()  # nosemgrep: worker path — nhãn đã ra giấy thì kết quả phải bền trước mọi bước sau
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
	"""Job `Queued` đường server không đổi trong `RETRY_AFTER`, cũ nhất trước, máy in gửi được từ server.

	`data` lọc trước bằng SQL (`LIKE` chuỗi đánh dấu) rồi kiểm lại khóa cấp đầu trong Python; đọc theo trang tới khi
	đủ `limit` hoặc hết, nên job kiosk hay job đường server của máy in không gửi được không chiếm chỗ job gửi được.
	"""
	if limit <= 0:
		return []
	page = limit * PENDING_SCAN_FACTOR
	filters = {
		"status": "Queued",
		"printer": ["is", "set"],
		"attempts": ["<", MAX_ATTEMPTS],
		"modified": ["<", now_datetime() - RETRY_AFTER],
		"data": ["like", f"%{SERVER_MARK}%"],
	}
	addresses = {}
	names = []
	start = 0
	while True:
		rows = frappe.get_all(
			"Print Job",
			filters=filters,
			fields=["name", "printer", "data"],
			order_by="modified asc, name asc",
			limit_start=start,
			limit_page_length=page,
		)
		for row in rows:
			if _data(row.data).get("dispatch") != SERVER_ROUTE:
				continue
			if row.printer not in addresses:
				addresses[row.printer] = printer_address(row.printer)
			if addresses[row.printer] is not None:
				names.append(str(row.name))
				if len(names) >= limit:
					return names
		if len(rows) < page:
			return names
		start += page


def _count_unexpected_failure(job, error):
	"""Lỗi bất ngờ (không phải lỗi mạng) khi gửi: vẫn tính một lần thử, đủ `MAX_ATTEMPTS` thì `Failed`."""
	row = frappe.db.get_value("Print Job", job, ["status", "attempts", "printer"], as_dict=True)
	if not row or row.status != "Queued":
		return  # đã Printed/Failed (kết quả đã commit) — không đụng
	attempts = cint(row.attempts) + 1
	values = {"attempts": attempts, "error": _("Print job {0}: {1}").format(job, repr(error))}
	if attempts >= MAX_ATTEMPTS:
		values.update({"status": "Failed", "output_mode": "Printer"})
	frappe.db.set_value("Print Job", job, values)


def dispatch_pending(limit=20):
	"""Scheduler mỗi phút: gửi lại các job đường server còn `Queued`; trả số job đã thử gửi.

	Mỗi job được commit ngay sau khi gửi (trong `dispatch_job`), nên lỗi hay rollback ở job sau không hủy kết quả
	`Printed` của job đã in. Lỗi bất ngờ của một job → rollback phần chưa commit của job đó, tính một lần thử,
	ghi Error Log, commit, rồi làm tiếp job khác.
	"""
	dispatched = 0
	for name in _pending_jobs(cint(limit)):
		try:
			dispatch_job(name)
		except Exception as error:
			frappe.db.rollback()
			_count_unexpected_failure(name, error)
			frappe.log_error(title=_("Print job {0} could not be dispatched").format(name))
			frappe.db.commit()  # nosemgrep: scheduler path — lần thử phải bền để không thử lại vô hạn
			continue
		dispatched += 1
	return dispatched
