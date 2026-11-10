"""Tự đánh giá chất lượng KSNK hằng năm (FEAT-072; FR-M11-13, FR-M11-13.1; UC-42 bước 6; ADR-015; A-149).

Phiếu là `Audit Session` của mẫu M12 loại "Quality Self-Assessment" (đã duyệt — BRU-AUD-001 do engine M12 kiểm). Kết quả
của một năm = phiếu đã ghi sổ mới nhất có ``audit_date`` trong năm. So hai năm liền theo ``item_code`` của bản chụp mục.
Đọc phiếu qua ``frappe.get_all`` theo tên DocType, không import M12.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

SESSION, ANSWER, TEMPLATE = "Audit Session", "Audit Answer", "Audit Template"
AUDIT_TYPE = "Quality Self-Assessment"


def latest(year):
	"""Phiếu tự đánh giá đã ghi sổ mới nhất của năm, hoặc None."""
	year = cint(year)
	rows = frappe.get_all(
		SESSION,
		filters={
			"audit_type": AUDIT_TYPE,
			"docstatus": 1,
			"audit_date": ["between", [f"{year}-01-01", f"{year}-12-31"]],
		},
		fields=[
			"name",
			"audit_date",
			"score_pct",
			"result",
			"template_code",
			"audit_template",
			"department_name",
		],
		order_by="audit_date desc, creation desc",
		limit=1,
	)
	if not rows:
		return None
	row = rows[0]
	row["score_pct"] = None if row.score_pct in (None, "") else flt(row.score_pct, 1)
	row["result_label"] = _(row.result) if row.result else ""
	return row


def _answers(name):
	if not name:
		return []
	return frappe.get_all(
		ANSWER,
		filters={"parent": name, "parenttype": SESSION},
		fields=["item_code", "section", "question", "answer"],
		order_by="idx asc",
	)


def _label(answer):
	return _(answer) if answer else ""


def compare(year):
	"""Năm ``year`` và năm trước cạnh nhau theo từng mục (FR-M11-13.1)."""
	year = cint(year)
	current, previous = latest(year), latest(year - 1)
	current_rows = _answers(current and current.name)
	before = {row.item_code: row.answer or "" for row in _answers(previous and previous.name)}
	now = {row.item_code: row.answer or "" for row in current_rows}
	# mục của năm nay theo thứ tự mẫu, rồi mục chỉ có ở năm trước (mẫu đã đổi phiên bản)
	ordered = current_rows + [row for row in _answers(previous and previous.name) if row.item_code not in now]
	result = []
	for row in ordered:
		cur, prev = now.get(row.item_code, ""), before.get(row.item_code, "")
		result.append(
			{
				"item_code": row.item_code,
				"section": row.section or "",
				"question": row.question or "",
				"current": cur,
				"previous": prev,
				"current_label": _label(cur),
				"previous_label": _label(prev),
				"changed": bool(current and previous and cur != prev),
			}
		)
	return {
		"year": year,
		"previous_year": year - 1,
		"current": current,
		"previous": previous,
		"both": bool(current and previous),
		"items": result,
	}


def active_template(on=None):
	"""Phiên bản đã duyệt mới nhất có hiệu lực của mẫu tự đánh giá (để mở phiếu mới), hoặc None."""
	rows = frappe.get_all(
		TEMPLATE,
		filters={"audit_type": AUDIT_TYPE, "docstatus": 1, "effective_from": ["<=", getdate(on or today())]},
		order_by="effective_from desc, version_no desc",
		limit=1,
		pluck="name",
	)
	return rows[0] if rows else None
