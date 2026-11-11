"""Tỷ suất NKBV theo khoa và kỳ (FEAT-063; FR-M13-10, 10.1, 10.2; BRU-HAI-006; UC-48 bước 5-6; A-144 d).

Mỗi hàm nhận ``(period "YYYY-MM", department | None)`` và trả ``(tử số, mẫu số, cỡ mẫu)`` cho engine M9 (hook
``tracecore_ic_indicators``). Tử số = ca **Xác định** đã ghi sổ có ngày khởi phát trong tháng; ca theo thiết bị chọn
theo ``device_type`` của phiên bản định nghĩa (không theo chuỗi mã). Mẫu số = ngày nằm viện / ngày thiết bị của
``census.denominators`` (nguồn khoa chọn, FEAT-062). Mẫu số 0 → "Không tính" (BRU-HAI-006), không bao giờ 0.
"""

import frappe
from frappe.utils import add_months, flt, getdate

from tracecore.hai_surveillance import census, periods

CASE = "HAI Case"
NOT_CALCULATED = "Not calculated"
SCALE = {"Percentage": 100, "Rate per 1000": 1000}
DEVICE_DAYS = {
	"Ventilator": "vent_days",
	"Central Line": "cvc_days",
	"Urinary Catheter": "urinary_catheter_days",
}
KEYS = (
	"HAI_RATE",
	"VAP_RATE",
	"CLABSI_RATE",
	"CAUTI_RATE",
	"VENT_UTILIZATION",
	"CVC_UTILIZATION",
	"URINARY_UTILIZATION",
)


def measure(kind, numerator, denominator):
	"""(giá trị, ghi chú) — cùng quy tắc engine M9: mẫu số 0 → "Not calculated" (BRU-HAI-006)."""
	numerator, denominator = flt(numerator), flt(denominator)
	if kind in SCALE:
		if not denominator:
			return None, NOT_CALCULATED
		return flt(numerator / denominator * SCALE[kind], 4), ""
	return numerator, ""


def _wards(period, department):
	if department:
		return [department]
	start, end = periods.bounds(period)
	return frappe.get_all(
		census.DOCTYPE,
		filters={"census_date": ["between", [start, end]]},
		pluck="department",
		distinct=True,
	)


def denominators(period, department=None):
	start, end = periods.bounds(period)
	total = {"patient_days": 0, "vent_days": 0, "cvc_days": 0, "urinary_catheter_days": 0}
	for ward in _wards(period, department):
		values = census.denominators(ward, start, end)
		for key in total:
			total[key] += values[key]
	return total


def confirmed(period, department=None, device=None):
	filters = {"docstatus": 1, "status": "Confirmed", "reporting_period": periods.check_month(period)}
	if department:
		filters["department"] = department
	if device:
		filters["device_type"] = device
	return frappe.db.count(CASE, filters)


def _rate(device=None):
	def compute(period, department=None):
		days = denominators(period, department)
		denominator = days[DEVICE_DAYS[device]] if device else days["patient_days"]
		return confirmed(period, department, device), denominator, denominator

	return compute


def _utilization(device):
	def compute(period, department=None):
		days = denominators(period, department)
		return days[DEVICE_DAYS[device]], days["patient_days"], days["patient_days"]

	return compute


hai_rate = _rate()
vap_rate = _rate("Ventilator")
clabsi_rate = _rate("Central Line")
cauti_rate = _rate("Urinary Catheter")
vent_utilization = _utilization("Ventilator")
cvc_utilization = _utilization("Central Line")
urinary_utilization = _utilization("Urinary Catheter")


def register():
	"""Hook ``tracecore_ic_indicators``."""
	return dict(
		zip(
			KEYS,
			(
				hai_rate,
				vap_rate,
				clabsi_rate,
				cauti_rate,
				vent_utilization,
				cvc_utilization,
				urinary_utilization,
			),
			strict=True,
		)
	)


# --- dữ liệu màn SCR-58 ---------------------------------------------------------------------------------------------


def _row(period, department):
	days = denominators(period, department)
	cases = confirmed(period, department)
	per_device = {
		key: measure("Rate per 1000", confirmed(period, department, device), days[DEVICE_DAYS[device]])[0]
		for key, device in (("vap", "Ventilator"), ("clabsi", "Central Line"), ("cauti", "Urinary Catheter"))
	}
	return {
		"department": department,
		"patient_days": days["patient_days"],
		"vent_days": days["vent_days"],
		"cvc_days": days["cvc_days"],
		"urinary_catheter_days": days["urinary_catheter_days"],
		"cases": cases,
		"hai": measure("Rate per 1000", cases, days["patient_days"])[0],
		**per_device,
		"vent_utilization": measure("Percentage", days["vent_days"], days["patient_days"])[0],
	}


def by_department(period):
	"""Một dòng mỗi khoa có mẫu số hoặc ca trong tháng; giá trị ``None`` = "Không tính"."""
	periods.check_month(period)
	wards = set(_wards(period, None))
	wards |= set(
		frappe.get_all(
			CASE,
			filters={"docstatus": 1, "status": "Confirmed", "reporting_period": period},
			pluck="department",
			distinct=True,
		)
	)
	names = dict(
		frappe.get_all(
			"Department",
			filters={"name": ["in", list(wards) or [""]]},
			fields=["name", "department_name"],
			as_list=True,
		)
	)
	rows = []
	for ward in wards:
		row = _row(period, ward)
		row["department_name"] = names.get(ward) or ward
		rows.append(row)
	rows.sort(key=lambda row: row["department_name"])
	return rows


def hospital(period):
	row = _row(period, None)
	row["department_name"] = None
	return row


def trend(period, count=12):
	"""Tỷ suất NKBV toàn viện ``count`` tháng tính lùi tới ``period`` (cũ trước)."""
	start = getdate(f"{periods.check_month(period)}-01")
	months = [periods.month_of(add_months(start, -step)) for step in range(count - 1, -1, -1)]
	out = []
	for month in months:
		days = denominators(month)
		cases = confirmed(month)
		out.append(
			{
				"month": month,
				"cases": cases,
				"patient_days": days["patient_days"],
				"value": measure("Rate per 1000", cases, days["patient_days"])[0],
				"locked": int(periods.is_locked(month)),
			}
		)
	return out
