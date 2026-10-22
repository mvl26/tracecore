"""Quyền R09/R06/R10/R02/R01 cho Item, Batch, Stock Entry và các DocType được Link tới (FEAT-041, A-07 V11).

Ma trận quyền #13 không có trong repo (R-13) nên hiện thực thành ``Custom DocPerm`` idempotent, gọi ở
``after_install`` và ``after_migrate``. Lần đầu Frappe sao chép quyền chuẩn của ERPNext vào ``Custom DocPerm``
(``setup_custom_perms``), vai trò chuẩn (Stock Manager, Item Manager…) giữ nguyên quyền, riêng ``delete`` bị gỡ ở
Item, Batch, Stock Entry: không ai xóa (chứng từ chỉ Nháp → Ghi sổ → Hủy).
"""

import frappe
from frappe.permissions import add_permission, setup_custom_perms, update_permission_property

# Các quyền do ma trận quản lý; quyền khác (share, export, import…) không đụng tới.
MANAGED_PTYPES = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "print")

_READ = ("read", "print")
_EDIT = ("read", "write", "create", "print")

# doctype -> role -> các quyền được cấp (V11)
PERMISSION_MATRIX: dict[str, dict[str, tuple[str, ...]]] = {
	"Item": {
		"TC R09": _EDIT,
		"TC R10": _EDIT,
		"TC R02": _EDIT,
		"System Manager": (*_EDIT, "report"),
		"TC R01": (*_READ, "report"),
		"TC R03": _READ,
		"TC R04": _READ,
		"TC R05": _READ,
		"TC R06": _READ,
		"TC R07": _READ,
		"TC R08": _READ,
	},
	"Batch": {
		"TC R09": _EDIT,
		"TC R06": _EDIT,
		"System Manager": (*_EDIT, "report"),
		"TC R02": (*_READ, "report"),
		"TC R01": (*_READ, "report"),
	},
	"Stock Entry": {
		"TC R09": (*_EDIT, "submit", "cancel", "amend", "report"),
		"TC R06": (*_EDIT, "submit", "report"),
		"System Manager": (*_EDIT, "submit", "cancel", "amend", "report"),
		"TC R02": (*_READ, "cancel", "report"),
		"TC R01": (*_READ, "report"),
	},
}

# DocType được Link tới từ form Item / phiếu nhập: các vai trò dưới đây đọc được để chọn trên Desk.
LINK_TARGETS = ("Supplier", "Warehouse", "Item Group", "UOM", "Company", "Stock Entry Type")
LINK_TARGET_ROLES = ("TC R09", "TC R06", "TC R10", "TC R02")
# Cấp quyền đọc cho vai trò chuẩn ngoài ma trận cũng đủ: chỉ thêm, không bớt quyền nào của ERPNext.
NO_DELETE_DOCTYPES = tuple(PERMISSION_MATRIX)


def ensure_permissions() -> None:
	"""Áp ma trận quyền V11 vào ``Custom DocPerm`` (idempotent; chạy lại không đổi gì khi đã đúng)."""
	for doctype, rules in PERMISSION_MATRIX.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		setup_custom_perms(doctype)
		for role, ptypes in rules.items():
			_ensure_rule(doctype, role, ptypes)
		_remove_delete(doctype)
		frappe.clear_cache(doctype=doctype)
	for doctype in LINK_TARGETS:
		if not frappe.db.exists("DocType", doctype):
			continue
		setup_custom_perms(doctype)
		for role in LINK_TARGET_ROLES:
			_ensure_rule(doctype, role, ("read",), only_add=True)
		frappe.clear_cache(doctype=doctype)


def _row(doctype: str, role: str) -> dict | None:
	rows = frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0},
		fields=["name", *MANAGED_PTYPES],
		limit=1,
	)
	return rows[0] if rows else None


def _ensure_rule(doctype: str, role: str, ptypes: tuple[str, ...], only_add: bool = False) -> None:
	"""Đảm bảo ``role`` có đúng các quyền ``ptypes`` ở permlevel 0.

	``only_add``: chỉ bật thêm quyền còn thiếu, không tắt quyền hiện có (DocType ngoài ma trận như Supplier).
	"""
	if not frappe.db.exists("Role", role):
		return
	if _row(doctype, role) is None:
		add_permission(doctype, role, 0)
	for ptype in MANAGED_PTYPES:
		wanted = 1 if ptype in ptypes else 0
		row = _row(doctype, role)
		if only_add and not wanted:
			continue
		if int(row.get(ptype) or 0) != wanted:
			update_permission_property(doctype, role, 0, ptype, wanted, validate=False)


def _remove_delete(doctype: str) -> None:
	"""Gỡ quyền xóa của mọi vai trò (kể cả vai trò chuẩn của ERPNext) trên Item, Batch, Stock Entry."""
	if doctype not in NO_DELETE_DOCTYPES:
		return
	for row in frappe.get_all(
		"Custom DocPerm",
		filters={"parent": doctype, "delete": 1},
		fields=["name", "role", "permlevel", "if_owner"],
	):
		update_permission_property(
			doctype, row.role, row.permlevel, "delete", 0, validate=False, if_owner=row.if_owner
		)
