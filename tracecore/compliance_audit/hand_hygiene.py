"""Vệ sinh tay theo cơ hội (FEAT-061; ADR-015, FR-M12-05, FR-M12-10, FR-M12-11, BRU-AUD-002, BRU-AUD-004).

Đơn vị đo là **cơ hội** (một thời điểm 1-5 cần vệ sinh tay của một người), không phải người hay phiếu:

- tuân thủ = cơ hội có hành động (Chà tay cồn / Rửa tay xà phòng) / tổng cơ hội;
- đúng kỹ thuật tách riêng = cơ hội có hành động và ``technique_ok`` / cơ hội có hành động (cơ hội "Không thực hiện"
  không vào mẫu số, FR-M12-05.2).

Thời điểm của phiếu sinh từ mục của mẫu: mục ``MOMENT-<n>`` (chữ số cuối là thời điểm), nên mẫu của bệnh viện đổi số
thời điểm không cần sửa code (D10). Tổng hợp chỉ tính phiếu ``docstatus = 1`` (FR-M12-14.1); R08/R12 chỉ thấy khoa mình.
"""

import re

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.utils import flt, get_first_day, get_last_day, getdate
from pypika.terms import Case

from tracecore.compliance_audit import scoring, templates
from tracecore.core.errors import Block, BlockedError

SESSION = "Audit Session"
CHILD = "Hand Hygiene Opportunity"
BY_OPPORTUNITY = templates.BY_OPPORTUNITY
MISSED = "Missed"
MOMENT_ITEM = re.compile(r"(\d)$")
GROUPS = {
	"department": "department",
	"profession": "subject_role",
	"moment": "moment",
	"month": "audit_date",
}
NOT_CALCULATED, INSUFFICIENT = "Not calculated", "Insufficient sample"


def _blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


# --- thời điểm của mẫu --------------------------------------------------------------------------------------------


def moment_of(item_code):
	"""Thời điểm (chữ số cuối của mã mục) hoặc None."""
	match = MOMENT_ITEM.search(item_code or "")
	return match.group(1) if match else None


def moments(template):
	"""Các thời điểm của phiên bản mẫu, theo thứ tự tăng dần."""
	codes = frappe.get_all(
		templates.ITEM_DOCTYPE,
		filters={"parent": template, "parenttype": templates.DOCTYPE},
		pluck="item_code",
	)
	return sorted({moment_of(code) for code in codes} - {None})


# --- thống kê một danh sách cơ hội ----------------------------------------------------------------------------------


def _percent(part, whole):
	return flt(part * 100 / whole, 1) if whole else None


def stats(rows):
	"""``{total, actioned, technique_ok, rate, technique_rate}`` của các dòng cơ hội (``rate`` None khi chưa có cơ hội)."""
	rows = list(rows or ())
	actioned = [row for row in rows if row.action != MISSED]
	technique_ok = [row for row in actioned if row.technique_ok]
	return frappe._dict(
		total=len(rows),
		actioned=len(actioned),
		technique_ok=len(technique_ok),
		rate=_percent(len(actioned), len(rows)),
		technique_rate=_percent(len(technique_ok), len(actioned)),
	)


@scoring.register(BY_OPPORTUNITY)
def by_opportunity(doc, template):
	"""Điểm phiếu = tỷ lệ tuân thủ theo cơ hội; kết quả theo ``pass_threshold`` nếu mẫu đặt (BRU-AUD-002)."""
	rate = stats(doc.opportunities).rate
	if rate is None:
		return None, None, False
	threshold = template.get("pass_threshold")
	if not flt(
		threshold
	):  # trường Percent chưa đặt đọc ra 0: mẫu không đặt ngưỡng thì không kết luận Đạt/Không đạt
		return rate, None, False
	return rate, (scoring.PASS if rate >= flt(threshold) else scoring.FAIL), False


# --- kiểm tra phiếu (gọi từ sessions) -------------------------------------------------------------------------------


