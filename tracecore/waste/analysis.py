"""Phân tích chất thải (FEAT-050, UC-37, FR-M10-06.2, FR-M10-07, .1-.3, FR-M10-08, .1, .3, .4, A-63).

`report_rows` là nguồn của báo cáo kỳ; `check_anomaly` so kg của khoa trong ngày với trung bình tối đa 30 ngày trước, gọi khi
ghi sổ phiếu thu gom; `run_daily` cảnh báo khoa phân loại sai lặp lại. Ngưỡng ở `TraceCore Settings`, trống thì lấy mặc
định. Túi tuân thủ hạn lưu là túi không bị đánh dấu quá hạn (`overdue_at`).
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, flt, get_datetime, getdate, now_datetime, today

from tracecore.core import notification
from tracecore.waste.storage import COLLECTED, HELD, SETTINGS, STORED, thresholds

CONTAINER = "Waste Container"
COLLECTION = "Waste Collection"
DEFAULT_MISCLASS_COUNT = 3
DEFAULT_MISCLASS_DAYS = 30
DEFAULT_ANOMALY_PERCENT = 30
HISTORY_DAYS = 30
ANOMALY_EVENT = "WASTE_ANOMALY"
REPEAT_EVENT = "WASTE_MISCLASS_REPEAT"
MISCLASS_TYPE = "Waste Misclassification"
REPORT_LINK = "/app/query-report/Waste Report"
WASTE_INCIDENT_TYPES = (
	MISCLASS_TYPE,
	"Waste Storage Overdue",
	"Waste Weight Variance",
	"Waste Spill",
	"Sharps Exposure",
)


def limits():
	get = frappe.db.get_single_value
	return {
		"misclass_count": cint(get(SETTINGS, "waste_misclass_count")) or DEFAULT_MISCLASS_COUNT,
		"misclass_days": cint(get(SETTINGS, "waste_misclass_days")) or DEFAULT_MISCLASS_DAYS,
		"anomaly_percent": flt(get(SETTINGS, "waste_anomaly_percent")) or DEFAULT_ANOMALY_PERCENT,
	}


# --- phát sinh bất thường (FR-M10-08.1, .4) ---------------------------------------------------------------------------


def _daily_kg(department, waste_type, start, end):
	"""{ngày: kg} đã ghi sổ của khoa - loại trong [start, end]; túi bị giữ không tính."""
	rows = frappe.db.sql(
		"""select date(c.collected_at) as day, sum(l.weight_kg) as kg
		from `tabWaste Collection Line` l
		inner join `tabWaste Collection` c on c.name = l.parent and l.parenttype = 'Waste Collection'
		where c.docstatus = 1 and c.department = %s and l.waste_type = %s and l.misclassified = 0
			and date(c.collected_at) between %s and %s
		group by date(c.collected_at)""",
		(department, waste_type, start, end),
		as_dict=True,
	)
	return {getdate(row.day): flt(row.kg) for row in rows}


def anomaly(department, waste_type, day=None):
	"""So kg ngày `day` với trung bình các ngày có dữ liệu trong 30 ngày trước; không có lịch sử → None."""
	day = getdate(day or today())
	today_kg = _daily_kg(department, waste_type, day, day).get(day, 0)
	history = _daily_kg(department, waste_type, add_days(day, -HISTORY_DAYS), add_days(day, -1))
	if not history:
		return None
	average = sum(history.values()) / len(history)
	percent = (today_kg - average) * 100 / average if average else 0
	return {
		"kg": today_kg,
		"average": round(average, 3),
		"percent": round(percent, 1),
		"insufficient": len(history) < HISTORY_DAYS,
		"over": abs(percent) > limits()["anomaly_percent"],
	}


def check_anomaly(doc):
	"""Ghi sổ phiếu thu gom: lệch quá ngưỡng thì báo R02, mỗi khoa - loại - ngày một lần; đánh dấu Chưa đủ dữ liệu."""
	day = getdate(doc.collected_at)
	for waste_type in {row.waste_type for row in doc.lines}:
		result = anomaly(doc.department, waste_type, day)
		if not result or not result["over"]:
			continue
		subject = _("Unusual waste from {0}: {1}").format(doc.department, waste_type)
		marker = _("{0} on {1}: {2} kg against an average of {3} kg ({4} %).").format(
			waste_type, day.strftime("%d/%m/%Y"), result["kg"], result["average"], result["percent"]
		)
		if result["insufficient"]:
			marker = _("{0} Not enough data yet.").format(marker)
		if frappe.db.exists(
			"Notification Delivery",
			{
				"event_code": ANOMALY_EVENT,
				"ref_name": doc.department,
				"subject": subject,
				"creation": [">=", f"{day} 00:00:00"],
			},
		):
			continue
		notification.emit(
			ANOMALY_EVENT,
			frappe._dict(doctype="Department", name=doc.department, department=doc.department),
			subject=subject,
			message=marker,
			link=REPORT_LINK,
		)


# --- phân loại sai lặp lại (FR-M10-06.2) ------------------------------------------------------------------------------


def repeat_departments(day=None):
	settings = limits()
	since = add_days(day or today(), -settings["misclass_days"])
	rows = frappe.get_all(
		"Incident CAPA",
		filters={
			"incident_type": MISCLASS_TYPE,
			"occurred_at": [">=", since],
			"department": ["is", "set"],
			"status": ["!=", "Cancelled"],
		},
		fields=["department", "count(name) as times"],
		group_by="department",
	)
	return {row.department: row.times for row in rows if row.times >= settings["misclass_count"]}


def run_daily():
	settings = limits()
	since = add_to_date(now_datetime(), days=-settings["misclass_days"])
	for department, times in repeat_departments().items():
		if frappe.db.exists(
			"Notification Delivery",
			{"event_code": REPEAT_EVENT, "ref_name": department, "creation": [">=", since]},
		):
			continue
		notification.emit(
			REPEAT_EVENT,
			frappe._dict(doctype="Department", name=department, department=department),
			subject=_("{0} has repeated waste misclassification").format(department),
			message=_("{0} misclassifications in {1} days.").format(times, settings["misclass_days"]),
			link=REPORT_LINK,
		)


# --- báo cáo kỳ (FR-M10-07, FR-M10-08.3) ------------------------------------------------------------------------------


def _quota(department, waste_type, on_date):
	rows = frappe.get_all(
		"Waste Quota",
		filters={
			"department": department,
			"waste_type": waste_type,
			"is_active": 1,
			"effective_from": ["<=", getdate(on_date)],
		},
		fields=["bags_per_day", "kg_per_bed_day"],
		order_by="effective_from desc",
		limit=1,
	)
	return rows[0] if rows else None


def _handover_rates(names):
	if not names:
		return {}
	rows = frappe.get_all(
		"Waste Handover Line",
		filters={"parent": ["in", list(names)], "parenttype": "Waste Handover"},
		fields=["parent", "waste_type", "amount", "collected_kg"],
	)
	return {
		(row.parent, row.waste_type): flt(row.amount) / flt(row.collected_kg) if flt(row.collected_kg) else 0
		for row in rows
	}


def is_provisional(to_date):
	"""FR-M10-07.2: kỳ chưa khóa → bản Tạm; dùng chung ngày khóa báo cáo của M9 (Single trống trả năm 1)."""
	value = frappe.db.get_single_value(SETTINGS, "report_locked_until")
	locked = getdate(value) if value and getdate(value).year > 1 else None
	return not locked or getdate(to_date) > locked


def report_rows(from_date, to_date, department=None, waste_type=None):
	"""Mỗi dòng là khoa - loại trong kỳ: số túi, kg thu gom, kg đã bàn giao, chênh lệch, chi phí, chi phí/kg, tuân thủ, định mức."""
	filters = {
		"collected_at": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]],
		"status": ["!=", "Cancelled"],
	}
	if department:
		filters["department"] = department
	if waste_type:
		filters["waste_type"] = waste_type
	bags = frappe.get_all(
		CONTAINER,
		filters=filters,
		fields=["waste_type", "department", "weight_kg", "status", "handover", "overdue_at"],
	)
	handed_docs = frappe.get_all(
		"Waste Handover",
		filters={"name": ["in", [bag.handover for bag in bags if bag.handover] or [""]], "docstatus": 1},
		pluck="name",
	)
	rates = _handover_rates(handed_docs)
	handed_kg = {}
	if handed_docs:
		for row in frappe.get_all(
			"Waste Handover Line",
			filters={"parent": ["in", handed_docs], "parenttype": "Waste Handover"},
			fields=["parent", "waste_type", "collected_kg", "handover_kg"],
		):
			handed_kg[(row.parent, row.waste_type)] = (
				flt(row.handover_kg) / flt(row.collected_kg) if flt(row.collected_kg) else 1
			)
	groups = {}
	for bag in bags:
		row = groups.setdefault(
			(bag.department, bag.waste_type),
			{
				"department": bag.department,
				"waste_type": bag.waste_type,
				"bags": 0,
				"collected_kg": 0,
				"handed_collected_kg": 0,
				"handover_kg": 0,
				"cost": 0,
				"on_time": 0,
			},
		)
		row["bags"] += 1
		row["collected_kg"] += flt(bag.weight_kg)
		row["on_time"] += 0 if bag.overdue_at else 1
		if bag.handover in handed_docs:
			key = (bag.handover, bag.waste_type)
			row["handed_collected_kg"] += flt(bag.weight_kg)
			row["handover_kg"] += flt(bag.weight_kg) * handed_kg.get(key, 1)
			row["cost"] += flt(bag.weight_kg) * rates.get(key, 0)
	repeat = repeat_departments(to_date)
	rows = []
	for (dept, waste), row in sorted(groups.items(), key=lambda item: (item[0][0] or "", item[0][1])):
		quota = _quota(dept, waste, to_date)
		rows.append(
			{
				**row,
				"collected_kg": round(row["collected_kg"], 3),
				"handover_kg": round(row["handover_kg"], 3),
				"difference_kg": round(row["handover_kg"] - row["handed_collected_kg"], 3),
				"cost": round(row["cost"]),
				"cost_per_kg": round(row["cost"] / row["handover_kg"]) if row["handover_kg"] else 0,
				"compliance_percent": round(row["on_time"] * 100 / row["bags"], 1),
				"bags_per_day": quota.bags_per_day if quota else None,
				"kg_per_bed_day": quota.kg_per_bed_day if quota else None,
				"quota_missing": not quota,
				"repeat_misclassification": dept in repeat,
			}
		)
	return rows


def incidents(from_date, to_date, department=None):
	filters = {
		"incident_type": ["in", WASTE_INCIDENT_TYPES],
		"occurred_at": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]],
	}
	if department:
		filters["department"] = department
	return frappe.get_all(
		"Incident CAPA",
		filters=filters,
		fields=["name", "incident_type", "severity", "status", "department", "waste_type", "occurred_at"],
		order_by="occurred_at desc",
	)


# --- khối dashboard (FR-M10-07.1) -------------------------------------------------------------------------------------


def dashboard(now=None):
	now = get_datetime(now) if now else now_datetime()
	day = getdate(now)
	percent = thresholds()["warn_percent"]
	kg = frappe.db.sql(
		"""select l.waste_type, sum(l.weight_kg) as kg
		from `tabWaste Collection Line` l
		inner join `tabWaste Collection` c on c.name = l.parent and l.parenttype = 'Waste Collection'
		where c.docstatus = 1 and l.misclassified = 0 and date(c.collected_at) = %s
		group by l.waste_type order by l.waste_type""",
		(day,),
		as_dict=True,
	)
	due_soon = overdue = 0
	for row in frappe.get_all(
		CONTAINER,
		filters={"status": ["in", [COLLECTED, STORED, HELD]], "storage_due": ["is", "set"]},
		fields=["collected_at", "storage_due"],
	):
		due = get_datetime(row.storage_due)
		if now >= due:
			overdue += 1
		else:
			start = get_datetime(row.collected_at)
			if now >= start + (due - start) * percent / 100:
				due_soon += 1
	pending = frappe.db.count("Waste Handover", {"docstatus": 1, "document_pending": 1})
	since = f"{day} 00:00:00"
	unusual = frappe.get_all(
		"Notification Delivery",
		filters={"event_code": ANOMALY_EVENT, "creation": [">=", since]},
		distinct=True,
		pluck="ref_name",
	)
	return {
		"kg_today": [{"waste_type": row.waste_type, "kg": flt(row.kg)} for row in kg],
		"due_soon": due_soon,
		"overdue": overdue,
		"pending_documents": pending,
		"unusual_departments": sorted(set(unusual)),
	}


def department_summary(department, from_date, to_date):
	"""FR-M10-07.3: kg theo loại của một khoa và NC phân loại sai của khoa."""
	return {
		"rows": [
			{"waste_type": row["waste_type"], "bags": row["bags"], "collected_kg": row["collected_kg"]}
			for row in report_rows(from_date, to_date, department)
		],
		"misclassifications": [
			row for row in incidents(from_date, to_date, department) if row.incident_type == MISCLASS_TYPE
		],
	}
