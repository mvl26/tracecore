"""Quyền R10 cho ERPNext Issue và Frappe Help Article / Help Category (FEAT-013, A-56): Custom DocPerm idempotent.

Gọi ở ``after_install`` và ``after_migrate``. Quyền chuẩn (Support Team, Knowledge Base Editor…) giữ nguyên; R10 xử lý
phản hồi/báo lỗi từ trạm và soạn hướng dẫn theo trạm, theo cùng cách `hr.permissions`.
"""

import frappe
from frappe.permissions import add_permission, setup_custom_perms, update_permission_property

MANAGED_PTYPES = ("read", "write", "create", "report", "print")
_EDIT = ("read", "write", "create", "print")

PERMISSION_MATRIX: dict[str, dict[str, tuple[str, ...]]] = {
	# phản hồi tạo từ trạm bằng dịch vụ (ignore_permissions); R10 đọc, trả lời, đóng, không tạo tay
	"Issue": {"TC R10": ("read", "write", "report", "print")},
	"Help Article": {"TC R10": (*_EDIT, "report")},
	"Help Category": {"TC R10": _EDIT},
	# NAV-04: R10 chỉ đọc để mở hai màn này từ menu; không tạo, sửa, xóa
	"Department": {"TC R10": ("read", "report", "print")},
	"Print Job": {"TC R10": ("read", "report", "print")},
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