def invalid(reason, action):
	return _blocked("AUDIT_OPPORTUNITY_INVALID", _("Opportunity not valid"), reason, action)


_invalid = invalid


def validate(doc):
	"""Cơ hội chỉ có ở mẫu "Theo cơ hội" và thuộc các thời điểm của mẫu; "Không thực hiện" không có kỹ thuật."""
	rows = doc.opportunities or []
	if doc.scoring_method != BY_OPPORTUNITY:
		if rows:
			raise _invalid(
				_("Template {0} does not record hand hygiene opportunities.").format(doc.audit_template),
				_("Choose a hand hygiene template, or remove the opportunities."),
			)
		return
	allowed = moments(doc.audit_template)
	for row in rows:
		row.moment = str(row.moment or "")
		if allowed and row.moment not in allowed:  # mẫu không khai mục thời điểm thì nhận 1-5 như DocType
			raise _invalid(
				_("Moment {0} is not in template {1}.").format(row.moment, doc.audit_template),
				_("Choose one of the moments of the template: {0}.").format(", ".join(allowed)),
			)
		if row.action == MISSED:
			row.technique_ok = 0


def before_submit(doc):
	if doc.scoring_method == BY_OPPORTUNITY and not doc.opportunities:
		raise _blocked(
			"AUDIT_NO_OPPORTUNITY",
			_("No opportunity recorded"),
			_("The audit has no hand hygiene opportunity."),
			_("Record at least one opportunity before posting."),
		)


# --- tổng hợp -------------------------------------------------------------------------------------------------------


def _query(filters, dims):
	"""Đếm cơ hội của phiếu đã ghi sổ trong kỳ, nhóm theo ``dims`` (tên cột của phiếu hoặc của cơ hội)."""
	from tracecore.compliance_audit import sessions  # sessions nạp module này nên import muộn

	filters = frappe._dict(filters or {})
	session, row = frappe.qb.DocType(SESSION), frappe.qb.DocType(CHILD)
	columns = [(row if dim in ("subject_role", "moment") else session)[dim] for dim in dims]
	query = (
		frappe.qb.from_(session)
		.join(row)
		.on((row.parent == session.name) & (row.parenttype == SESSION))
		.where(session.docstatus == 1)
		.where(session.scoring_method == BY_OPPORTUNITY)
		.where(session.audit_date[getdate(filters.from_date) : getdate(filters.to_date)])
		.groupby(*columns)
		.select(
			*columns,
			Count(session.name).distinct().as_("sessions"),
			Count(row.name).as_("total"),
			Sum(Case().when(row.action != MISSED, 1).else_(0)).as_("actioned"),
			Sum(Case().when((row.action != MISSED) & (row.technique_ok == 1), 1).else_(0)).as_(
				"technique_ok"
			),
		)
	)
	for field in ("audit_type", "template_code", "department"):
		if filters.get(field):
			query = query.where(session[field] == filters[field])
	if filters.profession:
		query = query.where(row.subject_role == filters.profession)
	if filters.moment:
		query = query.where(row.moment == str(filters.moment))
	allowed = sessions.allowed_departments()
	if allowed is not None:
		query = query.where(session.department.isin(allowed or [""]))
	return [frappe._dict(item) for item in query.run(as_dict=True)]


def rows(filters):
	"""Dòng theo (mã mẫu, khoa) cùng dạng ``compliance.aggregate``: ``passed`` = cơ hội có hành động, ``scored`` = tổng
	cơ hội (n của FR-M12-11)."""
	result = []
	for item in _query(filters, ["template_code", "department"]):
		result.append(
			frappe._dict(
				template_code=item.template_code,
				department=item.department,
				sessions=item.sessions,
				passed=int(item.actioned or 0),
				scored=int(item.total or 0),
				critical_failed=0,
				avg_score=_percent(item.actioned, item.total),
			)
		)
	return result


