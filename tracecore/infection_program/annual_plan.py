"""Kế hoạch KSNK năm (FEAT-058; FR-M11-04..06; BRU-ICP-004; UC-41; A-133 Q1-Q3).

- Mỗi năm tối đa một kế hoạch chưa hủy, trừ bản sửa đổi (``amended_from``) của chính kế hoạch đó (FR-M11-04.2).
- Chỉ Chủ tịch Hội đồng (R13) ghi sổ = phê duyệt (FR-M11-04.1); ghi sổ bản sửa đổi thì tự Hủy bản gốc (A-133 Q1).
- Sau ghi sổ nội dung khóa hẳn; chỉ trường tiến độ của hoạt động và nhận xét tổng kết sửa được (FR-M11-04.3, Q2).
- Tổng kết năm đọc ``IC Indicator Value`` (M9) qua DocType, không import module khác (FR-M11-06.1, Q3).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime, today

from tracecore.infection_program import reminders

DOCTYPE = "IC Annual Plan"
VALUE_DOCTYPE = "IC Indicator Value"
APPROVER_ROLE = "TC R13"
EDITOR_ROLE = "TC R01"
SCREEN_SLUG = "ke-hoach"
COMPLETED = "Completed"
PROGRESS_STATUSES = ("Planned", "In Progress", COMPLETED)
CONTENT_FIELDS = ("year", "objectives")
CHILD_CONTENT = {
	"indicators": ("indicator", "baseline", "target"),
	"activities": ("activity", "measure_group", "responsible", "department", "due_date", "budget_vnd"),
}
# cùng hệ số với engine M9 (`admin_reports.indicator.SCALE`); M11 không import M9 (architecture §5.2)
SCALE = {"Percentage": 100, "Rate per 1000": 1000}
NOT_CALCULATED = "Not calculated"
SMALL_SAMPLE = "Insufficient sample"


# --- validate / ghi sổ -------------------------------------------------------------------------------------------


def _others_same_year(doc):
	names = frappe.get_all(
		DOCTYPE,
		filters={"year": cint(doc.year), "docstatus": ["<", 2], "name": ["!=", doc.name or ""]},
		pluck="name",
		order_by="creation asc",
	)
	return [name for name in names if name != doc.amended_from]


def check_amended_from(doc):
	"""Bản sửa đổi trỏ tới kế hoạch đã ghi sổ hoặc đã hủy, cùng năm (thay kiểm "bản gốc phải Hủy" của Frappe, Q1)."""
	original = frappe.db.get_value(DOCTYPE, doc.amended_from, ["docstatus", "year"], as_dict=True)
	if not original or original.docstatus == 0:
		frappe.throw(_("Only an approved plan can be amended."))
	if cint(original.year) != cint(doc.year):
		frappe.throw(
			_("An amendment must keep the year {0} of plan {1}.").format(original.year, doc.amended_from)
		)


def validate(doc):
	year = cint(doc.year)
	if year < 2000 or year > 2100:
		frappe.throw(_("Plan year {0} is not valid.").format(doc.year))
	if doc.amended_from:
		check_amended_from(doc)
	others = _others_same_year(doc)
	if others:
		frappe.throw(
			_(
				"Year {0} already has plan {1}. Create an amendment (Amend) of that plan instead of a new plan."
			).format(year, ", ".join(others))
		)
	seen = set()
	for row in doc.indicators:
		if row.indicator in seen:
			frappe.throw(_("Indicator {0} is listed more than once.").format(row.indicator))
		seen.add(row.indicator)
	_sync_completion(doc)
	doc.total_budget_vnd = sum(flt(row.budget_vnd) for row in doc.activities)


def _sync_completion(doc):
	for row in doc.activities:
		if row.status == COMPLETED:
			row.completed_on = row.completed_on or today()
		else:
			row.completed_on = None


def _norm(value):
	if value is None or value == "":
		return ""
	if isinstance(value, int | float):
		return flt(value)
	if hasattr(value, "isoformat"):
		return value.isoformat()
	return str(value)


def _changed_content(doc, old):
	changed = [field for field in CONTENT_FIELDS if _norm(doc.get(field)) != _norm(old.get(field))]
	for table, fields in CHILD_CONTENT.items():
		before = {row.name: row for row in old.get(table)}
		rows = doc.get(table)
		if len(rows) != len(before):
			changed.append(table)
			continue
		for row in rows:
			prev = before.get(row.name)
			if not prev or any(_norm(row.get(field)) != _norm(prev.get(field)) for field in fields):
				changed.append(table)
				break
	return changed


def guard_after_submit(doc):
	"""FR-M11-04.3: kế hoạch đã duyệt không sửa nội dung; báo hướng dẫn Amend trước khi Frappe báo lỗi chung."""
	old = doc.get_doc_before_save()
	if old and _changed_content(doc, old):
		frappe.throw(
			_(
				"Plan {0} is approved and its content cannot be changed. Create an amendment (Amend) and have the committee chair approve it again."
			).format(doc.name),
			title=_("Approved plan locked"),
		)
	_sync_completion(doc)


def before_submit(doc):
	if APPROVER_ROLE not in frappe.get_roles():
		frappe.throw(
			_("Only the chair of the infection control committee (R13) can approve the annual plan."),
			frappe.PermissionError,
		)
	doc.approved_by = frappe.session.user
	doc.approved_by_name = frappe.db.get_value("User", frappe.session.user, "full_name")
	doc.approved_on = now_datetime()


def on_submit(doc):
	"""Ghi sổ bản sửa đổi → Hủy bản gốc còn hiệu lực (Q1): năm luôn có tối đa một kế hoạch đã ghi sổ."""
	if not doc.amended_from:
		return
	original = frappe.get_doc(DOCTYPE, doc.amended_from)
	if original.docstatus != 1:
		return
	original.flags.ignore_permissions = True
	original.flags.ignore_links = True  # bản sửa đổi trỏ về bản gốc qua amended_from
	original.cancel()


# --- duyệt, Amend và tiến độ (RPC gọi) ---------------------------------------------------------------------------


def approve(name):
	"""R13 ghi sổ kế hoạch Nháp = phê duyệt (FR-M11-04, FR-M11-04.1).

	Frappe đòi quyền ghi khi ghi sổ; ma trận D6 cho R13 ghi sổ (S) nhưng không sửa (W), nên quyền thật kiểm ở đây
	(Role R13 + đọc được kế hoạch) rồi ghi sổ bỏ qua DocPerm write.
	"""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	if APPROVER_ROLE not in frappe.get_roles():
		frappe.throw(
			_("Only the chair of the infection control committee (R13) can approve the annual plan."),
			frappe.PermissionError,
		)
	if doc.docstatus != 0:
		frappe.throw(_("Plan {0} is not a draft.").format(name))
	doc.flags.ignore_permissions = True
	doc.submit()
	return doc


def make_amendment(name):
	"""R01 lập bản sửa đổi Nháp khi bản gốc vẫn hiệu lực (Q1); đã có bản Nháp thì trả bản đó."""
	original = frappe.get_doc(DOCTYPE, name)
	if original.docstatus != 1:
		frappe.throw(_("Only an approved plan can be amended."))
	if not frappe.has_permission(DOCTYPE, "amend", original):
		frappe.throw(_("You are not allowed to amend the annual plan."), frappe.PermissionError)
	pending = frappe.get_all(DOCTYPE, filters={"amended_from": name, "docstatus": 0}, pluck="name")
	if pending:
		return pending[0]
	amendment = frappe.copy_doc(original, ignore_no_copy=False)  # bỏ người duyệt, cờ nhắc (no_copy)
	amendment.amended_from = name
	amendment.docstatus = 0
	for row in amendment.get_all_children():
		row.docstatus = 0
	amendment.insert()
	return amendment.name


def can_update_activity(row, user=None):
	user = user or frappe.session.user
	if EDITOR_ROLE in frappe.get_roles(user):
		return True
	return bool(row.responsible) and frappe.db.get_value("Employee", row.responsible, "user_id") == user


def update_activity(plan, row_name, status, evidence=None):
	"""Người chủ trì hoặc R01 cập nhật tiến độ hoạt động của kế hoạch đã duyệt (UC-41 bước 4, Q2)."""
	doc = frappe.get_doc(DOCTYPE, plan)
	if doc.docstatus != 1:
		frappe.throw(_("Progress is updated on the approved plan."))
	row = next((item for item in doc.activities if item.name == row_name), None)
	if not row:
		frappe.throw(_("Activity {0} is not in plan {1}.").format(row_name, plan))
	if not can_update_activity(row):
		frappe.throw(
			_("Only the responsible person or the head of infection control (R01) can update this activity."),
			frappe.PermissionError,
		)
	if status not in PROGRESS_STATUSES:
		frappe.throw(_("Activity status {0} is not valid.").format(status))
	row.status = status
	if evidence is not None:
		row.evidence = (evidence or "").strip()
	doc.flags.ignore_permissions = True
	doc.save()
	return doc


# --- tổng kết năm ------------------------------------------------------------------------------------------------


def annual_value(kind, rows, min_sample=0):
	"""(giá trị, ghi chú) của năm: cộng dồn tử/mẫu số các tháng rồi tính lại theo loại chỉ số (Q3)."""
	numerator = sum(flt(row.numerator) for row in rows)
	denominator = sum(flt(row.denominator) for row in rows)
	sample = sum(cint(row.sample_size) for row in rows)
	if not rows:
		return None, NOT_CALCULATED
	if kind in SCALE:
		if not denominator:
			return None, NOT_CALCULATED
		value = numerator / denominator * SCALE[kind]
	else:
		value = numerator
	note = SMALL_SAMPLE if min_sample and sample < cint(min_sample) else ""
	return flt(value, 4), note


def judge(value, note, target, direction):
	"""Met / Not met / Not calculated / Insufficient sample / "" (chưa có hướng mục tiêu)."""
	if note:
		return note
	if value is None or not direction:
		return ""
	met = value >= flt(target) if direction == "Higher is better" else value <= flt(target)
	return "Met" if met else "Not met"


def _latest(rows):
	if not rows:
		return None, None
	row = max(rows, key=lambda item: item.period)
	value = None if row.sample_note == NOT_CALCULATED else flt(row.value)
	return value, row.period


def year_summary(name):
	"""Số liệu tổng kết năm của một kế hoạch: chỉ số so mục tiêu, tiến độ hoạt động, nhận xét, cờ "Tạm"."""
	doc = frappe.get_doc(DOCTYPE, name)
	year = cint(doc.year)
	codes = [row.indicator for row in doc.indicators] or [""]
	catalog = {
		row.name: row
		for row in frappe.get_all(
			"IC Indicator",
			filters={"name": ["in", codes]},
			fields=["name", "indicator_name", "kind", "target_direction", "min_sample"],
		)
	}
	values = frappe.get_all(
		VALUE_DOCTYPE,
		filters={
			"indicator": ["in", codes],
			"period": ["like", f"{year}-%"],
			"department": ["is", "not set"],
		},
		fields=[
			"indicator",
			"period",
			"numerator",
			"denominator",
			"sample_size",
			"value",
			"sample_note",
			"locked",
		],
	)
	by_indicator = {}
	for row in values:
		by_indicator.setdefault(row.indicator, []).append(row)
	indicators = []
	for row in doc.indicators:
		meta = catalog.get(row.indicator) or frappe._dict()
		rows = by_indicator.get(row.indicator, [])
		value, note = annual_value(meta.kind, rows, meta.min_sample)
		status = judge(value, note, row.target, meta.target_direction)
		latest, latest_period = _latest(rows)
		indicators.append(
			{
				"indicator": row.indicator,
				"indicator_name": row.indicator_name or meta.indicator_name or row.indicator,
				"kind": meta.kind,
				"direction": meta.target_direction or "",
				"baseline": row.baseline,
				"target": row.target,
				"value": value,
				"status": status,
				"status_label": _(status) if status else "",
				"latest": latest,
				"latest_period": latest_period,
				"latest_status": judge(latest, "", row.target, meta.target_direction)
				if latest is not None
				else "",
			}
		)
	completed = sum(1 for row in doc.activities if row.status == COMPLETED)
	provisional = getdate(today()).year <= year or any(not row.locked for row in values)
	return {
		"name": doc.name,
		"year": year,
		"docstatus": doc.docstatus,
		"provisional": provisional,
		"indicators": indicators,
		"activities_total": len(doc.activities),
		"activities_completed": completed,
		"total_budget_vnd": flt(doc.total_budget_vnd),
		"summary": doc.summary or "",
		"objectives": doc.objectives or "",
		"approved_by": doc.approved_by_name or doc.approved_by or "",
		"approved_on": doc.approved_on,
	}


# --- badge -------------------------------------------------------------------------------------------------------


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: hoạt động quá hạn của kế hoạch đã duyệt năm nay + văn bản cần rà soát."""
	return {SCREEN_SLUG: reminders.attention_count()}
