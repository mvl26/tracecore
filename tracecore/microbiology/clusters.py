"""Cảnh báo cụm ca (FEAT-069; FR-M13-13, .1; UC-50 bước 1-4, A1, A3, E1; A-150 Q2).

- Ngưỡng là `Cluster Alert Rule` do R01 đặt; mặc định không có dòng nào → không cảnh báo (FR-M13-13.1). Khoa trống =
  đếm riêng từng khoa (FR "tại một khoa").
- `run_daily` (job hằng ngày): cửa sổ N ngày kết thúc ở ngày chạy; nguồn HAI Case = ca Xác định (đã ghi sổ) cùng
  ``infection_site`` theo ``onset_date`` — đọc qua ``frappe.db``, M14 không import M13; nguồn Microbiology Isolate =
  chủng cùng loài (hoặc chỉ đa kháng) theo ``collected_on``, mỗi người bệnh (hash mã BN) tính một lần.
- Đạt ≥ ``min_cases`` → `Cluster Alert` (New) + `CLUSTER_ALERT` (Urgent; R01, R11) kèm link mở ổ dịch điền sẵn. Không
  lặp cho cùng cụm đến khi có ca mới: cảnh báo New có ca mới thì cập nhật và báo lại; đã mở ổ dịch / đã xem xét thì
  tạo cảnh báo mới.
- `dismiss`: R01/R11 ghi lý do không mở ổ dịch (UC-53 A3).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, getdate, now_datetime, today

from tracecore.core import notification
from tracecore.core.errors import Block, BlockedError
from tracecore.microbiology import notifiable

RULE_DOCTYPE = "Cluster Alert Rule"
ALERT_DOCTYPE = "Cluster Alert"
HAI, ISOLATE = "HAI Case", "Microbiology Isolate"
NEW, OPENED, DISMISSED = "New", "Investigation Opened", "Dismissed"
EVENT = "CLUSTER_ALERT"
REVIEW_ROLES = ("TC R01", "TC R11")
DESK_LINK = "/app/tc-ksnk/o-dich"
MAX_TEXT = 500


def _block(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


# --- ngưỡng -------------------------------------------------------------------------------------------------------


def validate_rule(doc):
	doc.title = " ".join(cstr(doc.title).split())
	if cint(doc.window_days) < 1:
		frappe.throw(_("The window must be at least 1 day."))
	if cint(doc.min_cases) < 2:
		frappe.throw(_("A cluster needs at least 2 cases."))
	if doc.source == HAI:
		doc.organism = None
		doc.mdro_only = 0
		if not doc.infection_site:
			frappe.throw(_("Choose the infection type of the threshold."))
	elif doc.source == ISOLATE:
		doc.infection_site = None
		if not doc.organism and not cint(doc.mdro_only):
			frappe.throw(_("Choose the organism, or count multidrug-resistant isolates only."))
	else:
		frappe.throw(_("Choose the source of the threshold."))


def configured() -> bool:
	return bool(frappe.db.count(RULE_DOCTYPE, {"disabled": 0}))


def rules():
	return frappe.get_all(
		RULE_DOCTYPE,
		filters={"disabled": 0},
		fields=[
			"name",
			"title",
			"source",
			"infection_site",
			"organism",
			"mdro_only",
			"department",
			"window_days",
			"min_cases",
		],
		order_by="title asc",
	)


def key_label(rule) -> str:
	if rule.source == HAI:
		return _(rule.infection_site)
	label = (
		frappe.db.get_value("Organism", rule.organism, "organism_name") or rule.organism
		if rule.organism
		else ""
	)
	if cint(rule.mdro_only):
		label = f"{label} — {_('multidrug-resistant')}" if label else _("Multidrug-resistant isolates")
	return label


# --- đếm ----------------------------------------------------------------------------------------------------------


def _hai_cases(rule, start, end):
	filters = {
		"docstatus": 1,
		"status": "Confirmed",
		"infection_site": rule.infection_site,
		"onset_date": ["between", [start, end]],
	}
	if rule.department:
		filters["department"] = rule.department
	rows = frappe.get_all(
		HAI, filters=filters, fields=["name", "department", "onset_date"], order_by="onset_date asc"
	)
	return [{"name": row.name, "department": row.department, "date": row.onset_date} for row in rows]


def _isolates(rule, start, end):
	filters = {"collected_on": ["between", [start, end]]}
	if rule.organism:
		filters["organism"] = rule.organism
	if cint(rule.mdro_only):
		filters["is_mdro"] = 1
	if rule.department:
		filters["department"] = rule.department
	rows = frappe.get_all(
		ISOLATE,
		filters=filters,
		fields=["name", "department", "collected_on", "patient_code_hash"],
		order_by="collected_on asc, name asc",
	)
	seen, result = set(), []
	for row in rows:
		key = (row.department, row.patient_code_hash or row.name)
		if key in seen:
			continue
		seen.add(key)
		result.append({"name": row.name, "department": row.department, "date": row.collected_on})
	return result


def _latest(rule, department):
	rows = frappe.get_all(
		ALERT_DOCTYPE,
		filters={"rule": rule, "department": department},
		fields=["name", "status", "case_refs"],
		order_by="creation desc",
		limit_page_length=1,
	)
	return rows[0] if rows else None


def _notify(doc):
	notification.emit(
		EVENT,
		doc=doc,
		subject=_("Infection cluster in {0}: {1} cases of {2} in {3} days").format(
			doc.department_name or doc.department, doc.case_count, doc.key_label, doc.window_days
		),
		message=_("Threshold {0} cases / {1} days. Open an outbreak investigation or record why not.").format(
			doc.min_cases, doc.window_days
		),
		link=f"{DESK_LINK}?alert={doc.name}",
	)


def _raise(rule, department, cases, start, end):
	refs = [case["name"] for case in cases]
	latest = _latest(rule.name, department)
	if latest and set(refs) <= set(cstr(latest.case_refs).split()):
		return None  # không có ca mới
	values = {
		"window_start": start,
		"window_end": end,
		"case_count": len(refs),
		"case_refs": "\n".join(refs),
		"key_label": key_label(rule),
		"window_days": cint(rule.window_days),
		"min_cases": cint(rule.min_cases),
	}
	if latest and latest.status == NEW:
		doc = frappe.get_doc(ALERT_DOCTYPE, latest.name)
		doc.update(values)
	else:
		doc = frappe.get_doc(
			{
				"doctype": ALERT_DOCTYPE,
				"rule": rule.name,
				"source": rule.source,
				"department": department,
				**values,
			}
		)
	doc.flags.tc_cluster = True
	doc.save(ignore_permissions=True)
	_notify(doc)
	return doc.name


def run_daily(day=None):
	"""Job hằng ngày (UC-50 bước 2-3); trả tên các cảnh báo vừa tạo hoặc cập nhật."""
	end = getdate(day or today())
	raised = []
	for rule in rules():
		start = add_days(end, -(cint(rule.window_days) - 1))
		cases = _hai_cases(rule, start, end) if rule.source == HAI else _isolates(rule, start, end)
		by_department = {}
		for case in cases:
			if case["department"]:
				by_department.setdefault(case["department"], []).append(case)
		for department, rows in sorted(by_department.items()):
			if len(rows) >= cint(rule.min_cases):
				name = _raise(rule, department, rows, start, end)
				if name:
					raised.append(name)
	return raised


# --- controller, xem xét ------------------------------------------------------------------------------------------


def validate_alert(doc):
	if not doc.flags.tc_cluster:
		frappe.throw(_("Cluster alerts are created by the daily check and reviewed on the outbreak screen."))


def on_trash(doc):
	frappe.throw(_("A cluster alert is never deleted; record why no investigation is opened instead."))


def _require_reviewer():
	if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(REVIEW_ROLES):
		raise frappe.PermissionError(_("Only infection control staff can review a cluster alert."))


def _new_alert(name):
	if not name or not frappe.db.exists(ALERT_DOCTYPE, name):
		raise frappe.DoesNotExistError(_("Cluster alert {0} does not exist.").format(name))
	doc = frappe.get_doc(ALERT_DOCTYPE, name)
	if doc.status != NEW:
		raise _block(
			"CLUSTER_ALREADY_REVIEWED",
			_("Alert already reviewed"),
			_("Cluster alert {0} is {1}.").format(doc.name, _(doc.status)),
			_("Refresh the list of cluster alerts."),
		)
	return doc


def dismiss(name, reason=None):
	"""R01/R11 ghi lý do không mở điều tra ổ dịch (UC-50 bước 4, UC-53 A3)."""
	_require_reviewer()
	text = " ".join(cstr(reason).split())[:MAX_TEXT]
	if not text:
		raise _block(
			"CLUSTER_REASON_REQUIRED",
			_("Reason required"),
			_("Record why no outbreak investigation is opened for this cluster."),
			_("Enter the reason, then mark the alert as reviewed."),
		)
	doc = _new_alert(name)
	doc.update(
		{
			"status": DISMISSED,
			"review_reason": text,
			"reviewed_by": frappe.session.user,
			"reviewed_on": now_datetime(),
		}
	)
	doc.flags.tc_cluster = True
	doc.save(ignore_permissions=True)
	notification.resolve(EVENT, ALERT_DOCTYPE, doc.name)
	return doc


def mark_opened(name, outbreak):
	"""Gọi khi R01 mở ổ dịch từ cảnh báo (``outbreaks.open_outbreak``)."""
	doc = _new_alert(name)
	doc.update(
		{
			"status": OPENED,
			"outbreak_investigation": outbreak,
			"reviewed_by": frappe.session.user,
			"reviewed_on": now_datetime(),
		}
	)
	doc.flags.tc_cluster = True
	doc.save(ignore_permissions=True)
	notification.resolve(EVENT, ALERT_DOCTYPE, doc.name)
	return doc


ALERT_FIELDS = (
	"name",
	"rule",
	"source",
	"key_label",
	"department",
	"department_name",
	"window_days",
	"min_cases",
	"window_start",
	"window_end",
	"case_count",
	"status",
	"outbreak_investigation",
	"review_reason",
)


def open_alerts(limit=50):
	return [
		dict(row)
		for row in frappe.get_all(
			ALERT_DOCTYPE,
			filters={"status": NEW},
			fields=list(ALERT_FIELDS),
			order_by="window_end desc, creation desc",
			limit_page_length=limit,
		)
	]


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: cảnh báo cụm ca chờ xem xét + khai báo quá hạn (SCR-61) cho R01/R11."""
	if not set(frappe.get_roles(user)) & set(REVIEW_ROLES):
		return {}
	return {"o-dich": frappe.db.count(ALERT_DOCTYPE, {"status": NEW}) + notifiable.badge_count()}


def todos(user, department=None, on=None):
	"""Hook ``tracecore_ksnk_todos`` (A-145 Q3): khai báo bệnh truyền nhiễm chưa xong của khoa; cảnh báo cụm ca chờ
	xem xét (toàn viện, R01/R11)."""
	if department:
		pending = frappe.db.count(
			notifiable.DOCTYPE, {"docstatus": 1, "status": notifiable.PENDING, "department": department}
		)
		if not pending:
			return []
		return [
			{
				"key": "notifiable-pending",
				"severity": "warn",
				"title": _("Notifiable disease reports not yet reported"),
				"count": pending,
				"detail": _(
					"Report on the national surveillance system, then record the date and reference."
				),
				"link": notifiable.PORTAL_LINK,
			}
		]
	if not set(frappe.get_roles(user)) & set(REVIEW_ROLES):
		return []
	count = frappe.db.count(ALERT_DOCTYPE, {"status": NEW})
	if not count:
		return []
	return [
		{
			"key": "cluster-alerts",
			"severity": "error",
			"title": _("Cluster alerts awaiting review"),
			"count": count,
			"detail": _("Open an outbreak investigation or record why not."),
			"link": DESK_LINK,
		}
	]
