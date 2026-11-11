"""Loại xuất báo cáo NKVM và NK hồi sức cho `core.exporter` (FEAT-064; FR-M13-12, 12.1; BRU-RPT-002; QĐ 38; A-147 Q4,
j).

- ``ssi_cases``: từng ca phẫu thuật giám sát trong khoảng kỳ (tháng ngày mổ) — mã người bệnh che.
- ``ssi_summary``: tổng hợp theo nhóm phẫu thuật và NNIS, kháng sinh dự phòng.
- ``icu_hai_cases``: ca NKBV Xác định đã ghi sổ ở khoa hồi sức (`Department.tc_icu`) — mã che, tác nhân, nhãn đa kháng.
- ``icu_hai_summary``: theo tháng và khoa hồi sức — ngày nằm viện, ngày thiết bị, số ca, tỷ suất ‰.

Bộ lọc ``period_from`` / ``period_to`` (YYYY-MM, mặc định tháng hiện tại), ``department`` (tùy chọn).
"""

import frappe
from frappe.utils import today

from tracecore.core.exporter import ExportField, ExportKind
from tracecore.hai_surveillance import indicators, periods, ssi, ssi_indicators

SSI_CASES, SSI_SUMMARY = "ssi_cases", "ssi_summary"
ICU_CASES, ICU_SUMMARY = "icu_hai_cases", "icu_hai_summary"
ROLES = ("TC R01", "TC R11", "System Manager")


def _months(filters):
	start = filters.get("period_from") or periods.month_of(today())
	return ssi_indicators.months_between(start, filters.get("period_to") or start)


def _icu_wards(department=None):
	filters = {"tc_icu": 1, "is_group": 0}
	if department:
		filters["name"] = department
	return frappe.get_all("Department", filters=filters, pluck="name")


def ssi_case_rows(filters):
	conditions = {"reporting_period": ["in", _months(filters)]}
	if filters.get("department"):
		conditions["department"] = filters["department"]
	rows = frappe.get_all(
		ssi.DOCTYPE,
		filters=conditions,
		fields=list(ssi.LIST_FIELDS),
		order_by="surgery_date asc, name asc",
		limit_page_length=0,
	)
	sites = dict(
		frappe.get_all(
			"HAI Case",
			filters={"name": ["in", [row.hai_case for row in rows if row.hai_case] or [""]]},
			fields=["name", "infection_site"],
			as_list=True,
		)
	)
	for row in rows:
		row["infection_site"] = sites.get(row.hai_case)
	return rows


def ssi_summary_rows(filters):
	months = _months(filters)
	return ssi_indicators.summary(months[0], months[-1])


def icu_case_rows(filters):
	wards = _icu_wards(filters.get("department"))
	rows = frappe.get_all(
		"HAI Case",
		filters={
			"docstatus": 1,
			"status": "Confirmed",
			"department": ["in", wards or [""]],
			"reporting_period": ["in", _months(filters)],
		},
		fields=[
			"name",
			"patient_code_masked",
			"birth_year",
			"sex",
			"department",
			"department_name",
			"admission_at",
			"onset_date",
			"def_code",
			"infection_site",
			"device_type",
			"device_episode",
			"mdro_flags",
			"outcome",
			"reporting_period",
		],
		order_by="onset_date asc, name asc",
		limit_page_length=0,
	)
	organisms = {}
	for line in frappe.get_all(
		"HAI Case Isolate",
		filters={"parenttype": "HAI Case", "parent": ["in", [row.name for row in rows] or [""]]},
		fields=["parent", "organism"],
		order_by="idx asc",
	):
		if line.organism:
			organisms.setdefault(line.parent, []).append(line.organism)
	for row in rows:
		row["organisms"] = ", ".join(dict.fromkeys(organisms.get(row.name, [])))
	return rows


def icu_summary_rows(filters):
	wards = set(_icu_wards(filters.get("department")))
	out = []
	for month in _months(filters):
		for row in indicators.by_department(month):
			if row["department"] in wards:
				out.append({"month": month, **row})
	return out


def _fields(*items):
	return [ExportField(*item) for item in items]


