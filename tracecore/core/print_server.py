"""Đường in từ server (A-05 R1, ADR-006 dự phòng): background job gửi ZPL của Print Job tới máy in nhãn qua TCP.

Dùng khi lệnh in không đi qua kiosk/Station Agent (in nhãn đối tượng từ Desk). Quy tắc:

- **Địa chỉ chỉ từ Printer**: host/port lấy từ DocType Printer của job, máy in phải đang hoạt động, host không rỗng,
  port trong 1..65535. Không hàm công khai nào nhận host/port; `data` của job không bao giờ được đọc làm địa chỉ.
  Máy in chỉ-qua-agent (host rỗng) → server không gửi, job giữ nguyên.
- **Không gửi tới chính server (chặn lúc gửi)**: host là địa chỉ IP dạng chữ thuộc dải loopback, link-local (gồm
  metadata 169.254.169.254), multicast hay unspecified bị `printer_address` bỏ qua, trừ khi site_config bật
  `tracecore_allow_local_printers` (chỉ site dev/e2e, nơi máy in giả nghe trên 127.0.0.1). `Printer.validate` KHÔNG
  chặn các host này: Station Agent trên máy kiosk dùng chính `Printer.host` (cầu nối 127.0.0.1 tới máy in USB, máy in
  APIPA 169.254.x.x), nên lưu Printer và `set_roll` vẫn chạy. Job đường server của máy in như vậy (hoặc host có
  khoảng trắng) không nằm im `Queued`: `dispatch_job` ghi `Failed` kèm lý do. Tên máy (hostname) vẫn được phép:
  R10 chịu trách nhiệm cấu hình máy in thật.
- **Thử tối đa 3 lần**: mỗi lần mở kết nối với timeout `SEND_TIMEOUT_S`; lỗi mạng (`OSError`, gồm timeout/từ chối)
  → `attempts + 1` và ghi `error`, còn dưới `MAX_ATTEMPTS` thì giữ `Queued`, đủ thì `ack(..., "Failed")`.
  Lỗi bất ngờ khác (vd `UnicodeEncodeError`) trong lần quét định kỳ cũng tính một lần thử — không thử lại vô hạn.
- **Không gửi trùng**: chỉ job `Queued` được gửi; dòng job bị khóa (`FOR UPDATE`) trong lúc gửi nên hai worker cùng
  job (enqueue + quét định kỳ) không in hai lần; job đã `Printed`/`Failed` trả nguyên trạng thái. Kết quả mỗi lần
  gửi được **commit ngay** (đây là đường worker, không phải request): nhãn đã ra giấy thì `Printed` không bị một lỗi
  hay rollback sau đó hoàn tác, nên không in lại.
- **Quét định kỳ** (`dispatch_pending`, cron mỗi phút): chỉ job đã đánh dấu đi đường server
  (`enqueue_server_dispatch`) và không đổi trong 1 phút — job của kiosk/Station Agent không bao giờ bị server gửi.

- **Gửi cả lô** (`dispatch_many`, FEAT-016 G9: thẻ kim loại / nhãn khay Set ID, một Print Job mỗi nhãn): một RQ job gửi
  tuần tự, mỗi job commit ngay như `dispatch_job`. Lỗi mạng đầu tiên của một máy in → job đó tính một lần thử, các job
  **sau** của cùng máy in không gửi trong lượt này (giữ `Queued`, không tính lần thử) để worker chỉ chờ tối đa một
  timeout cho mỗi máy in; cron `dispatch_pending` nhặt lại sau `RETRY_AFTER`. Job của máy in khác vẫn gửi.
- **Thẻ Set ID kiểm lại lúc gửi**: job `Set Tag`/`Set Tray Label` mang ZPL đã dựng sẵn; trước khi gửi, Set ID được kiểm
  lại (tiền tố demo trên site không phải dev/test — DB dev chép sang site thật — hoặc mã đã `Disabled`) → `Failed`
  kèm lý do, không gửi.

**Ngữ nghĩa giao nhận: ít nhất một lần (at-least-once), không phải đúng một lần.** Raw TCP 9100 không có ack ở tầng
ứng dụng: `sendall` thành công chỉ nghĩa là byte đã vào bộ đệm TCP. Nếu máy in nhận một phần (hoặc toàn bộ) ZPL rồi
kết nối mới bị timeout/reset, server ghi lần thử lỗi và gửi lại ở lần sau → máy in có thể ra **hai nhãn giống hệt**
(cùng mã, cùng QR). Chấp nhận được vì nhãn QR đối tượng chỉ mang mã trần, in trùng không sinh mã mới hay đổi dữ liệu;
R10 bỏ nhãn thừa. Ngược lại không bao giờ có chuyện job `Printed` mà không gửi byte nào.
"""