def totals(filters):
	"""``(tổng cơ hội, có hành động, đúng kỹ thuật)`` của các phiếu đã ghi sổ thỏa bộ lọc."""
	items = _query(filters, ["department"])
	return tuple(
		sum(int(item[field] or 0) for item in items) for field in ("total", "actioned", "technique_ok")
	)


def sample_threshold(template_code=None):
	"""``min_sample`` của phiên bản đã duyệt mới nhất của mẫu "Theo cơ hội" (lớn nhất nếu có nhiều mã)."""
	filters = {"docstatus": 1, "scoring_method": BY_OPPORTUNITY}
	if template_code:
		filters["template_code"] = template_code
	latest = {}
	for row in frappe.get_all(
		templates.DOCTYPE,
		filters=filters,
		fields=["template_code", "min_sample", "version_no"],
		order_by="version_no asc",
	):
		latest[row.template_code] = row.min_sample or 0
	return max(latest.values(), default=0)


def breakdown(filters, group_by="department"):
	"""Tỷ lệ theo khoa / nghề nghiệp / thời điểm / tháng (FR-M12-05): ``[{key, sessions, total, actioned, rate,
	technique_ok, technique_rate, sample_note, rate_label}]``."""
	if group_by not in GROUPS:
		frappe.throw(_("Group by must be one of: {0}.").format(", ".join(GROUPS)))
	filters = frappe._dict(filters or {})
	dim = GROUPS[group_by]
	merged = {}
	for item in _query(filters, [dim, "audit_date"] if dim != "audit_date" else ["audit_date"]):
		key = f"{getdate(item.audit_date):%Y-%m}" if group_by == "month" else (item[dim] or "")
		cell = merged.setdefault(key, frappe._dict(key=key, sessions=0, total=0, actioned=0, technique_ok=0))
		for field in ("sessions", "total", "actioned", "technique_ok"):
			cell[field] += int(item[field] or 0)
	min_sample = sample_threshold(filters.template_code)
	result = []
	for key in sorted(merged):
		cell = merged[key]
		cell.rate = _percent(cell.actioned, cell.total)
		cell.technique_rate = _percent(cell.technique_ok, cell.actioned)
		cell.min_sample = min_sample
		cell.sample_note = (
			NOT_CALCULATED if not cell.total else INSUFFICIENT if cell.total < min_sample else ""
		)
		cell.rate_label = rate_label(cell)
		result.append(cell)
	return result


def month_opportunities(template_code, department, on):
	"""Số cơ hội đã ghi sổ của mã mẫu tại khoa trong tháng của ngày ``on`` (cỡ mẫu FR-M12-11 của phiếu theo cơ hội)."""
	on = getdate(on)
	session, row = frappe.qb.DocType(SESSION), frappe.qb.DocType(CHILD)
	query = (
		frappe.qb.from_(session)
		.join(row)
		.on((row.parent == session.name) & (row.parenttype == SESSION))
		.where(session.docstatus == 1)
		.where(session.template_code == template_code)
		.where(session.department == department)
		.where(session.audit_date[get_first_day(on) : get_last_day(on)])
		.select(Count(row.name))
	)
	return query.run()[0][0] or 0


# --- nhãn ---------------------------------------------------------------------------------------------------------


def _decimal(value):
	text = f"{flt(value, 1):.1f}"
	if (frappe.db.get_default("number_format") or "").endswith(",##"):
		text = text.replace(".", ",")
	return text


def rate_label(row):
	"""Nhãn tỷ lệ VST luôn một chữ số thập phân: "82,0 % (n = 50)" | "75,0 % (n = 8, chưa đủ cỡ mẫu)" | "Không tính"."""
	if row.get("rate") is None:
		return _(NOT_CALCULATED)
	if row.get("sample_note") == INSUFFICIENT:
		return _("{0} % (n = {1}, insufficient sample)").format(_decimal(row["rate"]), row["total"])
	return _("{0} % (n = {1})").format(_decimal(row["rate"]), row["total"])
