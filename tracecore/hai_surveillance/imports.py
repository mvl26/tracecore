"""Loại import "Mẫu số ngày" cho khung `core.importer` (FEAT-062; FR-M13-02, .1, .2, FR-M9-28, EI-SW-010, F-21; UC-47 A1;
A-141 Q2).

File CSV/Excel xuất tay từ HIS (D3: không kết nối HIS), đọc qua Import Mapping Profile: mỗi dòng = một (ngày, khoa).
Kiểm như nhập tay (số thiết bị ≤ số người bệnh, ngày không ở tương lai, khoa có thật); (ngày, khoa) đã có thì cập
nhật (``upsert``, kết quả "Updated"), bản đã khóa kỳ báo lỗi dòng. File không chứa mã người bệnh.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from tracecore.core.errors import BlockedError
from tracecore.core.importer import Column, ImportKind, Issue, RowError, department_ref
from tracecore.hai_surveillance import census

KEY = "ward_census"
SEPARATOR = "|"
COUNT_COLUMNS = ("patient_count", "vent_count", "cvc_count", "urinary_catheter_count")


def _key(values) -> str:
	department = department_ref(values.get("department"))
	day = values.get("census_date")
	return f"{department}{SEPARATOR}{getdate(day)}" if department and day else ""


def _exists(code) -> bool:
	department, _sep, day = code.partition(SEPARATOR)
	return bool(census.find(department, day))


def _values(values) -> dict:
	return {**values, "department": department_ref(values.get("department"))}


def _probe(values, name=None):
	"""Kiểm dòng bằng chính luật của DocType (không ghi): trả BlockedError hoặc None."""
	doc = frappe.get_doc(census.DOCTYPE, name) if name else frappe.new_doc(census.DOCTYPE)
	doc.update({key: values.get(key) for key in census.VALUE_FIELDS})
	doc.flags.tc_skip_duplicate_check = True
	try:
		census.validate(doc)
	except BlockedError as error:
		return error
	return None


def _validate(unit):
	head = unit[0]
	values = head.values
	if not department_ref(values.get("department")):
		return [
			Issue(
				head.row,
				"DEPARTMENT_NOT_FOUND",
				"department",
				_("Department {0} does not exist.").format(values.get("department")),
			)
		]
	values = _values(values)
	error = _probe(values, census.find(values["department"], values["census_date"]))
	if error:
		field = (error.block.items or [None])[0]
		return [Issue(head.row, error.block.code, field, error.block.reason)]
	return []


def _write(unit):
	head = unit[0]
	try:
		doc = census.save(
			_values(head.values),
			source=census.IMPORT,
			upsert=True,
			import_batch=frappe.flags.tc_import_batch,
		)
	except BlockedError as error:
		field = (error.block.items or [None])[0]
		raise RowError([Issue(head.row, error.block.code, field, error.block.reason)]) from None
	return doc.name


def _can_import():
	return bool(frappe.has_permission(census.DOCTYPE, "create"))


def import_kinds():
	count_help = "Whole number of 0 or more; cannot be more than inpatients."
	return [
		ImportKind(
			key=KEY,
			label="Daily ward census",
			doctype=census.DOCTYPE,
			columns=[
				Column("census_date", "Census date", required=True, kind="date"),
				Column("department", "Department", required=True, help="Department name as in TraceCore."),
				Column("patient_count", "Inpatients", required=True, kind="int"),
				Column("vent_count", "On ventilator", required=True, kind="int", help=count_help),
				Column("cvc_count", "Central line", required=True, kind="int", help=count_help),
				Column(
					"urinary_catheter_count", "Urinary catheter", required=True, kind="int", help=count_help
				),
				Column("admissions", "Admissions", kind="int"),
			],
			code_field="census_date",
			code_of=_key,
			exists=_exists,
			validate=_validate,
			write=_write,
			roles=("TC R11", "TC R10", "TC R01", "System Manager"),
			can_import=_can_import,
			guide=(
				"One row per department and day. Importing the same day again updates the counts of that day.",
			),
			upsert=True,
		)
	]