import ipaddress
import socket
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tracecore.core import code_registry
from tracecore.core import print as core_print

# Timeout cho MỖI địa chỉ mà create_connection thử, không bao phân giải tên (getaddrinfo không bị giới hạn):
# cấu hình Printer.host bằng địa chỉ IP để worker không treo khi DNS chậm.
SEND_TIMEOUT_S = 5
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=1)
SERVER_ROUTE = "server"  # giá trị khóa `dispatch` trong `Print Job.data`
DISPATCH_METHOD = "tracecore.core.print_server.dispatch_job"
DISPATCH_MANY_METHOD = "tracecore.core.print_server.dispatch_many"
PENDING_SCAN_FACTOR = (
	5  # cỡ một trang đọc = limit * hệ số; đọc tiếp trang sau tới khi đủ `limit` job gửi được
)
# chuỗi đúng như `frappe.as_json` ghi khóa đánh dấu (indent=1, separators ", " / ": ") — lọc trước bằng SQL LIKE
SERVER_MARK = f'"dispatch": "{SERVER_ROUTE}"'
LOCAL_PRINTERS_FLAG = "tracecore_allow_local_printers"  # site_config: cho máy in IP cục bộ (dev/e2e)


def _result(doc):
	return {"status": doc.status, "attempts": cint(doc.attempts)}


def _data(value):
	data = frappe.parse_json(value) if value else {}
	return data if isinstance(data, dict) else {}


def _ip_literal(host):
	"""`ipaddress` của `host` nếu là địa chỉ IP dạng chữ (kể cả dạng socket hiểu như ``127.1``), ngược lại None."""
	# dấu chấm cuối (FQDN gốc, "127.0.0.1.") vẫn được getaddrinfo phân giải về cùng địa chỉ → bỏ trước khi đọc
	text = host.strip().removeprefix("[").removesuffix("]").split("%", 1)[0].rstrip(".")
	try:
		return ipaddress.ip_address(text)
	except ValueError:
		pass
	try:
		return ipaddress.IPv4Address(socket.inet_aton(text))  # 127.1, 2130706433, 0x7f.1 ...
	except (OSError, ValueError):
		return None


def _is_local(ip):
	mapped = getattr(ip, "ipv4_mapped", None)
	if mapped is not None:
		return _is_local(mapped)
	return ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified


def local_printers_allowed():
	"""Cờ site_config `tracecore_allow_local_printers` bật (1/true): chỉ dùng ở site dev/e2e."""
	value = frappe.conf.get(LOCAL_PRINTERS_FLAG)
	return str(value).strip().lower() in ("1", "true", "yes") if value is not None else False


def blocked_host(host):
	"""True nếu `host` là IP dạng chữ loopback/link-local/multicast/unspecified và site không bật cờ máy in cục bộ."""
	if not host or not isinstance(host, str):
		return False
	ip = _ip_literal(host)
	return ip is not None and _is_local(ip) and not local_printers_allowed()


def _host_refused(host):
	"""Host không rỗng nhưng server không được gửi tới: có khoảng trắng bên trong, hoặc IP cục bộ bị chặn."""
	return bool(host) and (any(char.isspace() for char in host) or blocked_host(host))


