"""Loại import Cơ số (Par Level) cho khung `core.importer` (FEAT-011 Task 7, FR-M9-11, FR-M8-01; A-41).

Ghi qua controller `Par Level` để luật `par.config` (đích hợp lệ, không trùng, giá trị, lịch sử) chạy như nhập tay.
"Đã có" theo (loại cơ số, loại đích, đích, khoa) — cùng khóa duy nhất của `par.config._check_unique`.
"""

import frappe
from frappe import _

from tracecore.core.importer import Column, ImportKind, Issue, department_ref
from tracecore.par.config import KIND_REPROCESSING, KIND_STOCK, REPROCESSING_TARGETS

SOURCES = ("IFU", "Estimate")
SEPARATOR = " | "


def _key(values):
	return SEPARATOR.join(
		str(values.get(field) or "") for field in ("par_kind", "target_doctype", "target", "department")
	)


def _exists(key):
	kind, doctype, target, department = [*key.split(SEPARATOR), "", "", "", ""][:4]
	return bool(
		frappe.db.exists(
			"Par Level",
			{
				"par_kind": kind,
				"target_doctype": doctype,
				"target": target,
				"department": department_ref(department) or ["is", "not set"],
			},
		)
	)


def _validate(unit):
	row = unit[0]
	values = row.values
	issues = []
	doctype, target = values.get("target_doctype"), values.get("target")
	if doctype and target and not frappe.db.exists(doctype, target):
		issues.append(
			Issue(
				row.row, "TARGET_NOT_FOUND", "target", _("{0} {1} does not exist.").format(_(doctype), target)
			)
		)
	if values.get("department") and not department_ref(values["department"]):
		issues.append(
			Issue(
				row.row,
				"DEPARTMENT_NOT_FOUND",
				"department",
				_("Department {0} does not exist.").format(values["department"]),
			)
		)
	return issues


def _write(unit):
	values = unit[0].values
	doc = frappe.get_doc(
		{
			"doctype": "Par Level",
			"par_kind": values["par_kind"],
			"target_doctype": values["target_doctype"],
			"target": values["target"],
			"department": department_ref(values.get("department")),
			"is_active": 1,
			"max_cycles": values.get("max_cycles") or 0,
			"source": values.get("source"),
			"warn_percent": values.get("warn_percent") or 0,
			"warn_count": values.get("warn_count") or 0,
			"min_qty": values.get("min_qty") or 0,
			"max_qty": values.get("max_qty") or 0,
			"over_percent": values.get("over_percent") or 0,
			"is_emergency_dept": 1 if values.get("is_emergency_dept") else 0,
			"reason": values.get("reason"),
		}
	)
	return doc.insert().name


def import_kinds():
	"""Hook ``tracecore_import_kinds``."""
	return [
		ImportKind(
			key="par_level",
			label="Par levels",
			doctype="Par Level",
			columns=[
				Column(
					"par_kind",
					"Par Kind",
					required=True,
					kind="select",
					options=(KIND_REPROCESSING, KIND_STOCK),
				),
				Column(
					"target_doctype",
					"Target Type",
					required=True,
					kind="select",
					options=REPROCESSING_TARGETS,
				),
				Column("target", "Target", required=True, help="Instrument code or set type code."),
				Column("department", "Department", help="Required for a department stock par level."),
				Column("max_cycles", "Max Cycles", kind="int"),
				Column("source", "Source", kind="select", options=SOURCES),
				Column("warn_percent", "Warning Percent", kind="float"),
				Column("warn_count", "Warning Count", kind="int"),
				Column("min_qty", "Min Stock Qty", kind="int"),
				Column("max_qty", "Max Stock Qty", kind="int"),
				Column("over_percent", "Allowed Overshoot Percent", kind="float"),
				Column("is_emergency_dept", "Emergency Department", kind="check"),
				Column("reason", "Reason"),
			],
			code_field="target",
			code_of=_key,
			exists=_exists,
			validate=_validate,
			write=_write,
		)
	]
