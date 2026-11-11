"""Loại import "Danh sách phẫu thuật" cho khung `core.importer` (FEAT-064; UC-49 A1; FR-M9-28, F-21; D3; A-147 i).

File CSV/Excel xuất tay từ HIS hoặc phòng mổ (không kết nối HIS), đọc qua Import Mapping Profile: một dòng một ca
phẫu thuật. Ca đã có (cùng nhóm, ngày mổ, mã người bệnh — so bằng hash) báo "đã có", không ghi đè phần R11 đã bổ sung.
Thiếu ASA / loại vết mổ / thời gian → vẫn ghi, ``data_complete = 0`` để R11 bổ sung trên SCR-57. Cột họ tên bị bỏ
(BRU-HAI-005); file nguồn có mã người bệnh rõ nên bị xóa sau khi ghi (``purge_file``).
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from tracecore.core import patient_code
from tracecore.core.errors import BlockedError
from tracecore.core.importer import Column, ImportKind, Issue, RowError, department_ref
from tracecore.hai_surveillance import ssi

KEY = "surgical_list"
SEPARATOR = "|"
# tiêu đề cột họ tên người bệnh (so sau khi bỏ dấu, không phân biệt hoa thường) — không lưu (BRU-HAI-005)
NAME_COLUMNS = (
	"patient name",
	"patient_name",
	"full name",
	"first name",
	"last name",
	"ho ten",
	"ho va ten",
	"ten benh nhan",
	"ten nguoi benh",
)
VALUE_FIELDS = (
	"patient_code",
	"birth_year",
	"sex",
	"surgery_date",
	"asa_score",
	"wound_class",
	"duration_min",
	"has_implant",
	"prophylaxis_given",
	"prophylaxis_agent",
	"prophylaxis_minutes_before_incision",
	"discharge_date",
)


def _group(value):
	code = " ".join(str(value or "").split()).upper()
	return code if code and frappe.db.exists(ssi.GROUP, code) else None


def _key(values) -> str:
	group = " ".join(str(values.get("procedure_group") or "").split()).upper()
	day = values.get("surgery_date")
	hashed = patient_code.hash_of(values.get("patient_code")) if values.get("patient_code") else None
	return f"{group}{SEPARATOR}{getdate(day)}{SEPARATOR}{hashed}" if group and day and hashed else ""


def _exists(code) -> bool:
	group, day, hashed = code.split(SEPARATOR)
	return bool(
		frappe.db.exists(
			ssi.DOCTYPE, {"procedure_group": group, "surgery_date": day, "patient_code_hash": hashed}
		)
	)


def _doc(values):
	doc = frappe.new_doc(ssi.DOCTYPE)
	doc.update({field: values.get(field) for field in VALUE_FIELDS if values.get(field) not in (None, "")})
	doc.department = department_ref(values.get("department"))
	doc.procedure_group = _group(values.get("procedure_group"))
	doc.source = ssi.IMPORT
	doc.import_batch = frappe.flags.tc_import_batch
	for field in ("has_implant", "prophylaxis_given"):
		doc.set(field, cint(doc.get(field)))
	return doc


def _issue(row, error):
	field = (error.block.items or [None])[0]
	return Issue(row, error.block.code, field, error.block.reason)


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
	if not _group(values.get("procedure_group")):
		return [
			Issue(
				head.row,
				"VALUE_INVALID",
				"procedure_group",
				_("Procedure group {0} does not exist.").format(values.get("procedure_group")),
			)
		]
	doc = _doc(values)
	frappe.db.savepoint("tc_ssi_probe")
	try:
		doc.run_method("validate")
	except BlockedError as error:
		return [_issue(head.row, error)]
	except frappe.ValidationError as error:
		return [Issue(head.row, "VALUE_INVALID", None, str(error))]
	finally:
		frappe.db.rollback(save_point="tc_ssi_probe")
	return []


def _write(unit):
	head = unit[0]
	doc = _doc(head.values)
	try:
		doc.insert(ignore_permissions=True)
	except BlockedError as error:
		raise RowError([_issue(head.row, error)]) from None
	return doc.name


def _can_import():
	return bool(frappe.has_permission(ssi.DOCTYPE, "create"))


def import_kinds():
	"""Hook ``tracecore_import_kinds``."""
	return [
		ImportKind(
			key=KEY,
			label="Surgery list",
			doctype=ssi.DOCTYPE,
			columns=[
				Column("patient_code", "Patient Code", required=True),
				Column("birth_year", "Birth Year", kind="int"),
				Column("sex", "Sex", kind="select", options=("Male", "Female", "Other")),
				Column("department", "Department", required=True, help="Department name as in TraceCore."),
				Column("procedure_group", "Procedure Group Code", required=True),
				Column("surgery_date", "Surgery Date", required=True, kind="date"),
				Column("asa_score", "ASA Score", kind="int", help="1 to 5; may be completed later."),
				Column("wound_class", "Wound Class", kind="select", options=ssi.WOUNDS),
				Column("duration_min", "Duration (minutes)", kind="int"),
				Column("has_implant", "Implant", kind="check"),
				Column("prophylaxis_given", "Prophylaxis Given", kind="check"),
				Column("prophylaxis_agent", "Antibiotic"),
				Column(
					"prophylaxis_minutes_before_incision",
					"Minutes before Incision",
					kind="int",
					help="Negative = given after the incision.",
				),
				Column("discharge_date", "Discharge Date", kind="date"),
			],
			code_field="surgery_date",
			code_of=_key,
			exists=_exists,
			validate=_validate,
			write=_write,
			ignored_columns=NAME_COLUMNS,
			purge_file=True,
			roles=("TC R11", "TC R01", "System Manager"),
			can_import=_can_import,
			guide=(
				"One row per operation. A surgery already registered (same group, day and patient) is skipped.",
				"Missing ASA score, wound class or duration can be completed later on the surgical site infection screen.",
				"Patient names are not stored: name columns are ignored.",
			),
		)
	]
