"""Dữ liệu màn SCR-65 ATTP & truyền thông người bệnh (FEAT-073; UC-56; FR-M17-01..06; A-131).

R01/R11: sự cố chờ quyết định, người chế biến (trạng thái hạn khám), buổi truyền thông, kết quả giám sát bếp ăn theo
đơn vị, mẫu thực phẩm, tài liệu truyền thông. R13 chỉ nhận số liệu tổng hợp (không tên người, không mã sự cố).
Tài liệu truyền thông đọc `IC Procedure Document` qua Link; QR do lớp RPC sinh.
"""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.food_safety import audits, education, events, handlers

SCREEN_SLUG = "attp"
EVENT_FIELDS = [
	"name",
	"event_date",
	"location",
	"department",
	"affected_count",
	"suspected_food",
	"supplier_name",
	"description",
	"nc_status",
	"incident_capa",
	"outbreak_status",
	"outbreak_investigation",
	"threshold_applied",
]


def kpis(day=None):
	day = getdate(day or today())
	rows = handlers.latest(day)
	audit_rows = audits.unit_results(add_days(day, -90), day)
	return {
		"handlers_total": len(rows),
		"handlers_overdue": sum(1 for row in rows if row["state"] == handlers.OVERDUE),
		"handlers_due_soon": sum(1 for row in rows if row["state"] == handlers.DUE_SOON),
		"handlers_unfit": sum(1 for row in rows if row["fit_for_work"] == handlers.UNFIT),
		"events_pending": events.pending_count(),
		"food_audits_failed": sum(1 for row in audit_rows if row["last_result"] == "Fail"),
		"food_samples_failed": sum(1 for row in audits.recent_samples(50) if row.result == "Fail"),
	}


def pending_events():
	return frappe.get_all(
		events.DOCTYPE,
		filters={"docstatus": 1},
		or_filters={"nc_status": events.SUGGESTED, "outbreak_status": events.SUGGESTED},
		fields=EVENT_FIELDS,
		order_by="event_date desc, creation desc",
		limit=10,
	)


def recent_events(limit=20):
	return frappe.get_all(
		events.DOCTYPE,
		filters={"docstatus": 1},
		fields=EVENT_FIELDS,
		order_by="event_date desc, creation desc",
		limit=limit,
	)


def recent_sessions(limit=20):
	rows = frappe.get_all(
		education.DOCTYPE,
		fields=["name", "session_date", "department", "audience", "topic", "title", "attendee_count"],
		order_by="session_date desc, creation desc",
		limit=limit,
	)
	names = dict(
		frappe.get_all(
			"Department",
			filters={"name": ["in", [row.department for row in rows] or [""]]},
			fields=["name", "department_name"],
			as_list=True,
		)
	)
	for row in rows:
		row["department_name"] = names.get(row.department, row.department)
	return rows


def build(day=None, summary_only=False):
	day = getdate(day or today())
	year, quarter = education.quarter_of(day)
	result = {
		"kpis": kpis(day),
		"quarter": education.quarter_summary(year, quarter),
		"threshold": events.threshold(),
		"summary_only": summary_only,
	}
	if summary_only:
		return result
	result.update(
		{
			"pending_events": pending_events(),
			"events": recent_events(),
			"handlers": handlers.latest(day),
			"overdue_by_unit": handlers.overdue_by_unit(day),
			"sessions": recent_sessions(),
			"food_audits": audits.unit_results(add_days(day, -90), day),
			"food_samples": audits.recent_samples(),
		}
	)
	return result


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: người chế biến quá hạn khám + sự cố chờ quyết định (R01/R11)."""
	if not events.can_decide(user):
		return {}
	overdue = sum(1 for row in handlers.latest() if row["state"] == handlers.OVERDUE)
	return {SCREEN_SLUG: overdue + events.pending_count()}