def _printer_target(printer):
	"""`(host, port, refused)` của Printer đang hoạt động có host; None nếu không có/không hoạt động/host rỗng (agent).

	`refused` = True khi host bị chặn hoặc sai dạng: job đường server của máy in đó phải `Failed`, không nằm im.
	"""
	if not printer:
		return None
	row = frappe.db.get_value("Printer", printer, ["host", "port", "is_active"], as_dict=True)
	if not row or not cint(row.is_active):
		return None
	host = (row.host or "").strip()
	if not host:
		return None
	return host, cint(row.port), _host_refused(host)


def printer_address(printer):
	"""`(host, port)` của Printer đang hoạt động có host và port hợp lệ, hoặc None (không gửi từ server được)."""
	target = _printer_target(printer)
	if target is None:
		return None
	host, port, refused = target
	if refused or not 1 <= port <= 65535:
		return None
	return host, port


def _host_refused_reason(printer):
	"""Lý do (đã dịch) nếu máy in của job có host bị chặn/sai dạng cho đường in từ server, ngược lại None."""
	target = _printer_target(printer)
	if target is None or not target[2]:
		return None
	return _("Printer {0} ({1}): printer host not allowed for server printing").format(printer, target[0])


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


def _set_label_refusal(doc):
	"""Lý do (đã dịch) không được gửi job thẻ kim loại / nhãn khay Set ID, ngược lại None (job khác → None).

	ZPL của job dựng lúc xếp hàng; kiểm lại Set ID lúc gửi: tiền tố chứa trong mã phải dùng được trên site này
	(`code_registry.set_id_block`, G3), bộ chưa ``Disposed`` và mã không `Disabled` trong Code Registry (thanh lý sau
	khi job đã xếp hàng: không ra thêm thẻ của bộ đã thanh lý, G14).
	"""
	data = _data(doc.data)
	if data.get("label_object") not in core_print.SET_LABELS:
		return None
	set_id = doc.ref_name if doc.ref_doctype == "Set Unit" else None
	row = frappe.db.get_value("Set Unit", set_id, ["set_type", "status"]) if set_id else None
	if not row:
		return _("Set ID {0} of this print job does not exist.").format(set_id or "-")
	set_type, status = row
	if status == "Disposed":
		return _("Set {0} has been disposed; its tag and tray label can no longer be printed.").format(set_id)
	type_code = frappe.db.get_value("Instrument Set Type", set_type, "type_code")
	block = code_registry.set_id_block(set_id, type_code)
	if block:
		return _("Set ID {0}: {1}").format(set_id, block.reason)
	if frappe.db.get_value("Code Registry", set_id, "status") == "Disabled":
		return _("Set ID {0} is disabled and cannot be printed.").format(set_id)
	return None


def _dispatch(job):
	"""`(kết quả, lỗi mạng?)` của một lần xử lý job (xem `dispatch_job`)."""
	doc = frappe.get_doc("Print Job", job, for_update=True)
	if doc.status != "Queued" or not doc.payload:
		return _result(doc), False
	refusal = _set_label_refusal(doc)
	if refusal:
		core_print.ack(doc.name, "Failed", "Printer", error=refusal)
		frappe.db.commit()  # nosemgrep: worker path — kết quả lần xử lý phải bền như các nhánh khác
		return _result(frappe.get_doc("Print Job", doc.name)), False
	address = printer_address(doc.printer)
	if address is None:
		reason = _host_refused_reason(doc.printer)
		if reason:  # máy in bị chặn (vd đổi host sau khi job Queued): báo Failed, không để job nằm im Queued
			core_print.ack(doc.name, "Failed", "Printer", error=reason)
			frappe.db.commit()  # nosemgrep: worker path — kết quả lần xử lý phải bền như các nhánh khác
			return _result(frappe.get_doc("Print Job", doc.name)), False
		return _result(doc), False
	host, port = address
	output_ref = f"{host}:{port}"
	network_error = False
	try:
		_send(host, port, doc.payload)
	except OSError as error:
		network_error = True
		reason = _("Printer {0} at {1} could not be reached: {2}").format(doc.printer, output_ref, error)
		if cint(doc.attempts) + 1 >= MAX_ATTEMPTS:
			core_print.ack(doc.name, "Failed", "Printer", output_ref=output_ref, error=reason)
		else:
			doc.update({"attempts": cint(doc.attempts) + 1, "error": reason})
			doc.save(ignore_permissions=True)
	else:
		_record_printed(doc.name, output_ref)
	frappe.db.commit()  # nosemgrep: worker path — nhãn đã ra giấy thì kết quả phải bền trước mọi bước sau
	return _result(frappe.get_doc("Print Job", doc.name)), network_error


