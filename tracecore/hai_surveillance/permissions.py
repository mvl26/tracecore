"""Phạm vi khoa của mẫu số ngày và đợt thiết bị (FEAT-062; NFR-SEC-09, ADR-010 mở rộng §8; A-141 g).

R08/R12 chỉ đọc/ghi bản ghi của khoa có User Permission Department (cùng cách `Audit Session`, FR-M12-08.1);
R01, R10, R11 và System Manager thấy mọi khoa. R13 không có DocPerm nên không tới đây.
"""

import frappe
from frappe import _

from tracecore.core.errors import Block, BlockedError

WIDE_ROLES = frozenset({"TC R01", "TC R10", "TC R11", "System Manager"})
DEPT_ROLES = frozenset({"TC R08", "TC R12"})
WRITE_ROLES = ("TC R01", "TC R08", "TC R11", "TC R12", "System Manager")


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


def census_query(user=None):
	return _conditions("Ward Daily Census", user)


def episode_query(user=None):
	return _conditions("Device Episode", user)


# FEAT-063 (A-144 j): ca NKBV theo khoa như mẫu số và đợt thiết bị
def case_query(user=None):
	return _conditions("HAI Case", user)


def has_permission(doc, user=None, permission_type=None):
	departments = allowed_departments(user)
	if departments is None:
		return None
	return doc.department in departments


def not_allowed(department=None):
	return BlockedError(
		Block(
			"HAI_NOT_ALLOWED",
			_("Not your department"),
			_("You can record census and device episodes of your own department only."),
			_("Choose your department, or ask the infection control supervisor."),
			object_type="Department" if department else None,
			object_name=department,
		)
	)


def require_department(department, user=None):
	"""Chặn ghi cho khoa ngoài phạm vi (`HAI_NOT_ALLOWED`)."""
	departments = allowed_departments(user)
	if not department or (departments is not None and department not in departments):
		raise not_allowed(department)
