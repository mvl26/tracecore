"""Audit Trail (FEAT-004, A-37 c, NFR-SEC-03): Audit Log theo đối tượng, người, trạm, thao tác và khoảng ngày.

Đọc qua ``frappe.get_list`` nên theo đúng quyền đọc Audit Log của người xem; mới nhất trước, tối đa ``MAX_ROWS`` dòng.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate

MAX_ROWS = 2000
EQUAL_FILTERS = ("ref_doctype", "ref_name", "user", "station", "action")

# (fieldname, nhãn gốc, kiểu, rộng, options); nhãn dịch với ngữ cảnh "Audit Trail" để không đè bản dịch app khác
COLUMNS = (
	("timestamp", "Time", "Datetime", 150, None),
	("user", "User", "Link", 170, "User"),
	("station", "Station", "Link", 90, "Zone Station"),
	("action", "Action", "Data", 90, None),
	("ref_doctype", "Document Type", "Link", 130, "DocType"),
	("ref_name", "Document", "Dynamic Link", 170, "ref_doctype"),
	("reason", "Reason", "Data", 220, None),
	("old_value", "Old Value", "Data", 220, None),
	("new_value", "New Value", "Data", 220, None),
	("device", "Device", "Data", 100, None),
	("name", "Audit Log", "Link", 120, "Audit Log"),
)


def _columns():
	return [
		{
			"fieldname": fieldname,
			"label": _(label, context="Audit Trail"),
			"fieldtype": fieldtype,
			"width": width,
			"options": options,
		}
		for fieldname, label, fieldtype, width, options in COLUMNS
	]


def _filters(filters):
	where = [[key, "=", filters[key]] for key in EQUAL_FILTERS if filters.get(key)]
	if filters.get("from_date"):
		where.append(["timestamp", ">=", getdate(filters.from_date)])
	if filters.get("to_date"):
		where.append(["timestamp", "<", add_days(getdate(filters.to_date), 1)])
	return where


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = frappe.get_list(
		"Audit Log",
		filters=_filters(filters),
		fields=[column[0] for column in COLUMNS],
		order_by="timestamp desc, name desc",
		limit_page_length=MAX_ROWS,
	)
	return _columns(), rows
