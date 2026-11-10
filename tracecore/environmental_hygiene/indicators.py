"""Chỉ số M15 cho bảng chỉ số KSNK M9 qua hook `tracecore_ic_indicators` (FEAT-070; FR-M15-02, FR-M15-06; QĐ 38).

Hàm nhận kỳ ``YYYY-MM`` và khoa (rỗng = toàn viện), trả (tử số, mẫu số, cỡ mẫu):
- vệ sinh bề mặt khu nguy cơ cao Đạt (QĐ 38 ≥ 80 %), mẫu môi trường Đạt,
- hệ thống thông khí / nguồn nước được kiểm tra đúng hạn tại cuối kỳ (QĐ 38 ≥ 70 %, ≥ 90 %).
"""

import frappe
from frappe.utils import get_first_day, get_last_day, getdate

from tracecore.environmental_hygiene import audits

SURFACE_HIGH_RISK = "env_surface_high_risk_pass"
SAMPLE_PASS = "env_sample_pass"  # nosec B105 - mã chỉ số, không phải mật khẩu
VENTILATION_ON_TIME = "env_ventilation_on_time"
WATER_ON_TIME = "env_water_on_time"


def register():
	return {
		SURFACE_HIGH_RISK: surface_high_risk_pass,
		SAMPLE_PASS: sample_pass,
		VENTILATION_ON_TIME: ventilation_on_time,
		WATER_ON_TIME: water_on_time,
	}


def _bounds(period):
	start = getdate(f"{period}-01")
	return get_first_day(start), get_last_day(start)


def surface_high_risk_pass(period, department=None):
	passed, total = audits.high_risk_pass(*_bounds(period), department)
	return passed, total, total


def sample_pass(period, department=None):
	start, end = _bounds(period)
	filters = {"docstatus": 1, "sampled_on": ["between", [start, end]]}
	if department:
		filters["department"] = department
	rows = frappe.get_all("Environmental Sample", filters=filters, pluck="result")
	passed = sum(1 for result in rows if result == "Pass")
	return passed, len(rows), len(rows)


def _on_time(category, period, department):
	ok, total = audits.on_time(category, _bounds(period)[1], department)
	return ok, total, total


def ventilation_on_time(period, department=None):
	return _on_time("Ventilation", period, department)


def water_on_time(period, department=None):
	return _on_time("Water Supply", period, department)
