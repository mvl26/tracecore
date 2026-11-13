"""RPC tracecore.v1.flow.* — phần đọc của cổng khoa trên Page tc-flow (FEAT-099, A-158, FR-M9-31).

Chỉ đọc, phiên Desk. Khoa lấy từ danh mục khoa nhận cấp phát; gói tại khoa dùng lại
``reprocessing.usage.department_overview`` (cùng dữ liệu màn T8). Giới hạn khoa như truy xuất gói:
R01/R02 xem mọi khoa, R08 chỉ khoa của mình. Không trả mã người bệnh.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.reprocessing import issuing
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


def _recall_pending(department):
	"""Gói của khoa trong lệnh thu hồi đang mở mà khoa chưa xác nhận."""
	return cint(
		frappe.db.sql(
			"""select count(*) from `tabRecall Order Pack` line
			join `tabRecall Order` recall on recall.name = line.parent and line.parenttype = 'Recall Order'
			where recall.docstatus = 1 and recall.status = 'Open' and line.department = %s
				and ifnull(line.line_status, '') != 'Confirmed'""",
			(department,),
		)[0][0]
	)


@frappe.whitelist(methods=["GET"])
def department_stock(department=None):
	"""Bộ tại khoa và cơ số: 4 số liệu, gói đang tại khoa (kèm Set ID, loại bộ), gói đã dùng chờ trả.

	``counts.held`` đếm như tồn khoa của cấp phát (gói `Issued` của khoa); ``counts.waiting_return`` là gói đã dùng mà
	bộ chưa về trạm tiếp nhận (chưa có chứng từ "yêu cầu trả đồ bẩn" riêng).
	"""
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
			"recall_pending": _recall_pending(name),
			"waiting_return": len(overview["waiting_return"]),
		},
	}
