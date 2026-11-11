"""Tự đánh giá năm theo QĐ 38 (FEAT-065; FR-M9-29, FR-M9-29.1; UC-57 bước 7; A-145 Q1, D8).

- Danh mục chỉ tiêu: `IC QD38 Criterion` (seed ``self_assessment_seed``; R01 sửa, không mã hóa cứng tiêu chí).
- R01 lập bản Nháp của năm (`TDG-{year}`): mỗi chỉ tiêu đang dùng một dòng. Dòng **Tự động** lấy kết quả từ hàm đăng ký
  qua hook ``tracecore_ic_self_checks`` (``{check_method: fn(year) -> {status, source_ref}}``) hoặc từ `IC Indicator Value`
  đã khóa của năm khi chỉ tiêu có Link ``indicator``. Dòng chưa tính được để "Chưa đánh giá" cho R01 đánh giá tay.
- R01 sửa một dòng → nguồn **Thủ công** (FR-M9-29.1); làm mới không ghi đè dòng Thủ công đã đánh giá.
- R01 ghi sổ thì khóa bản; R10, R11, R13 chỉ đọc. M9 không import module nghiệp vụ.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from tracecore.core import extension
from tracecore.core.print_tokens import token_values

DOCTYPE = "IC Self Assessment"
ITEM = "IC Self Assessment Item"
CRITERION = "IC QD38 Criterion"
PRINT_FORMAT = "TC IC Self Assessment"
HOOK = "tracecore_ic_self_checks"
AUTO, MANUAL = "Auto", "Manual"
MET, NOT_MET, NEEDS, NOT_ASSESSED = "Met", "Not met", "Needs confirmation", "Not assessed"
STATUSES = (NOT_ASSESSED, MET, NOT_MET, NEEDS)
MANAGE_ROLE = "TC R01"
SCALE = {"Percentage": 100, "Rate per 1000": 1000}
MIN_YEAR, MAX_YEAR = 2000, 2100


def registry():
	"""Gộp hàm tự kiểm của mọi module; một khóa chỉ một module đăng ký."""
	merged = {}
	for result in extension.run(HOOK):
		for key, fn in (result or {}).items():
			if key in merged:
				raise ValueError(f"IC self-assessment check {key} is registered twice")
			merged[key] = frappe.get_attr(fn) if isinstance(fn, str) else fn
	return merged


def validate(doc):
	"""``IC Self Assessment.validate``: năm hợp lệ, mỗi chỉ tiêu một dòng, trạng thái/nguồn trong danh sách."""
	year = cint(doc.year)
	if not MIN_YEAR <= year <= MAX_YEAR:
		frappe.throw(_("Year must be between {0} and {1}.").format(MIN_YEAR, MAX_YEAR))
	seen = set()
	for row in doc.items:
		if row.criterion in seen:
			frappe.throw(_("Criterion {0} appears twice.").format(row.criterion))
		seen.add(row.criterion)
		if row.status not in STATUSES:
			row.status = NOT_ASSESSED
		if row.source not in (AUTO, MANUAL):
			row.source = MANUAL


def _require_manager():
	if frappe.session.user != "Administrator" and MANAGE_ROLE not in frappe.get_roles():
		frappe.throw(
			_("Only the head of infection control (R01) can prepare the self-assessment."),
			frappe.PermissionError,
		)


def _criteria():
	return frappe.get_all(
		CRITERION,
		filters={"is_active": 1},
		fields=["name", "criterion", "source_hint", "check_method", "indicator"],
		order_by="sort_order asc, name asc",
	)


# --- dòng tự động ------------------------------------------------------------------------------------------------


def _indicator_check(code, year):
	"""Chỉ tiêu gắn chỉ số: cộng tử/mẫu số các kỳ đã khóa của năm (toàn viện), so mục tiêu kế hoạch/quốc gia."""
	ind = frappe.db.get_value(
		"IC Indicator", code, ["kind", "national_target", "target_direction"], as_dict=True
	)
	if not ind or not ind.target_direction:
		return None
	rows = frappe.get_all(
		"IC Indicator Value",
		filters={
			"indicator": code,
			"period": ("like", f"{cint(year):04d}-%"),
			"department": ("is", "not set"),
			"locked": 1,
		},
		fields=["numerator", "denominator"],
	)
	if not rows:
		return None
	numerator = sum(flt(row.numerator) for row in rows)
	denominator = sum(flt(row.denominator) for row in rows)
	if ind.kind in SCALE:
		if not denominator:
			return None
		value = numerator / denominator * SCALE[ind.kind]
	else:
		value = numerator
	plan_target = frappe.db.sql(
		"""select c.target from `tabIC Plan Indicator` c join `tabIC Annual Plan` p on p.name = c.parent
		where c.parenttype = 'IC Annual Plan' and p.docstatus = 1 and p.year = %s and c.indicator = %s""",
		(cint(year), code),
	)
	target = flt(plan_target[0][0]) if plan_target and flt(plan_target[0][0]) else flt(ind.national_target)
	met = value >= target if ind.target_direction == "Higher is better" else value <= target
	return {
		"status": MET if met else NOT_MET,
		"source_ref": _("{0}: {1} in {2} locked periods").format(code, flt(value, 1), len(rows)),
	}


def evaluate(criterion, year, checks):
	"""Kết quả tự động của một chỉ tiêu hoặc ``None`` (không tính được → R01 đánh giá tay)."""
	fn = checks.get(criterion.check_method) if criterion.check_method else None
	if fn:
		result = fn(cint(year)) or {}
		if result.get("status") in STATUSES:
			return {"status": result["status"], "source_ref": result.get("source_ref") or ""}
	if criterion.indicator:
		return _indicator_check(criterion.indicator, year)
	return None


def _get(year):
	name = frappe.db.get_value(DOCTYPE, {"year": cint(year)}, "name")
	return frappe.get_doc(DOCTYPE, name) if name else None


def prepare(year):
	"""R01 lập/làm mới bản Nháp của năm: thêm chỉ tiêu còn thiếu, tính lại dòng Tự động và dòng chưa đánh giá."""
	_require_manager()
	year = cint(year)
	doc = _get(year)
	if doc and doc.docstatus != 0:
		frappe.throw(_("The self-assessment of {0} is already submitted.").format(year))
	if not doc:
		doc = frappe.get_doc({"doctype": DOCTYPE, "year": year, "items": []})
	rows = {row.criterion: row for row in doc.items}
	checks = registry()
	for criterion in _criteria():
		row = rows.get(criterion.name)
		if not row:
			row = doc.append("items", {"criterion": criterion.name, "source": MANUAL, "status": NOT_ASSESSED})
		row.criterion_text = criterion.criterion
		row.source_hint = criterion.source_hint
		if row.source == MANUAL and row.status != NOT_ASSESSED:
			continue  # R01 đã đánh giá tay: giữ nguyên
		result = evaluate(criterion, year, checks)
		if result:
			row.update({"source": AUTO, **result})
		else:
			row.update({"source": MANUAL, "status": NOT_ASSESSED, "source_ref": ""})
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def set_item(year, criterion, status, evidence=None, note=None):
	"""R01 đánh giá tay một chỉ tiêu → nguồn Thủ công (FR-M9-29.1)."""
	_require_manager()
	if status not in STATUSES:
		frappe.throw(_("Status {0} is not valid.").format(status))
	doc = _get(year)
	if not doc:
		frappe.throw(_("Prepare the self-assessment of {0} first.").format(year))
	if doc.docstatus != 0:
		frappe.throw(_("The self-assessment of {0} is already submitted.").format(year))
	row = next((row for row in doc.items if row.criterion == criterion), None)
	if not row:
		frappe.throw(_("Criterion {0} is not in the self-assessment.").format(criterion))
	row.update({"status": status, "source": MANUAL, "evidence": evidence or "", "note": note or ""})
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def submit(year):
	"""R01 ghi sổ bản tự đánh giá (khóa); dòng "Cần R01 xác nhận" phải được xác nhận trước."""
	_require_manager()
	doc = _get(year)
	if not doc:
		frappe.throw(_("Prepare the self-assessment of {0} first.").format(year))
	pending = [row.criterion for row in doc.items if row.status == NEEDS]
	if pending:
		frappe.throw(_("Confirm these criteria first: {0}").format(", ".join(pending)))
	doc.assessed_on = getdate(today())
	doc.flags.ignore_permissions = True
	doc.submit()
	return doc.name


def view(year):
	"""Dữ liệu khối tự đánh giá của SCR-66 (đọc theo DocPerm: R01, R10, R11, R13)."""
	if not frappe.has_permission(DOCTYPE, "read"):
		frappe.throw(_("You are not allowed to read the self-assessment."), frappe.PermissionError)
	year = cint(year) or getdate(today()).year
	doc = _get(year)
	can_manage = frappe.session.user == "Administrator" or MANAGE_ROLE in frappe.get_roles()
	if not doc:
		return {
			"year": year,
			"name": None,
			"docstatus": None,
			"rows": [],
			"can_manage": can_manage,
			"editable": False,
		}
	return {
		"year": year,
		"name": doc.name,
		"docstatus": doc.docstatus,
		"assessed_on": doc.assessed_on,
		"can_manage": can_manage,
		"editable": can_manage and doc.docstatus == 0,
		"rows": [
			{
				"criterion": row.criterion,
				"criterion_text": row.criterion_text,
				"source_hint": row.source_hint or "",
				"source": row.source,
				"status": row.status,
				"source_ref": row.source_ref or "",
				"evidence": row.evidence or "",
				"note": row.note or "",
			}
			for row in doc.items
		],
	}


def tc_ic_self_assessment_context(name: str) -> dict:
	"""Ngữ cảnh Print Format "TC IC Self Assessment"."""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	return {
		"tc": token_values(),
		"name": doc.name,
		"year": cint(doc.year),
		"draft": doc.docstatus == 0,
		"assessed_on": getdate(doc.assessed_on).strftime("%d/%m/%Y") if doc.assessed_on else "",
		"remarks": doc.remarks or "",
		"rows": [
			{
				"criterion": row.criterion_text or row.criterion,
				"source_hint": row.source_hint or "",
				"source": _(row.source),
				"status": _(row.status),
				"source_ref": row.source_ref or "",
				"evidence": row.evidence or "",
			}
			for row in doc.items
		],
	}
