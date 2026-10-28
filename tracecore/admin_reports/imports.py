"""Loại import Khoa và Nhân viên cho khung `core.importer` (FEAT-011 Task 3, FR-M9-11, UC-39; A-41).

Đăng ký qua hook ``tracecore_import_kinds``. Ghi qua controller DocType (luật thẻ trạm duy nhất của
`core.account.validate_employee` chạy như nhập tay). Không có cột mã NV- (BRU-ID-006): mã nhân viên do hệ thống cấp.
Nhân viên "đã có" theo thẻ có sẵn của bệnh viện, nếu không có thẻ thì theo email người dùng; phải có ít nhất một trong
hai để import lại cùng file không tạo trùng (A-41 Q3).
"""

import frappe
from frappe import _

from tracecore.core.importer import Column, ImportKind, Issue, RowError, department_ref

GENDERS = ("Male", "Female", "Other")


def _companies():
	return frappe.get_all("Company", pluck="name", limit=2)


def _company():
	"""Company của Khoa/Nhân viên: Company mặc định; chưa đặt mặc định mà site chỉ có một Company thì dùng Company đó."""
	import erpnext

	company = erpnext.get_default_company()
	if company:
		return company
	companies = _companies()
	return companies[0] if len(companies) == 1 else None


def _company_issue(row):
	"""Không xác định được Company → lỗi dòng rõ ràng ở bước Kiểm tra, không để Department/Employee báo thiếu company."""
	if _company():
		return []
	return [
		Issue(
			row.row,
			"COMPANY_NOT_SET",
			None,
			_("No default company is set; ask R10 to set the default company before importing."),
		)
	]


# --- Khoa -------------------------------------------------------------------------------------------------------


def _department_exists(code):
	return bool(frappe.db.exists("Department", {"department_name": code}))


def _validate_department(unit):
	row = unit[0]
	parent = row.values.get("parent_department")
	if parent and not department_ref(parent):
		return [
			Issue(
				row.row,
				"PARENT_NOT_FOUND",
				"parent_department",
				_("Parent department {0} does not exist.").format(parent),
			)
		]
	return _company_issue(row)


def _write_department(unit):
	values = unit[0].values
	doc = frappe.get_doc(
		{
			"doctype": "Department",
			"department_name": values["department_name"],
			"parent_department": department_ref(values.get("parent_department")),
			"company": _company(),
			"tc_is_ward": 1 if values.get("is_ward") else 0,  # ô trống theo mặc định của trường (0)
		}
	)
	return doc.insert().name


# --- Nhân viên -------------------------------------------------------------------------------------------------


def _employee_code(values):
	return values.get("card_id") or values.get("user_email") or ""


def _employee_exists(code):
	from tracecore.core import station_auth

	card = station_auth.normalize_card_id(code)
	return bool(
		frappe.db.exists("Employee", {"tc_card_id": card}) or frappe.db.exists("Employee", {"user_id": code})
	)


def _validate_employee(unit):
	row = unit[0]
	values = row.values
	issues = []
	if not (values.get("card_id") or values.get("user_email")):
		issues.append(
			Issue(
				row.row,
				"IDENTITY_REQUIRED",
				"card_id",
				_(
					"Enter the station card ID or the user email, so the row is recognized when imported again."
				),
			)
		)
	if not department_ref(values.get("department")):
		issues.append(
			Issue(
				row.row,
				"DEPARTMENT_NOT_FOUND",
				"department",
				_("Department {0} does not exist.").format(values.get("department")),
			)
		)
	if values.get("user_email") and not frappe.db.exists("User", values["user_email"]):
		issues.append(
			Issue(
				row.row,
				"USER_NOT_FOUND",
				"user_email",
				_("User {0} does not exist.").format(values["user_email"]),
			)
		)
	return issues + _company_issue(row)


def _write_employee(unit):
	row = unit[0]
	values = row.values
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": values["first_name"],
			"last_name": values.get("last_name"),
			"gender": values["gender"],
			"date_of_birth": values["date_of_birth"],
			"date_of_joining": values["date_of_joining"],
			"department": department_ref(values["department"]),
			"company": _company(),
			"status": "Active",
			"user_id": values.get("user_email"),
			"tc_card_id": values.get("card_id"),
			"tc_card_enabled": 1 if values.get("card_id") else 0,
		}
	)
	try:
		return doc.insert().name
	except frappe.ValidationError as error:
		raise RowError(
			[Issue(row.row, "EMPLOYEE_INVALID", None, frappe.utils.strip_html(str(error)))]
		) from None


def import_kinds():
	"""Hook ``tracecore_import_kinds``."""
	return [
		ImportKind(
			key="department",
			label="Departments",
			doctype="Department",
			columns=[
				Column("department_name", "Department Name", required=True),
				Column("parent_department", "Parent Department Name", help="Name of an existing department."),
				Column(
					"is_ward", "Ward", kind="check", help="Yes for a clinical department that uses TraceCore."
				),
			],
			code_field="department_name",
			exists=_department_exists,
			validate=_validate_department,
			write=_write_department,
		),
		ImportKind(
			key="employee",
			label="Employees",
			doctype="Employee",
			columns=[
				Column("first_name", "Given Name", required=True),
				Column("last_name", "Family Name"),
				Column("gender", "Gender", required=True, kind="select", options=GENDERS),
				Column("date_of_birth", "Date of Birth", required=True, kind="date"),
				Column("date_of_joining", "Joining Date", required=True, kind="date"),
				Column("department", "Department", required=True),
				Column("card_id", "Card ID", help="Existing hospital card used to log in at stations."),
				Column("user_email", "User Email", help="Email of an existing user account."),
			],
			code_field="card_id",
			code_of=_employee_code,
			exists=_employee_exists,
			validate=_validate_employee,
			write=_write_employee,
			forbidden_columns=("Employee Code", "Employee", "Employee ID"),
			guide=("The employee code (NV-) is issued by the system after import.",),
		),
	]
