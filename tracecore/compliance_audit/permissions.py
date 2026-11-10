"""Quyền TraceCore trên ERPNext Supplier và Warehouse cho đơn vị thuê ngoài, kho khoa (FEAT-066; A-142 Q4).

Custom DocPerm thay thế toàn bộ quyền chuẩn của DocType, nên lần đầu sao chép quyền chuẩn của ERPNext
(``setup_custom_perms``) rồi chỉ **thêm** quyền còn thiếu cho vai trò TraceCore — không gỡ quyền FEAT-041 đã cấp, không
cấp delete. Idempotent, chạy ở ``after_migrate``.
"""

import frappe
from frappe.permissions import add_permission, setup_custom_perms, update_permission_property

_READ = ("read", "report", "print")
_EDIT = (*_READ, "write", "create")

# DocType ERPNext → vai trò → quyền cần có (chỉ thêm)
PERMISSIONS: dict[str, dict[str, tuple[str, ...]]] = {
	"Supplier": {
		"TC R09": _EDIT,
		"TC R01": _READ,
		"TC R02": _READ,
		"TC R11": _READ,
		"TC R13": _READ,
	},
	"Warehouse": {"TC R09": _EDIT, "TC R10": _EDIT, "TC R01": _READ},
}


def _row(doctype, role):
	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
		fields=["name", *{*_EDIT}],
		limit=1,
	)
	return rows[0] if rows else None


def _grant(doctype, role, ptypes):
	if not frappe.db.exists("Role", role):
		return
	if _row(doctype, role) is None:
		add_permission(doctype, role, 0)
	row = _row(doctype, role)
	for ptype in ptypes:
		if not int(row.get(ptype) or 0):
			update_permission_property(doctype, role, 0, ptype, 1, validate=False)


def ensure_permissions() -> None:
	for doctype, rules in PERMISSIONS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		setup_custom_perms(doctype)
		for role, ptypes in rules.items():
			_grant(doctype, role, ptypes)
		frappe.clear_cache(doctype=doctype)
