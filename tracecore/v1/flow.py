"""RPC tracecore.v1.flow.* — cổng khoa trên Page tc-flow (FEAT-099, A-158, FR-M9-31; FEAT-100, A-160, FR-M2-26).

Phiên Desk. RPC ghi duy nhất là `request_return` (yêu cầu lấy đồ bẩn, `@idempotent`), còn lại chỉ đọc. Khoa lấy từ danh mục khoa nhận cấp phát; gói tại khoa dùng lại
``reprocessing.usage.department_overview`` (cùng dữ liệu màn T8). Giới hạn khoa như truy xuất gói:
R01/R02 xem mọi khoa, R08 chỉ khoa của mình. Không trả mã người bệnh.
"""

import frappe
from frappe import _
from frappe.utils import cint, today

from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.linen import received as linen_received_service
from tracecore.reprocessing import department_recall, dirty_return, issue_request, issuing
from tracecore.reprocessing import usage as usage_service

SEE_ALL_ROLES = {"TC R01", "TC R02", "System Manager"}
WARD_ROLE = "TC R08"
WARD_FILTERS = {"is_group": 0, "disabled": 0, "tc_is_ward": 1}


def _own_department(user):
	return frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "department")


def _scope():
	"""None = mọi khoa; tên khoa = chỉ khoa đó (R08); không được xem → PermissionError."""
	user = frappe.session.user
	roles = set(frappe.get_roles())
	if user == "Administrator" or roles & SEE_ALL_ROLES:
		return None
	if WARD_ROLE in roles:
		return _own_department(user) or "-"
	frappe.throw(
		_("Only R01, R02 or department staff can open the department portal."), frappe.PermissionError
	)


@frappe.whitelist(methods=["GET"])
def departments():
	"""Khoa mà người gọi được mở cổng khoa: ``{"ok", "departments": [{"name", "label"}]}``."""
	scope = _scope()
	filters = dict(WARD_FILTERS)
	if scope is not None:
		filters["name"] = scope
	rows = frappe.get_all(
		"Department",
		filters=filters,
		fields=["name", "department_name"],
		order_by="department_name asc, name asc",
	)
	return {
		"ok": True,
		"departments": [{"name": row.name, "label": row.department_name or row.name} for row in rows],
	}


REPROCESSING_STATUSES = ("Processing", "Reprocess")


def _held_packs(overview):
	"""Gói đang tại khoa của `department_overview`, thêm Set ID và loại bộ của từng gói."""
	rows = overview["at_department"]
	if not rows:
		return []
	packs = {
		row.name: row
		for row in frappe.get_all(
			"Pack",
			filters={"name": ["in", [row["cycle_id"] for row in rows]]},
			fields=["name", "set_unit", "set_type"],
		)
	}
	for row in rows:
		pack = packs.get(row["cycle_id"])
		row["set_id"] = pack.set_unit if pack else None
		row["set_type"] = pack.set_type if pack else None
	return rows


def _par_range(department):
	"""Cơ số tồn khoa cộng theo mọi loại bộ đang đặt cơ số: ``{"min", "max"}``; chưa đặt → None."""
	rows = frappe.get_all(
		"Par Level",
		filters={
			"par_kind": "Department Stock",
			"target_doctype": "Instrument Set Type",
			"department": department,
			"is_active": 1,
		},
		fields=["min_qty", "max_qty"],
	)
	if not rows:
		return None
	return {"min": sum(cint(row.min_qty) for row in rows), "max": sum(cint(row.max_qty) for row in rows)}


def _ward(department):
	"""Tên khoa nhận cấp phát mà người gọi được mở; không có → DoesNotExistError, khoa khác → PermissionError."""
	scope = _scope()
	name = (
		frappe.db.get_value("Department", {**WARD_FILTERS, "name": department}, "name")
		if isinstance(department, str) and department
		else None
	)
	if not name:
		frappe.throw(_("Department {0} does not exist.").format(department or "-"), frappe.DoesNotExistError)
	if scope is not None and scope != name:
		frappe.throw(_("You can only see the packs of your own department."), frappe.PermissionError)
	return name


