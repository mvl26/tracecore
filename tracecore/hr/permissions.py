"""Quyền R01/R02/R10 cho HRMS Shift Assignment và Shift Type (FEAT-037, A-45): Custom DocPerm idempotent.

Gọi ở ``after_install`` và ``after_migrate``. Quyền chuẩn của HRMS (HR Manager, System Manager…) giữ nguyên; chỉ thêm
quyền cho vai trò TraceCore để R02 xếp ca và R01/R10 xem được, theo cùng cách `inventory.permissions`.
"""

import frappe
from frappe.permissions import add_permission, setup_custom_perms, update_permission_property

MANAGED_PTYPES = ("read", "write", "create", "submit", "cancel", "report", "print")
_EDIT = ("read", "write", "create", "print")
_READ = ("read", "print")

PERMISSION_MATRIX: dict[str, dict[str, tuple[str, ...]]] = {
	"Shift Assignment": {
		"TC R02": (*_EDIT, "submit", "cancel", "report"),
		"TC R10": (*_EDIT, "submit", "cancel", "report"),
		"TC R01": (*_READ, "report"),
	},
	"Shift Type": {
		"TC R02": _EDIT,
		"TC R10": _EDIT,
		"TC R01": _READ,
	},
}


def _row(doctype, role):
	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
		fields=["name", *MANAGED_PTYPES],
		limit=1,
	)
	return rows[0] if rows else None


def ensure_permissions() -> None:
	for doctype, rules in PERMISSION_MATRIX.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		setup_custom_perms(doctype)
		for role, ptypes in rules.items():
			if not frappe.db.exists("Role", role):
				continue
			if _row(doctype, role) is None:
				add_permission(doctype, role, 0)
			for ptype in MANAGED_PTYPES:
				wanted = 1 if ptype in ptypes else 0
				if int(_row(doctype, role).get(ptype) or 0) != wanted:
					update_permission_property(doctype, role, 0, ptype, wanted, validate=False)
		frappe.clear_cache(doctype=doctype)
