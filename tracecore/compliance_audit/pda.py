"""Phiếu giám sát trên PDA/Page `station` (FEAT-060; SCR-52, FR-M12-04, NFR-AVAIL-05, ADR-003).

- ``context``: mẫu đã duyệt đang hiệu lực (chấm theo mục: Điểm %, Tất cả-hoặc-không; vệ sinh tay theo cơ hội là
  SCR-51 của FEAT-061) kèm mục, và khoa người dùng được làm phiếu; cũng là snapshot đọc offline của trạm.
- ``submit``: tạo và ghi sổ phiếu trong một giao dịch; ``session_uuid`` của client chống trùng khi phát lại hàng đợi
  (kể cả khi khóa idempotent đã hết hạn).
"""

import frappe
from frappe.utils import cint, getdate

from tracecore.compliance_audit import (
	hand_hygiene,
	prevalence,  # FEAT-072
	sessions,
	templates,
)
from tracecore.core.errors import Block, BlockedError

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
	# FEAT-072 (A-149 Q1): phiếu cắt ngang cần mã BN, chỉ ghi trên WEB SCR-58 — không đưa lên PDA
	survey = set(prevalence.template_codes())
	result = [row for row in result if row.template_code not in survey]
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


def opportunity_templates(on=None):
	"""Mẫu "Theo cơ hội" (SCR-51) kèm thời điểm sinh từ mục của mẫu (FEAT-061, D2)."""
	rows = active_templates(on, (templates.BY_OPPORTUNITY,))
	for row in rows:
		row["moments"] = [
			{"moment": hand_hygiene.moment_of(item.item_code), "label": item.question}
			for item in row["items"]
			if hand_hygiene.moment_of(item.item_code)
		] or [{"moment": str(number), "label": ""} for number in range(1, 6)]  # mẫu không khai thời điểm: 1-5
	return rows


def open_episodes(on=None):
	"""FEAT-062 (FR-M12-07, A-141 e): đợt thiết bị đang mở của các khoa được làm phiếu, mã BN che — chọn khi chấm gói.

	Đọc `Device Episode` (M13) qua Link, không import M13; xếp theo khoa rồi ngày đặt."""
	names = [row.name for row in departments()]
	if not names:
		return []
	return frappe.get_all(
		"Device Episode",
		filters={"status": "Open", "department": ["in", names], "inserted_on": ["<=", getdate(on)]},
		fields=["name", "department", "device_type", "patient_code_masked", "inserted_on"],
		order_by="department asc, inserted_on asc, name asc",
	)


def environment_zones():
	"""FEAT-070 (FR-M15-02, A-148 e): vùng vệ sinh đang dùng của các khoa được làm phiếu — chọn khi chấm phiếu VSMT/hạ
	tầng. Đọc `Environment Zone` (M15) qua Link, không import M15."""
	names = [row.name for row in departments()]
	if not names:
		return []
	return frappe.get_all(
		"Environment Zone",
		filters={"disabled": 0, "department": ["in", names]},
		fields=["name", "area_name", "department", "risk_level", "awaiting_resample"],
		order_by="department asc, area_name asc",
	)


def caterers():
	"""FEAT-073 (FR-M17-01, A-151): đơn vị suất ăn thuê ngoài (Supplier `tc_ic_service_type` = Catering) — chọn khi chấm
	phiếu An toàn thực phẩm; bếp ăn bệnh viện tự vận hành để trống (UC-56 A1)."""
	return frappe.get_all(
		"Supplier",
		filters={"disabled": 0, "tc_ic_service_type": "Catering"},
		fields=["name", "supplier_name"],
		order_by="supplier_name asc",
	)


