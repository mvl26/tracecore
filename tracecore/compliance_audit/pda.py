"""Phiếu giám sát trên PDA/Page `station` (FEAT-060; SCR-52, FR-M12-04, NFR-AVAIL-05, ADR-003).

- ``context``: mẫu đã duyệt đang hiệu lực (chấm theo mục: Điểm %, Tất cả-hoặc-không; vệ sinh tay theo cơ hội là
  SCR-51 của FEAT-061) kèm mục, và khoa người dùng được làm phiếu; cũng là snapshot đọc offline của trạm.
- ``submit``: tạo và ghi sổ phiếu trong một giao dịch; ``session_uuid`` của client chống trùng khi phát lại hàng đợi
  (kể cả khi khóa idempotent đã hết hạn).
"""

import frappe
from frappe.utils import cint, getdate

from tracecore.compliance_audit import sessions, templates

DOCTYPE = "Audit Session"
SAVEPOINT = "tc_audit_submit"
PROFESSIONS = ("Doctor", "Nurse", "Midwife", "Technician", "Orderly", "Student", "Other")
ITEM_FIELDS = [
	"item_code",
	"section",
	"question",
	"answer_type",
	"options",
	"weight",
	"is_critical",
	"guidance",
]


def active_templates(on=None, methods=templates.SCORED):
	"""Phiên bản đã duyệt mới nhất có hiệu lực của mỗi mã, theo phương pháp chấm."""
	rows = frappe.get_all(
		templates.DOCTYPE,
		filters={
			"docstatus": 1,
			"effective_from": ["<=", getdate(on)],
			"scoring_method": ["in", list(methods)],
		},
		fields=[
			"name",
			"template_code",
			"title",
			"audit_type",
			"scoring_method",
			"bundle_type",
			"version_no",
			"pass_threshold",
			"min_sample",
			"legal_ref",
		],
		order_by="template_code asc, version_no desc",
	)
	latest = {}
	for row in rows:
		latest.setdefault(row.template_code, row)
	result = list(latest.values())
	for row in result:
		row["items"] = frappe.get_all(
			templates.ITEM_DOCTYPE,
			filters={"parent": row.name, "parenttype": templates.DOCTYPE},
			fields=ITEM_FIELDS,
			order_by="idx asc",
		)
	return result


def departments(user=None):
	allowed = sessions.allowed_departments(user)
	filters = {"disabled": 0, "is_group": 0}
	if allowed is None:
		filters["tc_is_ward"] = 1
	else:
		filters["name"] = ["in", allowed or [""]]
	return frappe.get_all(
		"Department", filters=filters, fields=["name", "department_name"], order_by="department_name asc"
	)


def context(observer, on=None):
	return {
		"templates": active_templates(on),
		"departments": departments(),
		"observer": observer,
		"observer_name": frappe.db.get_value("Employee", observer, "employee_name") if observer else None,
		"professions": list(PROFESSIONS),
	}


def _result(name):
	row = frappe.db.get_value(
		DOCTYPE,
		name,
		["name", "score_pct", "result", "critical_failed", "sample_flag", "sample_n"],
		as_dict=True,
	)
	row.critical_failed = cint(row.critical_failed)
	return row


def submit(observer, values, on, replay=False):
	"""Tạo + ghi sổ phiếu; trả {name, score_pct, result, critical_failed, sample_flag, sample_n}."""
	uuid = values.get("session_uuid")
	if uuid:
		existing = frappe.db.get_value(DOCTYPE, {"client_uuid": uuid, "docstatus": 1}, "name")
		if existing:
			return _result(existing)
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"audit_template": values.get("audit_template"),
			"department": values.get("department"),
			"location": values.get("location"),
			"mode": values.get("mode") or "Announced",
			"subject_role": values.get("subject_role"),
			"subject_employee": values.get("subject_employee") or None,
			"supplier": values.get("supplier") or None,
			"observer": observer,
			"audit_date": getdate(on),
			"started_at": values.get("started_at"),
			"client_uuid": uuid,
			"answers": [
				{key: row.get(key) for key in ("item_code", "answer", "value", "photo", "note")}
				for row in frappe.parse_json(values.get("answers") or "[]")
			],
		}
	)
	doc.flags.tc_replay = bool(replay)
	frappe.db.savepoint(SAVEPOINT)
	try:
		doc.insert()
		doc.submit()
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise
	return _result(doc.name)
