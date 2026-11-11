"""Điều tra cắt ngang — tỷ lệ hiện mắc NKBV theo ngày (FEAT-072; FR-M13-14, FR-M13-14.1; UC-50 bước 5, 6, E2; A-149 Q1).

Phiếu là `Audit Session` của mẫu có mục ``PREV-HAI`` (engine M12). Module này chỉ đọc phiếu, mục và `Device Episode`
qua ``frappe.get_all`` theo tên DocType/Link, không import M12 (architecture §5.2):

- tỷ lệ hiện mắc theo khoa và toàn viện = phiếu ``PREV-HAI`` = Có / phiếu đã ghi sổ của ngày điều tra; % dùng kháng sinh
  từ ``PREV-ABX``. Số khảo sát 0 → không tính (``None``), không ghi 0 (BRU-RPT-001);
- người bệnh gợi ý = người bệnh có đợt thiết bị đang đặt vào ngày điều tra tại khoa, chưa có phiếu ngày đó (theo hash);
- hàm chỉ số ``hai_prevalence`` theo tháng cho bảng chỉ số M9.

Kết quả chỉ có mã BN đã che, không hash, không mã đầy đủ (NFR-PRIV-01).
"""

import frappe
from frappe.utils import flt, get_last_day, getdate

SESSION, ANSWER = "Audit Session", "Audit Answer"
TEMPLATE, TEMPLATE_ITEM = "Audit Template", "Audit Template Item"
EPISODE = "Device Episode"
HAI_ITEM, ABX_ITEM = "PREV-HAI", "PREV-ABX"
YES = "Yes"
INDICATOR_KEY = "hai_prevalence"
RECENT_DATES = 12


def template_codes():
	parents = frappe.get_all(
		TEMPLATE_ITEM, filters={"parenttype": TEMPLATE, "item_code": HAI_ITEM}, pluck="parent"
	)
	if not parents:
		return []
	return sorted(set(frappe.get_all(TEMPLATE, filters={"name": ["in", parents]}, pluck="template_code")))


def _sessions(filters):
	codes = template_codes()
	if not codes:
		return []
	rows = frappe.get_all(
		SESSION,
		filters={"docstatus": 1, "template_code": ["in", codes], **filters},
		fields=["name", "department", "department_name", "audit_date", "patient_code_hash"],
		order_by="department asc, name asc",
		limit_page_length=0,
	)
	if not rows:
		return []
	answers = {}
	for row in frappe.get_all(
		ANSWER,
		filters={
			"parenttype": SESSION,
			"parent": ["in", [row.name for row in rows]],
			"item_code": ["in", [HAI_ITEM, ABX_ITEM]],
		},
		fields=["parent", "item_code", "value"],
		limit_page_length=0,
	):
		answers.setdefault(row.parent, {})[row.item_code] = (row.value or "").strip()
	for row in rows:
		values = answers.get(row.name, {})
		row["hai"] = values.get(HAI_ITEM) == YES
		row["antibiotic"] = values.get(ABX_ITEM) == YES
	return rows


def _rate(numerator, denominator):
	return round(flt(numerator) * 100 / denominator, 1) if denominator else None


def _summary(rows):
	surveyed = len(rows)
	hai = sum(1 for row in rows if row.hai)
	antibiotic = sum(1 for row in rows if row.antibiotic)
	return {
		"surveyed": surveyed,
		"hai": hai,
		"antibiotic": antibiotic,
		"rate": _rate(hai, surveyed),
		"antibiotic_rate": _rate(antibiotic, surveyed),
	}


def survey_dates(limit=RECENT_DATES):
	"""Ngày có phiếu cắt ngang đã ghi sổ, mới nhất trước."""
	days = sorted({getdate(row.audit_date) for row in _sessions({})}, reverse=True)
	return days[:limit]


def by_department(day):
	"""Tỷ lệ hiện mắc của ngày ``day`` theo khoa và toàn viện."""
	rows = _sessions({"audit_date": getdate(day)})
	grouped = {}
	for row in rows:
		grouped.setdefault(row.department, []).append(row)
	departments = [
		{"department": name, "department_name": items[0].department_name or name, **_summary(items)}
		for name, items in grouped.items()
	]
	departments.sort(key=lambda row: row["department_name"])
	return {"date": getdate(day), "departments": departments, "hospital": _summary(rows)}


def candidates(day, department):
	"""Người bệnh có đợt thiết bị đang đặt vào ngày ``day`` tại khoa, chưa khảo sát ngày đó; gộp theo người bệnh."""
	day = getdate(day)
	surveyed = {row.patient_code_hash for row in _sessions({"audit_date": day, "department": department})}
	episodes = frappe.get_all(
		EPISODE,
		filters={"department": department, "inserted_on": ["<=", day]},
		fields=[
			"name",
			"device_type",
			"inserted_on",
			"removed_on",
			"patient_code_hash",
			"patient_code_masked",
		],
		order_by="inserted_on asc, name asc",
		limit_page_length=0,
	)
	patients = {}
	for row in episodes:
		if row.removed_on and getdate(row.removed_on) < day:
			continue
		if not row.patient_code_hash or row.patient_code_hash in surveyed:
			continue
		patient = patients.setdefault(
			row.patient_code_hash, {"patient_code_masked": row.patient_code_masked, "episodes": []}
		)
		patient["episodes"].append(
			{"name": row.name, "device_type": row.device_type, "inserted_on": row.inserted_on}
		)
	return list(patients.values())


def hai_prevalence(period, department=None):
	"""Chỉ số ``hai_prevalence``: (phiếu có NKBV, phiếu khảo sát, phiếu khảo sát) của tháng ``period``."""
	start = getdate(f"{period}-01")
	filters = {"audit_date": ["between", [start, get_last_day(start)]]}
	if department:
		filters["department"] = department
	rows = _sessions(filters)
	return sum(1 for row in rows if row.hai), len(rows), len(rows)


def register():
	"""Hook ``tracecore_ic_indicators``."""
	return {INDICATOR_KEY: hai_prevalence}
