"""Tổng hợp tuân thủ theo mẫu x khoa từ phiếu đã ghi sổ (FEAT-060; FR-M12-11, FR-M12-14, BRU-RPT-001).

Nguồn duy nhất cho Script Report "Compliance by Department", màn SCR-53 và hàm chỉ số M9 (``indicators``): chỉ phiếu
``docstatus = 1`` trong kỳ (FR-M12-14.1). Tỷ lệ = phiếu Đạt / phiếu có kết quả; n = số phiếu có kết quả. n = 0 → "Không
tính" (không hiện 0); n < ``min_sample`` của mẫu → "Chưa đủ mẫu". R08/R12 chỉ nhận dòng khoa có User Permission.
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Avg, Count, Sum
from frappe.utils import cint, flt, getdate
from pypika.terms import Case

from tracecore.compliance_audit import sessions, templates

DOCTYPE = "Audit Session"
NOT_CALCULATED, INSUFFICIENT = "Not calculated", "Insufficient sample"


def _decimal(value):
	text = f"{flt(value, 1):g}"
	if (frappe.db.get_default("number_format") or "").endswith(",##"):
		text = text.replace(".", ",")
	return text


def rate_label(row):
	"""Nhãn tỷ lệ cho màn/báo cáo: "75 % (n = 8, chưa đủ cỡ mẫu)" | "75 % (n = 30)" | "Không tính"."""
	if row.get("pass_rate") is None:
		return _(NOT_CALCULATED)
	if row.get("sample_note") == INSUFFICIENT:
		return _("{0} % (n = {1}, insufficient sample)").format(_decimal(row["pass_rate"]), row["scored"])
	return _("{0} % (n = {1})").format(_decimal(row["pass_rate"]), row["scored"])


def _min_samples(codes):
	result = {}
	for code in codes:
		latest = frappe.get_all(
			templates.DOCTYPE,
			filters={"template_code": code, "docstatus": 1},
			fields=["min_sample", "title"],
			order_by="version_no desc",
			limit=1,
		)
		result[code] = latest[0] if latest else frappe._dict(min_sample=0, title=code)
	return result


def aggregate(filters):
	"""Dòng tổng hợp theo (mã mẫu, khoa). ``filters``: from_date, to_date, audit_type, template_code, department,
	profession."""
	filters = frappe._dict(filters or {})
	session = frappe.qb.DocType(DOCTYPE)
	query = (
		frappe.qb.from_(session)
		.where(session.docstatus == 1)
		.where(session.audit_date[getdate(filters.from_date) : getdate(filters.to_date)])
		.groupby(session.template_code, session.department)
		.select(
			session.template_code,
			session.department,
			Count(session.name).as_("sessions"),
			Sum(Case().when(session.result == "Pass", 1).else_(0)).as_("passed"),
			Sum(Case().when(session.result.isin(["Pass", "Fail"]), 1).else_(0)).as_("scored"),
			Sum(session.critical_failed).as_("critical_failed"),
			Avg(session.score_pct).as_("avg_score"),
		)
	)
	for field in ("audit_type", "template_code", "department"):
		if filters.get(field):
			query = query.where(session[field] == filters[field])
	if filters.profession:
		query = query.where(session.subject_role == filters.profession)
	allowed = sessions.allowed_departments()
	if allowed is not None:
		query = query.where(session.department.isin(allowed or [""]))
	rows = [frappe._dict(row) for row in query.run(as_dict=True)]
	if not rows and filters.department and filters.template_code:
		if allowed is None or filters.department in allowed:
			rows = [
				frappe._dict(
					template_code=filters.template_code,
					department=filters.department,
					sessions=0,
					passed=0,
					scored=0,
					critical_failed=0,
					avg_score=None,
				)
			]
	meta = _min_samples({row.template_code for row in rows})
	for row in rows:
		row.passed, row.scored = cint(row.passed), cint(row.scored)
		row.critical_failed = cint(row.critical_failed)
		row.avg_score = None if row.avg_score is None else flt(row.avg_score, 1)
		row.template_title = meta[row.template_code].title
		row.min_sample = cint(meta[row.template_code].min_sample)
		if not row.scored:
			row.pass_rate, row.sample_note = None, NOT_CALCULATED
		else:
			row.pass_rate = flt(row.passed * 100 / row.scored, 1)
			row.sample_note = INSUFFICIENT if row.scored < row.min_sample else ""
	rows.sort(key=lambda row: (row.template_code, row.department))
	return rows
