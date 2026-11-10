"""Phạm vi khoa của lệnh cách ly và phòng cách ly (FEAT-068; NFR-SEC-09, ADR-010 mở rộng; A-146 Q5; UC-52 E4).

R08/R12 chỉ đọc/ghi bản ghi của khoa có User Permission Department (cùng cách M13 `hai_surveillance.permissions`,
không import chéo module); R01, R10, R11, R13 và System Manager không bị giới hạn khoa (R13 chỉ có DocPerm đọc
Isolation Room, không đọc Isolation Order).
"""

import frappe
from frappe import _

from tracecore.core.errors import Block, BlockedError

WIDE_ROLES = frozenset({"TC R01", "TC R10", "TC R11", "TC R13", "System Manager"})
DEPT_ROLES = frozenset({"TC R08", "TC R12"})


def allowed_departments(user=None):
	"""None = mọi khoa; danh sách = chỉ các khoa có User Permission (R08/R12)."""
	user = user or frappe.session.user
	if user == "Administrator":
		return None
	roles = set(frappe.get_roles(user))
	if roles & WIDE_ROLES or not roles & DEPT_ROLES:
		return None
	return frappe.get_all("User Permission", filters={"user": user, "allow": "Department"}, pluck="for_value")


def _conditions(doctype, user=None):
	departments = allowed_departments(user)
	if departments is None:
		return ""
	if not departments:
		return "1=0"
	values = ", ".join(frappe.db.escape(name) for name in departments)
	return f"`tab{doctype}`.`department` in ({values})"


def order_query(user=None):
	return _conditions("Isolation Order", user)


def room_query(user=None):
	return _conditions("Isolation Room", user)


def has_permission(doc, user=None, permission_type=None):
	departments = allowed_departments(user)
	if departments is None:
		return None
	return doc.department in departments


def not_allowed(department=None):
	return BlockedError(
		Block(
			"ISOLATION_NOT_ALLOWED",
			_("Not your department"),
			_("You can record isolation orders of your own department only."),
			_("Choose your department, or ask the infection control supervisor."),
			object_type="Department" if department else None,
			object_name=department,
		)
	)


def require_department(department, user=None):
	"""Chặn ghi cho khoa ngoài phạm vi hoặc thiếu khoa (`ISOLATION_NOT_ALLOWED`)."""
	departments = allowed_departments(user)
	if not department or (departments is not None and department not in departments):
		raise not_allowed(department)
