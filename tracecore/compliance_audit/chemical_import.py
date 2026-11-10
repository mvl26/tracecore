"""Loại import "Hóa chất KSNK" cho khung `core.importer` (FEAT-066; FR-M12-12, FR-M9-28, EI-SW-010, F-21; UC-46 bước 2).

File CSV/Excel do khoa Dược xuất tay, đọc qua Import Mapping Profile (D3: không kết nối trực tuyến). Mỗi dòng: ngày
xuất (→ kỳ tháng), khoa, mã Item, số lượng, đơn vị (tùy chọn, mặc định UOM kho), số chứng từ. Khóa không trùng
``kỳ|khoa|item|số chứng từ``: nhập lại cùng file tạo 0 bản ghi ("Existing"), kể cả bản đã bị hủy khi chọn nguồn.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from tracecore.compliance_audit import chemicals
from tracecore.core.importer import Column, ImportKind, Issue, department_ref

KEY = "ic_chemical"
ROLES = ("TC R09", "TC R11", "TC R01", "System Manager")
COLUMNS = [
	Column("issue_date", "Issue Date", required=True, kind="date", help="Day the pharmacy issued the chemical."),
	Column("department", "Department", required=True, help="Department name or full name."),
	Column("item", "Item Code", required=True, help="Item with an infection control chemical type."),
	Column("qty", "Quantity", required=True, kind="float"),
	Column("uom", "UOM", help="Empty means the stock unit of the item."),
	Column("document_no", "Document No", required=True, help="Pharmacy issue document number."),
]


def _values(values) -> dict:
	day = values.get("issue_date")
	return {
		"period": str(getdate(day))[:7] if day else None,
		"posting_date": day,
		"department": department_ref(values.get("department")),
		"item": (values.get("item") or "").strip() or None,
	}


def code_of(values) -> str:
	head = _values(values)
	if not (head["period"] and head["department"] and head["item"] and values.get("document_no")):
		return ""
	return "|".join((head["period"], head["department"], head["item"], str(values["document_no"]).strip()))


def exists(code) -> bool:
	return bool(frappe.db.exists(chemicals.DOCTYPE, {"source": chemicals.IMPORT, "source_row": code}))


def _row_issues(row) -> list[Issue]:
	values = row.values
	head = _values(values)
	issues = []
	if values.get("department") and not head["department"]:
		issues.append(
			Issue(row.row, "DEPARTMENT_NOT_FOUND", "department", _("Department {0} does not exist.").format(values["department"]))
		)
	item = head["item"]
	if item and not frappe.db.exists("Item", item):
		issues.append(Issue(row.row, "ITEM_NOT_FOUND", "item", _("Item {0} does not exist.").format(item)))
	elif item and not chemicals.chemical_type(item):
		issues.append(
			Issue(
				row.row,
				"ITEM_NOT_IC_CHEMICAL",
				"item",
				_("Item {0} has no infection control chemical type.").format(item),
			)
		)
	elif item and values.get("uom") and not chemicals.uom_factor(item, values["uom"]):
		issues.append(
			Issue(
				row.row,
				"UOM_NOT_CONVERTIBLE",
				"uom",
				_("Item {0} has no conversion for unit {1}.").format(item, values["uom"]),
			)
		)
	if values.get("qty") is not None and flt(values["qty"]) <= 0:
		issues.append(Issue(row.row, "VALUE_INVALID", "qty", _("Quantity must be greater than 0.")))
	day = values.get("issue_date")
	if day and getdate(day) > getdate(today()):
		issues.append(Issue(row.row, "VALUE_INVALID", "issue_date", _("Issue date is in the future.")))
	return issues


def validate(unit) -> list[Issue]:
	return [issue for row in unit for issue in _row_issues(row)]


def write(unit) -> str:
	values = unit[0].values
	head = _values(values)
	qty = flt(values["qty"]) * chemicals.uom_factor(head["item"], values.get("uom"))
	doc = chemicals.record(
		{
			**head,
			"qty": qty,
			"source_ref": str(values["document_no"]).strip(),
			"source_row": code_of(values),
		},
		chemicals.IMPORT,
		import_batch=frappe.flags.tc_import_batch,
	)
	return doc.name


def can_import() -> bool:
	return bool(set(frappe.get_roles()) & set(ROLES)) and bool(frappe.has_permission(chemicals.DOCTYPE, "create"))


def import_kinds():
	return [
		ImportKind(
			key=KEY,
			label="Infection Control Chemicals",
			doctype=chemicals.DOCTYPE,
			columns=COLUMNS,
			code_field="document_no",
			code_of=code_of,
			exists=exists,
			validate=validate,
			write=write,
			roles=ROLES,
			can_import=can_import,
			guide=(
				"One row per item and pharmacy issue document; the issue date decides the month.",
				"A file imported again creates nothing new.",
			),
		)
	]