def dispatch_job(job):
	"""Gửi ZPL của Print Job `Queued` tới máy in của job; trả `{"status", "attempts"}` sau lần gửi.

	Job không `Queued`, không có payload, hoặc máy in không gửi được từ server (không có, không hoạt động, host rỗng,
	port sai) → không gửi, trả trạng thái hiện tại. Host bị chặn (IP cục bộ khi site không bật cờ) hoặc có khoảng trắng
	→ không gửi, ghi `Failed` qua `ack` kèm lý do đã dịch; job thẻ Set ID không còn in được (`_set_label_refusal`) cũng
	vậy. Thành công → `Printed` với `output_ref = "host:port"`.
	Chỉ chạy trong background job/scheduler: kết quả lần gửi được `frappe.db.commit()` ngay.
	"""
	return _dispatch(job)[0]


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


def enqueue_server_dispatch_many(jobs):
	"""Đánh dấu từng Print Job đi đường server (như `enqueue_server_dispatch`) và xếp **một** `dispatch_many` cho cả lô
	vào hàng `short` sau khi transaction commit. Job nào worker không gửi tới vẫn được `dispatch_pending` nhặt lại."""
	names = [str(job) for job in jobs or []]
	if not names:
		return
	for name in names:
		doc = frappe.get_doc("Print Job", name)
		data = _data(doc.data)
		data["dispatch"] = SERVER_ROUTE
		doc.db_set("data", frappe.as_json(data))
	frappe.enqueue(
		DISPATCH_MANY_METHOD,
		queue="short",
		enqueue_after_commit=True,
		job_id=f"tc-print-batch-{names[0]}-{len(names)}",
		deduplicate=True,
		jobs=names,
	)


def dispatch_many(jobs):
	"""Gửi lần lượt các Print Job `jobs` (theo thứ tự); trả kết quả từng job như `dispatch_job`, cùng thứ tự.

	Mỗi job commit ngay sau lần gửi. Lỗi mạng (`OSError`) đầu tiên của một máy in → job đó tính một lần thử như
	`dispatch_job`; các job sau của **cùng máy in** không gửi trong lượt này (giữ nguyên `Queued`, không đổi
	`attempts`), job của máy in khác vẫn gửi: lượt này chờ tối đa một timeout cho mỗi máy in. Lỗi bất ngờ khác của một
	job → rollback phần chưa commit, tính một lần thử, Error Log, làm tiếp. Chỉ chạy trong background job.
	"""
	results = []
	down = set()
	for name in [str(job) for job in jobs or []]:
		printer = frappe.db.get_value("Print Job", name, "printer")
		if printer in down:
			results.append(_result(frappe.get_doc("Print Job", name)))
			continue
		try:
			result, network_error = _dispatch(name)
		except Exception as error:
			frappe.db.rollback()
			_count_unexpected_failure(name, error)
			frappe.log_error(title=_("Print job {0} could not be dispatched").format(name))
			frappe.db.commit()  # nosemgrep: worker path — lần thử phải bền để không thử lại vô hạn
			results.append(_result(frappe.get_doc("Print Job", name)))
			continue
		if network_error:
			down.add(printer)
		results.append(result)
	return results


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
			if row.printer not in addresses:  # gửi được, hoặc host bị chặn (dispatch_job ghi Failed)
				addresses[row.printer] = (
					printer_address(row.printer) is not None or _host_refused_reason(row.printer) is not None
				)
			if addresses[row.printer]:
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