def export_kinds():
	"""Hook ``tracecore_export_kinds``."""
	return [
		ExportKind(
			key=SSI_CASES,
			label="Surgical site infection surveillance (cases)",
			fields=_fields(
				("name", "Surveillance ID"),
				("patient_code_masked", "Patient Code"),
				("birth_year", "Birth Year", "int"),
				("sex", "Sex", "select"),
				("department_name", "Department"),
				("procedure_group", "Procedure Group Code"),
				("group_name", "Procedure Group"),
				("surgery_date", "Surgery Date", "date"),
				("asa_score", "ASA Score", "int"),
				("wound_class", "Wound Class", "select", ssi.DOCTYPE),
				("duration_min", "Duration (minutes)", "int"),
				("has_implant", "Implant", "check"),
				("nnis_index", "NNIS Index", "int"),
				("prophylaxis_given", "Prophylaxis Given", "check"),
				("prophylaxis_agent", "Antibiotic"),
				("prophylaxis_minutes_before_incision", "Minutes before Incision", "int"),
				("prophylaxis_timing", "Prophylaxis Timing", "select", ssi.DOCTYPE),
				("discharge_date", "Discharge Date", "date"),
				("window_end", "Window End", "date"),
				("outcome", "Outcome", "select", ssi.DOCTYPE),
				("hai_case", "HAI Case"),
				("infection_site", "Infection Site", "select"),
				("reporting_period", "Reporting Period"),
			),
			rows=ssi_case_rows,
			roles=ROLES,
		),
		ExportKind(
			key=SSI_SUMMARY,
			label="Surgical site infection by procedure group",
			fields=_fields(
				("procedure_group", "Procedure Group Code"),
				("group_name", "Procedure Group"),
				("surgeries", "Surgeries", "int"),
				("ssi", "SSI Cases", "int"),
				("ssi_rate", "SSI Rate (%)", "float"),
				*(
					item
					for bucket in ssi_indicators.NNIS_BUCKETS
					for item in (
						(f"nnis_{bucket}", f"Surgeries NNIS {bucket}", "int"),
						(f"ssi_nnis_{bucket}", f"SSI NNIS {bucket}", "int"),
						(f"ssi_rate_nnis_{bucket}", f"SSI Rate NNIS {bucket} (%)", "float"),
					)
				),
				("nnis_unknown", "NNIS Not Calculated", "int"),
				("prophylaxis", "With Prophylaxis", "int"),
				("prophylaxis_rate", "Prophylaxis Rate (%)", "float"),
				("on_time", "Prophylaxis On Time", "int"),
				("on_time_rate", "On Time Rate (%)", "float"),
			),
			rows=ssi_summary_rows,
			roles=ROLES,
		),
		ExportKind(
			key=ICU_CASES,
			label="ICU infections (cases)",
			fields=_fields(
				("name", "HAI Case"),
				("patient_code_masked", "Patient Code"),
				("birth_year", "Birth Year", "int"),
				("sex", "Sex", "select"),
				("department_name", "Department"),
				("onset_date", "Onset Date", "date"),
				("def_code", "Definition Code"),
				("infection_site", "Infection Site", "select"),
				("device_type", "Device", "select"),
				("organisms", "Organisms"),
				("mdro_flags", "MDRO Flags"),
				("outcome", "Outcome", "select"),
				("reporting_period", "Reporting Period"),
			),
			rows=icu_case_rows,
			roles=ROLES,
		),
		ExportKind(
			key=ICU_SUMMARY,
			label="ICU infections by department",
			fields=_fields(
				("month", "Month"),
				("department_name", "Department"),
				("patient_days", "Patient Days", "int"),
				("vent_days", "Ventilator Days", "int"),
				("cvc_days", "Central Line Days", "int"),
				("urinary_catheter_days", "Urinary Catheter Days", "int"),
				("cases", "HAI Cases", "int"),
				("hai", "HAI per 1,000 Patient Days", "float"),
				("vap", "VAP per 1,000 Ventilator Days", "float"),
				("clabsi", "CLABSI per 1,000 Central Line Days", "float"),
				("cauti", "CAUTI per 1,000 Urinary Catheter Days", "float"),
				("vent_utilization", "Ventilator Use (%)", "float"),
			),
			rows=icu_summary_rows,
			roles=ROLES,
		),
	]
