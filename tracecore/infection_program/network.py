"""Mạng lưới viên KSNK sau khi lưu (FEAT-057; FR-M11-03.2; A-132 d).

- Khoa bắt buộc mất người cuối cùng của một nhóm (bác sĩ / ĐD-HS-KTV) → cảnh báo R01 qua ``core.notification`` (sự
  kiện ``IC_NETWORK_GAP``), msgprint cho người đang sửa, Audit Log.
- Đồng bộ quyền R12: user của nhân viên có dòng hiệu lực → Role ``TC R12`` + User Permission Department của từng khoa;
  không còn dòng hiệu lực ở khoa → gỡ User Permission khoa đó (chỉ khoa từng là mạng lưới của user, không đụng quyền
  gán tay ở khoa khác); không còn dòng hiệu lực nào → gỡ Role. Mỗi lần đổi ghi Audit Log.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import audit, notification
from tracecore.infection_program import structure

GAP_EVENT = "IC_NETWORK_GAP"
R12_ROLE = "TC R12"
SYNC_REASON = "IC_NETWORK_R12_SYNC"
SKIP_USERS = frozenset({"Administrator", "Guest"})


def _key(doc):
	if not doc or not cint(doc.is_active):
		return None
	return (doc.department, structure.member_group(doc.member_type))


def _is_required(department):
	return bool(frappe.db.get_value("Department", department, "tc_ic_network_required"))


def _warn_gap(doc, before):
	old = _key(before)
	if not old or old == _key(doc):
		return
	department, group = old
	if not _is_required(department):
		return
	remaining = frappe.db.count(
		structure.NETWORK,
		{
			"department": department,
			"is_active": 1,
			"member_type": ["in", list(structure.group_types(group))],
			"name": ["!=", doc.name],
		},
	)
	if remaining:
		return
	label = _("doctor") if group == "doctor" else _("nurse/midwife/technician")
	department_name = frappe.db.get_value("Department", department, "department_name") or department
	message = _("{0} no longer has an active {1} in the infection control network.").format(
		department_name, label
	)
	notification.emit(
		GAP_EVENT,
		doc=doc,
		subject=_("IC network gap: {0}").format(department_name),
		message=message,
		link=f"/app/tc-ksnk/{structure.SCREEN_SLUG}",
	)
	frappe.msgprint(message, title=_("IC network gap"), indicator="orange")
	audit.log(
		"Update",
		structure.NETWORK,
		doc.name,
		old={"department": department, "group": group},
		new={"department": doc.department, "is_active": cint(doc.is_active)},
		reason=f"{GAP_EVENT}: {department} {group}",
	)


def _user_of(employee):
	return frappe.db.get_value("Employee", employee, "user_id") if employee else None


def sync_user(user):
	"""Role R12 + User Permission Department theo các dòng mạng lưới của mọi Employee gắn `user`."""
	if not user or user in SKIP_USERS or not frappe.db.exists("User", user):
		return
	employees = frappe.get_all("Employee", filters={"user_id": user}, pluck="name")
	rows = (
		frappe.get_all(
			structure.NETWORK, filters={"employee": ["in", employees]}, fields=["department", "is_active"]
		)
		if employees
		else []
	)
	active = {row.department for row in rows if cint(row.is_active)}
	known = {row.department for row in rows}
	permissions = {
		row.for_value: row.name
		for row in frappe.get_all(
			"User Permission", filters={"user": user, "allow": "Department"}, fields=["name", "for_value"]
		)
	}
	added = sorted(active - set(permissions))
	removed = sorted((known - active) & set(permissions))
	for department in added:
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Department",
				"for_value": department,
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)
	for department in removed:
		frappe.delete_doc("User Permission", permissions[department], ignore_permissions=True, force=True)

	roles = set(frappe.get_roles(user))
	role_change = None
	if active and R12_ROLE not in roles:
		role_change = "add"
	elif not active and known and R12_ROLE in roles:
		role_change = "remove"
	if role_change:
		user_doc = frappe.get_doc("User", user)
		user_doc.flags.ignore_permissions = True
		if role_change == "add":
			user_doc.add_roles(R12_ROLE)
		else:
			user_doc.remove_roles(R12_ROLE)

	if added or removed or role_change:
		audit.log(
			"Update",
			"User",
			user,
			old={"departments": sorted(set(permissions)), "r12": R12_ROLE in roles},
			new={"departments": sorted((set(permissions) | set(added)) - set(removed)), "r12": bool(active)},
			reason=SYNC_REASON,
		)


def after_change(doc):
	"""``on_update`` của IC Network Member (gồm cả lần tạo)."""
	before = doc.get_doc_before_save()
	_warn_gap(doc, before)
	users = {_user_of(doc.employee)}
	if before and before.employee != doc.employee:
		users.add(_user_of(before.employee))
	for user in users - {None}:
		sync_user(user)
