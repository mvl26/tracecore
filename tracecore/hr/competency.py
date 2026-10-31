"""Ma trận năng lực theo trạm (FEAT-037, FR-M4-03, UC-20, BRU-HR-001).

Station Competency (FEAT-003) cho phép nhân viên vào một trạm trong khoảng hiệu lực; FEAT-037 thêm chứng chỉ bắt buộc
(bảng con ``required_certificates``), người đánh giá, gán/thu hồi từ ma trận và quyền tạm tối đa 24 giờ. Năng lực mà
chứng chỉ bắt buộc không còn hạn bị **tạm dừng theo tính toán** (không đổi ``is_active``): gia hạn chứng chỉ là hiệu
lực lại ngay. Đăng nhập trạm kiểm qua hook ``tracecore_competency_missing_certificates`` (core không import hr).
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, cstr, get_datetime, getdate, now_datetime, today

from tracecore.core import notification
from tracecore.core.errors import Block, BlockedError
from tracecore.hr import certificates

DOCTYPE = "Station Competency"
MANAGERS = ("TC R02", "TC R10", "System Manager")
READERS = (*MANAGERS, "TC R01")
TEMPORARY_MAX_HOURS = 24


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _has_any_role(roles, user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(roles))


def _require_manager():
	if not _has_any_role(MANAGERS):
		raise _blocked(
			"COMPETENCY_NOT_ALLOWED",
			_("Not allowed"),
			_("Only R02 or R10 can grant or revoke station competencies."),
			_("Ask R02 to do this step."),
		)


def _require_reader():
	if not _has_any_role(READERS):
		raise _blocked(
			"COMPETENCY_NOT_ALLOWED",
			_("Not allowed"),
			_("Only R01, R02 or R10 can open the competency matrix."),
			_("Ask R02 for the station assignment."),
		)


# --- chứng chỉ bắt buộc -------------------------------------------------------------------------------------------


def required_types(competency_name) -> list[str]:
	return sorted(
		frappe.get_all(
			"Competency Required Cert",
			filters={"parent": competency_name, "parenttype": DOCTYPE},
			pluck="certificate_type",
		)
	)


def missing_certificate_types(employee, competency_name, at=None) -> list[str]:
	"""Loại chứng chỉ bắt buộc của năng lực mà `employee` chưa có bản còn hạn vào thời điểm `at` (mặc định bây giờ).

	Hàm hook ``tracecore_competency_missing_certificates`` của đăng nhập trạm (FR-M4-03.1); rỗng = đủ.
	"""
	required = required_types(competency_name)
	if not required:
		return []
	valid = certificates.valid_certificate_types(employee, getdate(at or today()))
	return [certificate_type for certificate_type in required if certificate_type not in valid]


# --- gán / thu hồi ------------------------------------------------------------------------------------------------


def grant(
	employee,
	station,
	valid_until,
	valid_from=None,
	evaluator=None,
	evaluated_on=None,
	required_certificates=(),
	is_temporary=0,
	reason=None,
):
	"""R02/R10 gán năng lực `station` cho `employee`; trả Station Competency. Từ chối nghiệp vụ bằng `BlockedError`."""
	_require_manager()
	if not frappe.db.exists("Employee", {"name": employee, "status": "Active"}):
		raise _blocked(
			"EMPLOYEE_INVALID",
			_("Employee not found"),
			_("Employee {0} does not exist or is not active.").format(employee),
			_("Choose an active employee."),
		)
	row = frappe.db.get_value("Zone Station", station, ["is_zone", "is_active"], as_dict=True)
	if not row or row.is_zone or not row.is_active:
		raise _blocked(
			"STATION_INVALID",
			_("Station not valid"),
			_("{0} is not an active station.").format(station),
			_("Choose an active station, not a zone."),
		)
	types = list(dict.fromkeys(certificates.normalize_type(value) for value in required_certificates or ()))
	known = certificates.certificate_types()
	unknown = [value for value in types if value not in known]
	if unknown:
		raise _blocked(
			"CERTIFICATE_TYPE_INVALID",
			_("Certificate type not valid"),
			_("Unknown certificate type: {0}.").format(", ".join(map(cstr, unknown))),
			_("Choose the certificate types from the list."),
		)
	start = get_datetime(valid_from) if valid_from else now_datetime()
	end = get_datetime(valid_until)
	if end <= start:
		raise _blocked(
			"COMPETENCY_INVALID",
			_("Period not valid"),
			_("The competency must end after it starts."),
			_("Enter a later end date and time."),
		)
	if cint(is_temporary):
		if not cstr(reason).strip():
			raise _blocked(
				"REASON_REQUIRED",
				_("Reason is required"),
				_("A temporary competency needs the reason for the staff shortage."),
				_("Enter the reason, then try again."),
			)
		if end > add_to_date(start, hours=TEMPORARY_MAX_HOURS):
			raise _blocked(
				"TEMP_TOO_LONG",
				_("Temporary access is too long"),
				_("A temporary competency lasts at most {0} hours.").format(TEMPORARY_MAX_HOURS),
				_("Choose an end time within {0} hours.").format(TEMPORARY_MAX_HOURS),
			)
	if frappe.db.exists(
		DOCTYPE,
		{
			"employee": employee,
			"station": station,
			"is_active": 1,
			"valid_from": ["<=", end],
			"valid_until": [">=", start],
		},
	):
		raise _blocked(
			"COMPETENCY_EXISTS",
			_("Competency already granted"),
			_("{0} already has an active competency at {1} for this period.").format(employee, station),
			_("Revoke the existing competency first, then grant a new one."),
		)
	return frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"employee": employee,
			"station": station,
			"valid_from": start,
			"valid_until": end,
			"evaluator": evaluator or frappe.session.user,
			"evaluated_on": evaluated_on or today(),
			"is_temporary": cint(is_temporary),
			"temporary_reason": cstr(reason).strip() if cint(is_temporary) else None,
			"approved_by": frappe.session.user if cint(is_temporary) else None,
			"required_certificates": [{"certificate_type": value} for value in types],
		}
	).insert(ignore_permissions=True)


def revoke(competency_name, reason):
	"""Thu hồi năng lực (``is_active`` = 0, bản ghi giữ nguyên làm lịch sử); lý do bắt buộc."""
	_require_manager()
	if not cstr(reason).strip():
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason for revoking the competency was entered."),
			_("Enter the reason, then try again."),
		)
	doc = frappe.get_doc(DOCTYPE, competency_name)
	if not doc.is_active:
		raise _blocked(
			"COMPETENCY_NOT_ACTIVE",
			_("Competency already revoked"),
			_("Competency {0} is no longer active.").format(competency_name),
			_("Open the matrix to see the current competencies."),
		)
	doc.is_active = 0
	doc.revoke_reason = cstr(reason).strip()
	doc.save(ignore_permissions=True)
	return doc


# --- ma trận ------------------------------------------------------------------------------------------------------


def _cell(row, employee):
	missing = missing_certificate_types(employee, row.name)
	state = "suspended" if missing else ("temporary" if row.is_temporary else "valid")
	return {
		"state": state,
		"competency": row.name,
		"valid_until": row.valid_until,
		"missing": missing,
		"required": required_types(row.name),
	}


def matrix(zone=None):
	"""Nhân viên theo trạm trên một màn (FR-M4-03.4). Trạng thái ô: none, valid, temporary, suspended (thiếu chứng chỉ)."""
	_require_reader()
	filters = {"is_zone": 0, "is_active": 1}
	stations = frappe.get_all(
		"Zone Station",
		filters=filters,
		fields=["name", "zone_station_name", "station_no", "parent_zone"],
	)
	stations.sort(key=lambda row: (not cint(row.station_no), cint(row.station_no), row.name))
	if zone:
		stations = [row for row in stations if row.parent_zone == zone]
	names = [row.name for row in stations]
	now = now_datetime()
	by_employee: dict[str, dict] = {}
	if names:
		for row in frappe.get_all(
			DOCTYPE,
			filters={
				"station": ["in", names],
				"is_active": 1,
				"valid_from": ["<=", now],
				"valid_until": [">=", now],
			},
			fields=["name", "employee", "station", "valid_until", "is_temporary"],
			order_by="is_temporary asc, valid_until desc",
		):
			cells = by_employee.setdefault(row.employee, {})
			current = _cell(row, row.employee)
			# nhiều bản ghi cùng trạm: bản đủ điều kiện thắng bản đang tạm dừng
			if row.station not in cells or (
				cells[row.station]["state"] == "suspended" and current["state"] != "suspended"
			):
				cells[row.station] = current
	employees = []
	for employee in frappe.get_all(
		"Employee",
		filters={"status": "Active", "user_id": ["is", "set"]},
		fields=["name", "employee_name", "department"],
		order_by="employee_name asc",
	):
		cells = {
			station: by_employee.get(employee.name, {}).get(station, {"state": "none"}) for station in names
		}
		employees.append(
			{
				"employee": employee.name,
				"employee_name": employee.employee_name,
				"department": employee.department,
				"cells": cells,
			}
		)
	zone_labels = dict(
		frappe.get_all(
			"Zone Station", filters={"is_zone": 1}, fields=["name", "zone_station_name"], as_list=True
		)
	)
	return {
		"stations": [
			{
				"name": row.name,
				"label": row.zone_station_name,
				"number": f"T{row.station_no}" if row.station_no else "",
				"zone": row.parent_zone,
				"zone_label": zone_labels.get(row.parent_zone) or row.parent_zone,
			}
			for row in stations
		],
		"employees": employees,
		"certificate_types": certificates.certificate_types(),
		"can_edit": _has_any_role(MANAGERS),
	}


# --- hết hạn chứng chỉ làm tạm dừng năng lực ------------------------------------------------------------------------


def notify_suspended(employee, certificate_type, certificate_no):
	"""Chứng chỉ vừa hết hạn: báo R02 và nhân viên về các năng lực yêu cầu loại chứng chỉ đó và đang bị tạm dừng."""
	now = now_datetime()
	for row in frappe.get_all(
		DOCTYPE,
		filters={"employee": employee, "is_active": 1, "valid_from": ["<=", now], "valid_until": [">=", now]},
		fields=["name", "station"],
	):
		if certificate_type not in required_types(row.name):
			continue
		if certificate_type not in missing_certificate_types(employee, row.name):
			continue  # còn chứng chỉ khác cùng loại còn hạn
		user = frappe.db.get_value("Employee", employee, "user_id")
		notification.emit(
			"COMPETENCY_SUSPENDED",
			frappe._dict(doctype=DOCTYPE, name=row.name),
			_("Competency at {0} of {1} is suspended: certificate {2} has expired").format(
				row.station, frappe.db.get_value("Employee", employee, "employee_name"), certificate_no
			),
			users=[user] if user else [],
		)