def context(observer, on=None):
	return {
		"episodes": open_episodes(on),  # FEAT-062: đợt thiết bị đang mở cho phiếu gói dự phòng
		"zones": environment_zones(),  # FEAT-070: vùng vệ sinh cho phiếu VSMT/hạ tầng
		"caterers": caterers(),  # FEAT-073: đơn vị suất ăn cho phiếu ATTP
		"templates": active_templates(on),
		"opportunity_templates": opportunity_templates(on),  # FEAT-061 (SCR-51)
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


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _own_draft(name, observer):
	"""Phiếu Nháp của chính người giám sát (người khác không ghi sổ hộ)."""
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.observer != observer:
		raise _blocked(
			"AUDIT_NOT_ALLOWED",
			frappe._("Not your audit"),
			frappe._("This audit was started by another observer."),
			frappe._("Start your own audit."),
		)
	return doc


def _post_draft(name, observer, replay):
	doc = _own_draft(name, observer)
	doc.flags.tc_replay = bool(replay)
	frappe.db.savepoint(SAVEPOINT)
	try:
		doc.submit()
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise
	return _result(doc.name)


def _opportunity_row(item):
	return {
		"subject_role": item.get("subject_role"),
		"subject_employee": item.get("subject_employee") or None,
		"moment": item.get("moment"),
		"action": item.get("action"),
		"technique_ok": 1 if item.get("technique_ok") else 0,
		"glove_instead": 1 if item.get("glove_instead") else 0,
		"client_uuid": item.get("uuid"),
	}


def _progress(doc):
	stats = hand_hygiene.stats(doc.opportunities)
	return {
		"name": doc.name,
		"opportunities": stats.total,
		"actioned": stats.actioned,
		"rate": stats.rate,
		"technique_rate": stats.technique_rate,
	}


def record_opportunity(observer, values, on, replay=False):
	"""Ghi một cơ hội vệ sinh tay vào phiếu Nháp (SCR-51; FR-M12-04, BRU-AUD-002/004).

	Lần đầu của ``session_uuid`` tạo phiếu Nháp; mỗi lần sau thêm đúng một dòng, khử trùng theo UUID của cơ hội
	(``Hand Hygiene Opportunity.client_uuid``) nên phát lại offline sau khi khóa idempotent hết hạn vẫn không trùng.
	Trả ``{name, opportunities, actioned, rate, technique_rate}`` (tỷ lệ tạm tính).
	"""
	uuid = values.get("session_uuid")
	if not uuid:
		raise hand_hygiene.invalid(
			frappe._("The audit has no client ID."), frappe._("Start the audit again from the first screen.")
		)
	if frappe.db.get_value(DOCTYPE, {"client_uuid": uuid, "docstatus": 1}, "name"):
		raise _blocked(
			"AUDIT_SESSION_POSTED",
			frappe._("Audit already posted"),
			frappe._("This audit was posted; opportunities cannot be added."),
			frappe._("Start a new audit."),
		)
	item = frappe.parse_json(values.get("opportunity") or "{}")
	name = frappe.db.get_value(DOCTYPE, {"client_uuid": uuid, "docstatus": 0}, "name")
	frappe.db.savepoint(SAVEPOINT)
	try:
		if name:
			doc = _own_draft(name, observer)
			if item.get("uuid") and any(row.client_uuid == item.get("uuid") for row in doc.opportunities):
				return _progress(doc)
			doc.append("opportunities", _opportunity_row(item))
			doc.flags.tc_replay = bool(replay)
			doc.save()
		else:
			doc = frappe.get_doc(
				{
					"doctype": DOCTYPE,
					"audit_template": values.get("audit_template"),
					"department": values.get("department"),
					"location": values.get("location"),
					"mode": values.get("mode") or "Announced",
					"observer": observer,
					"audit_date": getdate(on),
					"started_at": values.get("started_at"),
					"client_uuid": uuid,
					"opportunities": [_opportunity_row(item)],
				}
			)
			doc.flags.tc_replay = bool(replay)
			doc.insert()
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise
	return _progress(doc)


def submit(observer, values, on, replay=False):
	"""Tạo + ghi sổ phiếu; trả {name, score_pct, result, critical_failed, sample_flag, sample_n}."""
	uuid = values.get("session_uuid")
	if uuid:
		existing = frappe.db.get_value(DOCTYPE, {"client_uuid": uuid, "docstatus": 1}, "name")
		if existing:
			return _result(existing)
		draft = frappe.db.get_value(DOCTYPE, {"client_uuid": uuid, "docstatus": 0}, "name")
		if draft:  # FEAT-061: phiếu vệ sinh tay đã có cơ hội (Nháp) → ghi sổ
			return _post_draft(draft, observer, replay)
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
			"device_episode": values.get("device_episode") or None,  # FEAT-062: phiếu gói dự phòng gắn đợt
			"environment_zone": values.get("environment_zone")
			or None,  # FEAT-070: phiếu VSMT/hạ tầng gắn vùng
			"next_due": values.get("next_due")
			or None,  # FEAT-070: hạn kiểm tra hạ tầng kế tiếp (trống = theo chu kỳ)
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
