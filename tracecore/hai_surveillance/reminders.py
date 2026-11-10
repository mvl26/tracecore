"""Nhắc mẫu số ngày thiếu và gói dự phòng chưa chấm (FEAT-062; FR-M13-03, .1, .2, FR-M12-07, FR-M12-07.2; ADR-014;
A-141 Q1, Q3, c, d).

Scheduler 15 phút (``run``), mỗi việc một lần mỗi khoa mỗi ngày (khử trùng theo `Notification Delivery` như
``admin_reports.environment.remind_missing``):

- sau ``census_reminder_time`` (mặc định 10:00): khoa nội trú (`tc_inpatient`, đang dùng, không phải nhóm) chưa có mẫu
  số ngày hôm trước → ``CENSUS_MISSING`` cho R12 của khoa + R11 (vai trò mặc định của Rule);
- sau ``bundle_reminder_time`` (mặc định 10:00): khoa có đợt thiết bị đang mở chưa có phiếu gói dự phòng ghi sổ
  trong ngày → ``BUNDLE_CHECK_DUE`` cho R08 + R12 của khoa, một thông báo liệt kê các đợt (mã BN che).
"""

from datetime import datetime, time

import frappe
from frappe import _
from frappe.utils import add_days, formatdate, get_datetime, get_time, getdate, now_datetime

from tracecore.core import notification
from tracecore.hai_surveillance import census, episodes

CENSUS_EVENT = "CENSUS_MISSING"
BUNDLE_EVENT = "BUNDLE_CHECK_DUE"
SETTINGS = "IC Program Settings"
DEFAULT_TIME = time(10, 0)
R08, R12 = "TC R08", "TC R12"


def _time(field):
	value = frappe.db.get_single_value(SETTINGS, field)
	return get_time(value) if value else DEFAULT_TIME


def department_users(department, roles):
	"""Người dùng đang bật có một trong ``roles`` và User Permission Department = khoa."""
	permitted = frappe.get_all(
		"User Permission", filters={"allow": "Department", "for_value": department}, pluck="user"
	)
	if not permitted:
		return []
	holders = frappe.get_all(
		"Has Role",
		filters={"role": ["in", list(roles)], "parenttype": "User", "parent": ["in", permitted]},
		pluck="parent",
	)
	return sorted(
		set(frappe.get_all("User", filters={"name": ["in", holders or [""]], "enabled": 1}, pluck="name"))
	)


def _sent(event, department, marker):
	return frappe.db.exists(
		"Notification Delivery",
		{"event_code": event, "ref_doctype": "Department", "ref_name": department, "message": marker},
	)


def run(now=None):
	now = get_datetime(now) if now else now_datetime()
	day = getdate(now)
	if now >= datetime.combine(day, _time("census_reminder_time")):
		remind_census(day)
	if now >= datetime.combine(day, _time("bundle_reminder_time")):
		remind_bundles(day)


def remind_census(day):
	"""Khoa nội trú thiếu mẫu số của ngày hôm trước ``day`` (FR-M13-03, .2)."""
	target = add_days(day, -1)
	entered = set(
		frappe.get_all(census.DOCTYPE, filters={"census_date": getdate(target)}, pluck="department")
	)
	for ward in census.inpatient_wards():
		if ward.name in entered:
			continue
		marker = _("No daily census of {0} for {1}.").format(
			ward.department_name or ward.name, formatdate(target)
		)
		if _sent(CENSUS_EVENT, ward.name, marker):
			continue
		notification.emit(
			CENSUS_EVENT,
			frappe._dict(doctype="Department", name=ward.name),
			subject=_("Daily census missing: {0}").format(ward.department_name or ward.name),
			message=marker,
			users=department_users(ward.name, (R12,)),
			link="/ksnk-khoa/mau-so",
		)


def unchecked_episodes(day):
	"""Đợt đang mở (đặt ≤ ``day``) chưa có phiếu gói dự phòng ghi sổ trong ngày."""
	rows = frappe.get_all(
		episodes.DOCTYPE,
		filters={"status": episodes.OPEN, "inserted_on": ["<=", getdate(day)]},
		fields=["name", "department", "device_type", "patient_code_masked"],
		order_by="department asc, inserted_on asc",
	)
	checked = episodes.bundle_status([row.name for row in rows], day)
	return [row for row in rows if row.name not in checked]


def remind_bundles(day):
	"""Một nhắc mỗi khoa mỗi ngày cho các đợt chưa chấm gói (FR-M12-07, .2; A-141 Q3)."""
	by_department = {}
	for row in unchecked_episodes(day):
		by_department.setdefault(row.department, []).append(row)
	for department, rows in by_department.items():
		label = frappe.db.get_value("Department", department, "department_name") or department
		header = _("Prevention bundle not checked today ({0}) in {1}:").format(formatdate(day), label)
		if frappe.db.exists(
			"Notification Delivery",
			{
				"event_code": BUNDLE_EVENT,
				"ref_doctype": "Department",
				"ref_name": department,
				"message": ["like", f"{header}%"],
			},
		):
			continue
		lines = [f"{row.patient_code_masked} · {_(row.device_type)}" for row in rows]
		notification.emit(
			BUNDLE_EVENT,
			frappe._dict(doctype="Department", name=department),
			subject=_("Prevention bundle check due: {0}").format(label),
			message="\n".join([header, *lines]),
			users=department_users(department, (R08, R12)),
			link="/ksnk-khoa/mau-so",
		)
