"""Engine chỉ số KSNK: tính, khóa, mở khóa kỳ (FEAT-056; FR-M9-27, FR-M9-27.1; BRU-RPT-001, BRU-RPT-003;
architecture §6.10, §8.5; plan D1).

Kỳ là tháng ``YYYY-MM`` (D1: chưa Link sang `IC Reporting Period` của M13; FEAT-063 gọi các hàm dưới khi R01 khóa/mở
kỳ). Hàm tính lấy từ sổ `core.indicators` (hook ``tracecore_ic_indicators``) — M9 không import module nghiệp vụ.
Giá trị lưu một lần thành `IC Indicator Value` (materialized); bảng chỉ số chỉ đọc, không tính lại (NFR-PERF-05).
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from tracecore.core import audit, indicators

DOCTYPE = "IC Indicator Value"
PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
NOT_CALCULATED = "Not calculated"
SMALL_SAMPLE = "Insufficient sample"
UNLOCK_ROLE = "TC R01"
SCALE = {"Percentage": 100, "Rate per 1000": 1000}


def check_period(period) -> str:
	if not isinstance(period, str) or not PERIOD.match(period):
		frappe.throw(_("Period must be in the form YYYY-MM, for example 2026-10."))
	return period


def is_locked(period) -> bool:
	return bool(frappe.db.exists(DOCTYPE, {"period": period, "locked": 1}))


def measure(kind, numerator, denominator, sample_size, min_sample=0):
	"""(giá trị, ghi chú). Mẫu số 0 với tỷ lệ/tỷ suất → "Không tính", không ghi 0 (BRU-RPT-001, BRU-HAI-006)."""
	numerator, denominator = flt(numerator), flt(denominator)
	if kind in SCALE:
		if not denominator:
			return 0, NOT_CALCULATED
		value = numerator / denominator * SCALE[kind]
	else:
		value = numerator
	note = SMALL_SAMPLE if min_sample and cint(sample_size) < cint(min_sample) else ""
	return flt(value, 4), note


def display_value(row):
	"""Giá trị để hiện: ``None`` khi không tính được (không bao giờ hiện 0 thay cho "Không tính")."""
	return None if row.get("sample_note") == NOT_CALCULATED else flt(row.get("value"))


def status(row, ind) -> str:
	"""Trạng thái bằng chữ của một giá trị so với mục tiêu: Not calculated / Insufficient sample / Met / Not met / ""."""
	if row.get("sample_note"):
		return row.get("sample_note")
	if not ind.get("target_direction"):
		return ""
	value, target = flt(row.get("value")), flt(ind.get("national_target"))
	met = value >= target if ind.get("target_direction") == "Higher is better" else value <= target
	return "Met" if met else "Not met"


def _departments():
	return frappe.get_all(
		"Department", filters={"tc_is_ward": 1, "disabled": 0, "is_group": 0}, pluck="name", order_by="name"
	)


def _existing(code, period, department):
	return frappe.db.get_value(
		DOCTYPE, {"indicator": code, "period": period, "department": department or ("is", "not set")}, "name"
	)


def _write(code, period, department, values):
	name = _existing(code, period, department)
	doc = frappe.get_doc(DOCTYPE, name) if name else frappe.new_doc(DOCTYPE)
	doc.update({"indicator": code, "period": period, "department": department, **values})
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def compute_period(period):
	"""Tính và ghi giá trị mọi chỉ số đang dùng, cho toàn viện và từng khoa có dữ liệu, của kỳ chưa khóa.

	Kỳ đã khóa: không làm gì (BRU-RPT-003). Khoa mà hàm tính trả (0, 0, 0) là khoa không có dữ liệu: không ghi dòng.
	Ghi đè dòng tạm cũ của kỳ chưa khóa; thay đổi có Audit Log old/new (doc_events).
	"""
	check_period(period)
	if is_locked(period):
		return []
	methods = indicators.registry()
	scopes = [None, *_departments()]
	written = []
	for ind in frappe.get_all(
		"IC Indicator", filters={"is_active": 1}, fields=["name", "kind", "source_method", "min_sample"]
	):
		fn = methods.get(ind.source_method)
		if not fn:
			continue
		for department in scopes:
			numerator, denominator, sample_size = fn(period, department) or (0, 0, 0)
			if department and not (numerator or denominator or sample_size):
				continue
			value, note = measure(ind.kind, numerator, denominator, sample_size, ind.min_sample)
			written.append(
				_write(
					ind.name,
					period,
					department,
					{
						"numerator": flt(numerator),
						"denominator": flt(denominator),
						"sample_size": cint(sample_size),
						"value": value,
						"sample_note": note,
						"computed_on": now_datetime(),
					},
				)
			)
	return written


def lock_period(period):
	"""Tính (nếu kỳ chưa khóa) rồi khóa mọi giá trị của kỳ; gọi lại khi đã khóa thì giữ nguyên."""
	check_period(period)
	if is_locked(period):
		return
	compute_period(period)
	frappe.db.set_value(DOCTYPE, {"period": period}, "locked", 1, update_modified=False)


def unlock_period(period, reason):
	"""R01 mở khóa kỳ có lý do (FR-M9-27.1); Audit Log ghi lý do. Khóa lại thì tính lại."""
	check_period(period)
	if frappe.session.user != "Administrator" and UNLOCK_ROLE not in frappe.get_roles():
		frappe.throw(
			_("Only the head of infection control (R01) can unlock a reporting period."),
			frappe.PermissionError,
		)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Enter a reason to unlock period {0}.").format(period))
	if not is_locked(period):
		return
	frappe.db.set_value(DOCTYPE, {"period": period}, "locked", 0, update_modified=False)
	audit.log(
		"Override",
		DOCTYPE,
		None,
		old={"period": period, "locked": 1},
		new={"period": period, "locked": 0},
		reason=reason,
	)
