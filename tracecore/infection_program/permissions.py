"""Quyền R01/R02 cho HRMS Training Program / Training Event / Training Result (FEAT-059; A-135 e; UC-42 bước 1).

Custom DocPerm thay thế toàn bộ quyền chuẩn của DocType, nên lần đầu sao chép quyền chuẩn của HRMS
(``setup_custom_perms``) rồi mới thêm vai trò TraceCore — HR Manager / HR User giữ nguyên quyền. Idempotent, chạy ở
``after_migrate``. Không ai được xóa qua vai trò TraceCore (chứng từ Nháp → Ghi sổ → Hủy).
"""

import frappe
from frappe.permissions import add_permission, setup_custom_perms, update_permission_property

MANAGED_PTYPES = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "print")
_EDIT = ("read", "write", "create", "print", "report")
_SUBMIT = (*_EDIT, "submit")

# DocType HRMS → vai trò → quyền (ma trận D6 của plan FEAT-059)
PERMISSIONS: dict[str, dict[str, tuple[str, ...]]] = {
	"Training Program": {"TC R01": _EDIT, "TC R02": _EDIT},
	"Training Event": {"TC R01": _SUBMIT, "TC R02": _SUBMIT},
	"Training Result": {"TC R01": _SUBMIT, "TC R02": _SUBMIT},
}
# DocType được Link tới từ form đào tạo: R01/R02 cần đọc để chọn trên Desk (chỉ thêm, không gỡ quyền có sẵn).
# Không có Department: khoa của dòng nhân viên lấy từ employee.department, R02 không có quyền Department (FR-M1-03).
LINK_TARGETS = ("Employee", "Company")


def ensure_permissions() -> None:
	for doctype, rules in PERMISSIONS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		setup_custom_perms(doctype)
		for role, ptypes in rules.items():
			_ensure_rule(doctype, role, ptypes)
		frappe.clear_cache(doctype=doctype)
	for doctype in LINK_TARGETS:
		if not frappe.db.exists("DocType", doctype):
			continue
		setup_custom_perms(doctype)
		for role in ("TC R01", "TC R02"):
			_ensure_rule(doctype, role, ("read",), only_add=True)
		frappe.clear_cache(doctype=doctype)


def _row(doctype, role):
	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
		fields=["name", *MANAGED_PTYPES],
		limit=1,
	)
	return rows[0] if rows else None


def _ensure_rule(doctype, role, ptypes, only_add=False):
	if not frappe.db.exists("Role", role):
		return
	if _row(doctype, role) is None:
		add_permission(doctype, role, 0)
	for ptype in MANAGED_PTYPES:
		wanted = 1 if ptype in ptypes else 0
		if only_add and not wanted:
			continue
		if int(_row(doctype, role).get(ptype) or 0) != wanted:
			update_permission_property(doctype, role, 0, ptype, wanted, validate=False)