@frappe.whitelist(methods=["GET"])
def return_overview(department=None):
	"""Gửi trả đồ bẩn (FEAT-100, FR-M2-26): bộ có thể trả và yêu cầu khoa đã gửi hôm nay."""
	name = _ward(department)
	return {
		"ok": True,
		"department": name,
		"conditions": list(dirty_return.CONDITIONS),
		"candidates": dirty_return.candidates(name),
		"requests": dirty_return.requests_on(name, today()),
		"sent_sets": dirty_return.sets_on(name, today()),
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def request_return(department=None, items=None, client_ts=None):
	"""Khoa gửi yêu cầu lấy đồ bẩn cho các bộ đã chọn; không đổi trạng thái bộ (BRU-FLOW-003).

	Từ chối nghiệp vụ trả ``{"ok": false, "error": {code, title, reason, action}}`` (mã HTTP 200) để trang hiện
	alert inline; thành công trả tên yêu cầu và danh sách mới như `return_overview`.
	"""
	name = _ward(department)
	try:
		created = dirty_return.create(name, items, parse_client_ts(client_ts))
	except dirty_return.ReturnRejected as error:
		return {"ok": False, "error": error.as_dict()}
	return {**return_overview(name), **created}


@frappe.whitelist(methods=["GET"])
def recall_overview(department=None):
	"""Xác nhận thu hồi (FEAT-101, FR-M9-32): lệnh thu hồi đang mở và các gói của khoa; mã bệnh nhân chỉ dạng che.

	Xác nhận từng gói dùng RPC hiện có `tracecore.v1.recall.confirm_pack` (quy tắc vai trò của FR-M2-20 không đổi).
	"""
	name = _ward(department)
	return {
		"ok": True,
		"department": name,
		"orders": department_recall.open_orders(name),
		"pending": department_recall.pending_count(name),
	}


@frappe.whitelist(methods=["GET"])
def issue_overview(department=None):
	"""Đề nghị cấp bộ dụng cụ (FEAT-101, FR-M2-27): loại bộ kèm cơ số, tồn khoa và đề nghị khoa đã gửi hôm nay."""
	name = _ward(department)
	return {
		"ok": True,
		"department": name,
		"max_qty": issue_request.MAX_QTY,
		"options": issue_request.options(name),
		"requests": issue_request.requests_on(name, today()),
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def request_issue(department=None, set_type=None, qty=None, needed_by=None, client_ts=None):
	"""Khoa gửi đề nghị cấp; không giữ chỗ gói, không đổi trạng thái (FR-M2-27.1).

	Từ chối nghiệp vụ trả ``{"ok": false, "error": {code, title, reason, action}}`` (mã HTTP 200) để trang hiện alert
	inline; thành công trả tên đề nghị và danh sách mới như `issue_overview`.
	"""
	name = _ward(department)
	try:
		created = issue_request.create(name, set_type, qty, needed_by, parse_client_ts(client_ts))
	except issue_request.RequestRejected as error:
		return {"ok": False, "error": error.as_dict()}
	return {**issue_overview(name), **created}


@frappe.whitelist(methods=["GET"])
def linen_received(department=None, month=None):
	"""Đồ vải đã nhận (FEAT-101, FR-M9-32): thu gom, trả về, chênh lệch theo ngày và loại của tháng, định mức."""
	name = _ward(department)
	return {"ok": True, "department": name, **linen_received_service.overview(name, month)}


@frappe.whitelist(methods=["GET"])
def department_stock(department=None):
	"""Bộ tại khoa và cơ số: 4 số liệu, gói đang tại khoa (kèm Set ID, loại bộ), gói đã dùng chờ trả.

	``counts.held`` đếm như tồn khoa của cấp phát (gói `Issued` của khoa); ``counts.waiting_return`` là số bộ
	khoa đã gửi yêu cầu lấy đồ bẩn mà T1 chưa tiếp nhận (`dirty_return.pending_sets`, FEAT-100).
	"""
	name = _ward(department)
	overview = usage_service.department_overview(name)
	return {
		"ok": True,
		"department": overview["department"],
		"department_name": overview["department_name"],
		"at_department": _held_packs(overview),
		"waiting_return": overview["waiting_return"],
		"par": _par_range(name),
		"counts": {
			"held": sum(issuing.department_stock(name).values()),
			"reprocessing": frappe.db.count(
				"Set Unit", {"department": name, "status": ["in", REPROCESSING_STATUSES]}
			),
			"recall_pending": department_recall.pending_count(name),
			"waiting_return": len(dirty_return.pending_sets(name)),
		},
	}
