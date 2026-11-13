"""RPC tracecore.v1.flow.* — phần đọc của cổng khoa trên Page tc-flow (FEAT-099, A-158, FR-M9-31).

Chỉ đọc, phiên Desk. Khoa lấy từ danh mục khoa nhận cấp phát; gói tại khoa dùng lại
``reprocessing.usage.department_overview`` (cùng dữ liệu màn T8). Giới hạn khoa như truy xuất gói:
R01/R02 xem mọi khoa, R08 chỉ khoa của mình. Không trả mã người bệnh.
"""

import frappe
from frappe import _

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


@frappe.whitelist(methods=["GET"])
def department_stock(department=None):
	"""Gói đang tại khoa và gói đã dùng chờ trả về tiếp nhận: ``{"ok", "department", "department_name", ...}``."""
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
	return {"ok": True, **usage_service.department_overview(name)}
