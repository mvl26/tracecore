"""Food Safety and Communication by Quarter — "ATTP & truyền thông theo quý" (FEAT-073; FR-M17-05.1, FR-M17-01..04).

Phần "Truyền thông": số buổi và số người theo đối tượng - chủ đề trong quý. Phần "An toàn thực phẩm": số phiếu giám sát
bếp ăn (Đạt/tổng), sự cố nghi ngộ độc và số người bị ảnh hưởng, mẫu thực phẩm Không đạt, người chế biến quá hạn khám
cuối quý. Chỉ số liệu tổng hợp, không tên người.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from tracecore.food_safety import audits, education, events, handlers

COMMUNICATION, FOOD_SAFETY = "Communication", "Food Safety"


def _columns():
	return [
		{"fieldname": "section", "label": _("Section"), "fieldtype": "Data", "width": 150},
		{"fieldname": "item", "label": _("Audience / Item"), "fieldtype": "Data", "width": 260},
		{"fieldname": "topic", "label": _("Topic / Detail"), "fieldtype": "Data", "width": 280},
		{"fieldname": "count", "label": _("Count"), "fieldtype": "Int", "width": 110},
		{"fieldname": "attendees", "label": _("People"), "fieldtype": "Int", "width": 110},
	]


def _period(filters):
	year, quarter = education.quarter_of(today())
	year = cint(filters.get("year")) or year
	quarter = cint(str(filters.get("quarter") or f"Q{quarter}").lstrip("Q"))
	return year, quarter


def _food_rows(start, end):
	units = audits.unit_results(start, end)
	total = sum(unit["total"] for unit in units)
	passed = sum(unit["passed"] for unit in units)
	found = frappe.get_all(
		events.DOCTYPE,
		filters={"docstatus": 1, "event_date": ["between", [start, end]]},
		fields=["affected_count"],
	)
	failed_samples = frappe.db.count(
		"Environmental Sample",
		{
			"docstatus": 1,
			"sample_type": audits.FOOD_SAMPLE_TYPE,
			"result": "Fail",
			"sampled_on": ["between", [start, end]],
		},
	)
	overdue = sum(
		1 for row in handlers.latest(min(end, getdate(today()))) if row["state"] == handlers.OVERDUE
	)
	return [
		(_("Kitchen and catering audits"), _("{0} passed").format(passed), total, None),
		(_("Suspected food poisoning events"), "", len(found), sum(cint(r.affected_count) for r in found)),
		(_("Failed food samples"), "", failed_samples, None),
		(_("Food handlers overdue for a health check"), "", overdue, None),
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	year, quarter = _period(filters)
	start, end = education.quarter_bounds(year, quarter)
	data = [
		{
			"section": COMMUNICATION,
			"item": _(row["audience"]),
			"topic": _(row["topic"]),
			"count": row["sessions"],
			"attendees": row["attendees"],
		}
		for row in education.quarter_summary(year, quarter)["rows"]
	]
	data += [
		{"section": FOOD_SAFETY, "item": item, "topic": topic, "count": count, "attendees": people}
		for item, topic, count, people in _food_rows(start, end)
	]
	return _columns(), data
