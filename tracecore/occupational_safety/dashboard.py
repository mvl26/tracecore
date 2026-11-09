"""Dữ liệu màn SCR-64 Phơi nhiễm & tiêm chủng (FEAT-071; FR-M16-03..09; BRU-OCC-003; A-137 j).

R01/R11: KPI, danh sách hồ sơ (mã BN nguồn chỉ dạng che), tiêm chủng, cảnh báo thuốc dự phòng. R13: chỉ KPI tổng hợp,
không bản ghi cá nhân (FR-M16-05.1, NFR-SEC-09).
"""

import frappe
from frappe.utils import cint, date_diff, getdate, nowdate

from tracecore.occupational_safety import config, exposure, immunization, pep_stock

RECORD_FIELDS = (
	"name",
	"employee_name",
	"department",
	"exposure_type",
	"report_channel",
	"occurred_at",
	"minutes_to_report",
	"minutes_to_prophylaxis",
	"report_late",
	"prophylaxis_late",
	"status",
)
DUE_SOON_DAYS = 30


def kpis(day=None):
	day = getdate(day or nowdate())
	year_filters = {
		"status": ["!=", "Cancelled"],
		"occurred_at": ["between", [f"{day.year}-01-01 00:00:00", f"{day.year}-12-31 23:59:59"]],
	}
	rows = frappe.get_all(exposure.DOCTYPE, filters=year_filters, fields=["report_late", "prophylaxis_late"])
	report_hours, prophylaxis_hours = exposure.thresholds()
	return {
		"year": day.year,
		"year_total": len(rows),
		"late": sum(1 for row in rows if row.report_late or row.prophylaxis_late),
		"following": frappe.db.count(exposure.DOCTYPE, {"status": "Following Up"}),
		"new": frappe.db.count(exposure.DOCTYPE, {"status": "New"}),
		"immunization": immunization.coverage(day=day),
		"thresholds": {"report_hours": report_hours, "prophylaxis_hours": prophylaxis_hours},
	}


def records(limit=50):
	rows = frappe.get_all(
		exposure.DOCTYPE, fields=list(RECORD_FIELDS), order_by="occurred_at desc", limit=limit
	)
	order = {"New": 0, "Following Up": 1, "Completed": 2, "Cancelled": 3}
	rows.sort(
		key=lambda row: order.get(row.status, 9)
	)  # sort ổn định: trong cùng trạng thái vẫn mới nhất trước
	for row in rows:
		row.department_name = (
			frappe.db.get_value("Department", row.department, "department_name") if row.department else None
		)
	return rows


def immunizations(day=None, limit=50):
	day = getdate(day or nowdate())
	doses = {
		name: cint(doses)
		for name, doses in frappe.get_all(config.REQUIREMENT, fields=["name", "doses_required"], as_list=True)
	}
	rows = []
	for row in immunization._latest_doses():
		if frappe.db.get_value("Employee", row.employee, "status") != "Active":
			continue
		info = (
			frappe.db.get_value("Employee", row.employee, ["employee_name", "department"], as_dict=True) or {}
		)
		required = doses.get(row.vaccine) or 0
		if row.next_due:
			days_left = date_diff(row.next_due, day)
			state = (
				"Overdue" if days_left < 0 else ("Due Soon" if days_left <= DUE_SOON_DAYS else "Scheduled")
			)
		else:
			days_left = None
			state = "Complete" if cint(row.dose_no) >= required else "Scheduled"
		rows.append(
			{
				"name": row.name,
				"employee_name": info.get("employee_name"),
				"department": info.get("department"),
				"vaccine": row.vaccine,
				"dose_no": cint(row.dose_no),
				"doses_required": required,
				"next_due": str(row.next_due) if row.next_due else None,
				"days_left": days_left,
				"state": state,
			}
		)
	order = {"Overdue": 0, "Due Soon": 1, "Scheduled": 2, "Complete": 3}
	rows.sort(key=lambda r: (order[r["state"]], r["next_due"] or "9999"))
	return rows[:limit]


def detail(name):
	doc = frappe.get_doc(exposure.DOCTYPE, name)
	return {
		"name": doc.name,
		"employee_name": doc.employee_name,
		"department": doc.department,
		"occupation": doc.occupation,
		"exposure_type": doc.exposure_type,
		"occurred_at": str(doc.occurred_at),
		"reported_at": str(doc.reported_at),
		"report_channel": doc.report_channel,
		"activity": doc.activity,
		"device": doc.device,
		"source_known": doc.source_known,
		"source_patient_code_masked": doc.source_patient_code_masked,
		"first_aid_done": cint(doc.first_aid_done),
		"first_aid_at": str(doc.first_aid_at) if doc.first_aid_at else None,
		"prophylaxis": doc.prophylaxis,
		"prophylaxis_started_at": str(doc.prophylaxis_started_at) if doc.prophylaxis_started_at else None,
		"minutes_to_report": doc.minutes_to_report,
		"minutes_to_prophylaxis": doc.minutes_to_prophylaxis,
		"report_late": cint(doc.report_late),
		"prophylaxis_late": cint(doc.prophylaxis_late),
		"status": doc.status,
		"followup_template": doc.followup_template,
		"template_version": doc.template_version,
		"incident_capa": doc.incident_capa,
		"followups": [
			{
				"name": row.name,
				"step": row.step,
				"due_date": str(row.due_date) if row.due_date else None,
				"done_on": str(row.done_on) if row.done_on else None,
			}
			for row in doc.followups
		],
		"has_template": bool(config.active_template(doc.exposure_type)),
	}


def build(user=None, day=None):
	"""Toàn bộ dữ liệu màn; người không phải R01/R11 chỉ nhận KPI."""
	result = {"kpis": kpis(day), "is_manager": exposure.is_manager(user)}
	if result["is_manager"]:
		result.update(
			{"records": records(), "immunizations": immunizations(day), "pep_alerts": pep_stock.status(day)}
		)
	return result
