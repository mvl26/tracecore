"""Nước thải y tế: GPMT có phiên bản và đợt quan trắc (FEAT-095; FR-M15-08, .1, .2, FR-M15-10, .1, FR-M15-11, FR-M15-13,
.1; BRU-ENV-003..006; UC-58; A-153).

- GPMT (`Wastewater Permit`) ghi sổ = R01 duyệt và khóa phiên bản ``GPMT-<permit_code>-V<n>`` (``core.versioning``);
  sửa = ``new_version`` chép bản đang dùng thành Nháp V(n+1); bản cũ hơn ghi ``superseded_by`` khi bản mới được duyệt.
  Giới hạn, tần suất là cấu hình theo giấy phép của bệnh viện, không viết trong code; mẫu quy chuẩn là file dữ liệu
  ``data/wastewater_standards.json`` (Nháp), chỉ chép vào GPMT khi R01 nạp (``template``).
- Đợt quan trắc dùng phiên bản GPMT đã duyệt có hiệu lực tại ``sampled_on`` (``active_permit``), nạp thông số không tự
  động của điểm, so từng dòng và lưu bản chụp giới hạn (BRU-ENV-004, BRU-ENV-005). Giá trị 0 = chưa nhập (cột Float của
  Frappe không null); KPH đánh dấu ``below_detection``.
- Không đạt (ghi sổ): cờ điểm "Vượt chuẩn - chờ quan trắc lại", ToDo quan trắc lại cho người phụ trách, thông báo,
  ``nc_status`` = Suggested (hoặc nối NC đã mở của chuỗi quan trắc lại). Chỉ R01 ``open_nc`` → hook
  ``tracecore_environment_nc`` (M2 tạo Incident CAPA loại Environment, M15 không import M2) hoặc ``dismiss_nc`` có lý do.
"""

import json
import os

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, cstr, date_diff, flt, getdate, today

from tracecore.core import audit, extension, notification, versioning
from tracecore.core.errors import Block, BlockedError

POINT_DOCTYPE = "Wastewater Point"
PERMIT_DOCTYPE = "Wastewater Permit"
ROW_DOCTYPE = "Wastewater Permit Parameter"
DOCTYPE = "Wastewater Monitoring"
RESULT_DOCTYPE = "Wastewater Result"
PREFIX = "GPMT"
INLET = "Inlet"
PASS, FAIL, INCOMPLETE, REFERENCE = "Pass", "Fail", "Incomplete", "Reference Only"
SUGGESTED, OPENED, DISMISSED = "Suggested", "Opened", "Dismissed"
FREQUENCIES = (3, 6, 12)
NC_HOOK = "tracecore_environment_nc"
NC_ROLES = frozenset({"TC R01", "System Manager"})
FLAG_ROLES = frozenset({"TC R01", "TC R11", "System Manager"})
FAILED_EVENT = "WW_MONITORING_FAILED"
BADGE_SLUG = "nuoc-thai"
EXPIRY_WARNING_DAYS = 90
STANDARDS_FILE = os.path.join(os.path.dirname(__file__), "data", "wastewater_standards.json")
AFTER_APPROVAL = frozenset({"superseded_by", "modified", "modified_by", "_comments", "_assign", "_liked_by"})


def blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


def _number(value):
	"""Số gọn, dấu phẩy thập phân (100 → "100", 0,5 → "0,5", 460000 → "460000")."""
	value = flt(value)
	if value == int(value):
		return str(int(value))
	return f"{value:.6f}".rstrip("0").rstrip(".").replace(".", ",")


# --- kỳ quan trắc (FR-M15-09; W3) ------------------------------------------------------------------------------------


def period_label(frequency, start):
	start = getdate(start)
	if frequency == 3:
		return _("Quarter {0}/{1}").format((start.month - 1) // 3 + 1, start.year)
	if frequency == 6:
		return _("Half {0}/{1}").format((start.month - 1) // 6 + 1, start.year)
	return _("Year {0}").format(start.year)


def periods(frequency, year):
	"""Kỳ lịch của năm: khối ``frequency`` tháng tính từ 01/01."""
	frequency = cint(frequency) or 12
	result = []
	for index, month in enumerate(range(1, 13, frequency)):
		start = getdate(f"{cint(year)}-{month:02d}-01")
		end = add_days(add_months(start, frequency), -1)
		result.append(
			{"index": index, "start": start, "end": getdate(end), "label": period_label(frequency, start)}
		)
	return result


def period_of(on, frequency):
	on = getdate(on)
	return next(p for p in periods(frequency, on.year) if p["start"] <= on <= p["end"])


# --- GPMT có phiên bản (FR-M15-08, .1) ---------------------------------------------------------------------------------


def normalize_code(raw):
	try:
		return versioning.normalize_code(raw)
	except ValueError:
		frappe.throw(
			_("Permit code {0} is invalid. Use Latin letters without accents, digits and dashes.").format(
				frappe.bold(raw or "")
			)
		)


def _versions(code):
	return frappe.get_all(
		PERMIT_DOCTYPE,
		filters={"permit_code": code},
		fields=["name", "version_no", "docstatus", "effective_from"],
		order_by="version_no desc",
	)


def permit_autoname(doc):
	doc.permit_code = normalize_code(doc.permit_code)
	versions = _versions(doc.permit_code)
	draft = next((row for row in versions if row.docstatus == 0), None)
	if draft:
		frappe.throw(
			_("Permit {0} already has a draft version {1}. Open and edit that draft instead.").format(
				doc.permit_code, draft.name
			)
		)
	doc.version_no = (versions[0].version_no if versions else 0) + 1
	doc.name = versioning.make_versioned_code(PREFIX, doc.permit_code, doc.version_no)


def validate_permit(doc):
	"""Bắt buộc ≥ 1 dòng; dòng không tự động phải có tần suất; mỗi dòng có giới hạn (hoặc chỉ KPH); min ≤ max."""
	if not doc.parameters:
		frappe.throw(_("Add at least one parameter row with point, limit and frequency."))
	seen = set()
	for row in doc.parameters:
		row.parameter = cstr(row.parameter).strip()
		label = _("Row {0} ({1})").format(row.idx, row.parameter)
		key = (row.wastewater_point, row.parameter.lower())
		if key in seen:
			frappe.throw(
				_("{0}: parameter is listed twice for point {1}.").format(label, row.wastewater_point)
			)
		seen.add(key)
		if not cint(row.auto_monitored) and cint(row.frequency_months) not in FREQUENCIES:
			frappe.throw(_("{0}: choose the monitoring frequency (3, 6 or 12 months).").format(label))
		if cint(row.detect_only):
			continue
		if not flt(row.max_value) and not flt(row.min_value):
			frappe.throw(_("{0}: enter the limit, or tick Not Detected Only.").format(label))
		if flt(row.min_value) and flt(row.max_value) and flt(row.min_value) > flt(row.max_value):
			frappe.throw(_("{0}: the lower limit cannot be above the upper limit.").format(label))


def guard_locked(doc):
	"""Phiên bản đã duyệt bất biến: chặn và gợi ý tạo V(n+1)."""
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = [
		field.fieldname
		for field in doc.meta.fields
		if field.fieldtype not in ("Section Break", "Column Break", "Table")
		and field.fieldname not in AFTER_APPROVAL
		and doc.get(field.fieldname) != before.get(field.fieldname)
	]
	if changed:
		frappe.throw(
			_(
				"Version {0} is approved and locked. Create version V{1} to change it; rounds already recorded keep version {0}."
			).format(doc.name, cint(doc.version_no) + 1),
			title=_("Approved permit is locked"),
		)


def on_approve(doc):
	for row in _versions(doc.permit_code):
		if row.docstatus == 1 and row.version_no < doc.version_no:
			if not frappe.db.get_value(PERMIT_DOCTYPE, row.name, "superseded_by"):
				frappe.db.set_value(
					PERMIT_DOCTYPE, row.name, "superseded_by", doc.name, update_modified=False
				)


def new_version(name):
	"""Chép phiên bản đã duyệt mới nhất thành Nháp V(n+1); đã có Nháp thì trả bản Nháp đó."""
	source = frappe.get_doc(PERMIT_DOCTYPE, name)
	if source.docstatus != 1:
		frappe.throw(_("Only an approved version can be revised. Edit draft {0} directly.").format(name))
	versions = _versions(source.permit_code)
	draft = next((row for row in versions if row.docstatus == 0), None)
	if draft:
		return frappe.get_doc(PERMIT_DOCTYPE, draft.name)
	latest = next(row for row in versions if row.docstatus == 1)
	if latest.name != source.name:
		frappe.throw(_("Version {0} is no longer current. Revise version {1}.").format(name, latest.name))
	doc = frappe.copy_doc(source)
	doc.update(
		{
			"docstatus": 0,
			"version_no": None,
			"effective_from": today(),
			"superseded_by": None,
			"amended_from": None,
		}
	)
	return doc.insert()


def current_permits(on=None):
	"""Phiên bản đã duyệt mới nhất có hiệu lực tại ``on`` của mỗi mã GPMT."""
	on = getdate(on or today())
	rows = frappe.get_all(
		PERMIT_DOCTYPE,
		filters={"docstatus": 1, "effective_from": ["<=", on]},
		fields=["name", "permit_code", "version_no", "effective_from"],
		order_by="version_no desc",
	)
	latest = {}
	for row in rows:
		latest.setdefault(row.permit_code, row)
	return sorted(latest.values(), key=lambda row: (getdate(row.effective_from), row.name), reverse=True)


def active_permit(point, on=None):
	"""Phiên bản GPMT có hiệu lực tại ``on`` có dòng cho ``point`` (BRU-ENV-004); không có → None."""
	if not point:
		return None
	for row in current_permits(on):
		if frappe.db.exists(
			ROW_DOCTYPE, {"parent": row.name, "parenttype": PERMIT_DOCTYPE, "wastewater_point": point}
		):
			return row.name
	return None


def permit_rows(permit, point, include_auto=True):
	rows = frappe.get_all(
		ROW_DOCTYPE,
		filters={"parent": permit, "parenttype": PERMIT_DOCTYPE, "wastewater_point": point},
		fields=[
			"parameter",
			"unit",
			"min_value",
			"max_value",
			"detect_only",
			"frequency_months",
			"auto_monitored",
			"legal_ref",
		],
		order_by="idx asc",
	)
	return [row for row in rows if include_auto or not cint(row.auto_monitored)]


def days_to_expiry(permit, on=None):
	valid_until = permit.get("valid_until") if isinstance(permit, dict) else permit.valid_until
	return date_diff(valid_until, getdate(on or today())) if valid_until else None


def _standards():
	with open(STANDARDS_FILE, encoding="utf-8") as handle:
		return json.load(handle)


def template(standard, column, point=None, frequency=None):
	"""Dòng thông số mẫu của quy chuẩn và cột (FR-M15-08.2); chỉ trả dữ liệu, không ghi gì."""
	data = _standards()
	entry = next((item for item in data["standards"] if item["standard"] == standard), None)
	rows = entry and entry["columns"].get(cstr(column).upper())
	if not rows:
		frappe.throw(_("No template for standard {0}, column {1}.").format(standard, column))
	return [
		{
			"wastewater_point": point,
			"parameter": row["parameter"],
			"unit": row.get("unit"),
			"min_value": row.get("min_value"),
			"max_value": row.get("max_value"),
			"detect_only": cint(row.get("detect_only")),
			"frequency_months": cstr(frequency or ""),
			"legal_ref": entry["legal_ref"],
		}
		for row in rows
	]


# --- đánh giá đợt quan trắc (FR-M15-10; BRU-ENV-004, BRU-ENV-005) -------------------------------------------------------


def band(limit):
	"""Khoảng giới hạn ngắn: "6 - 9", "≤ 100", "≥ 2", "KPH"."""
	if cint(limit.get("detect_only")):
		return _("Not detected")
	low, high = flt(limit.get("min_value")), flt(limit.get("max_value"))
	if low and high:
		return f"{_number(low)} - {_number(high)}"
	if high:
		return f"≤ {_number(high)}"
	return f"≥ {_number(low)}"


def measured(row):
	return bool(cint(row.get("below_detection")) or flt(row.get("value")))


def evaluate(limit, row):
	"""Đạt / Không đạt một dòng; chưa nhập → None (BRU-ENV-005)."""
	if not measured(row):
		return None
	low, high = flt(limit.get("min_value")), flt(limit.get("max_value"))
	if cint(row.get("below_detection")):
		return FAIL if low else PASS
	value = flt(row.get("value"))
	if cint(limit.get("detect_only")):
		return FAIL if value > 0 else PASS
	if high and value > high:
		return FAIL
	if low and value < low:
		return FAIL
	return PASS


def _point(name):
	point = frappe.db.get_value(
		POINT_DOCTYPE,
		name,
		["name", "point_name", "point_type", "responsible_user", "disabled"],
		as_dict=True,
	)
	if not point:
		frappe.throw(_("Wastewater point {0} not found.").format(name))
	return point


def point_frequency(rows):
	values = [cint(row.frequency_months) for row in rows if not cint(row.auto_monitored)]
	values = [value for value in values if value in FREQUENCIES]
	return min(values) if values else None


def load_parameters(doc):
	"""Nạp phiên bản GPMT hiệu lực tại ngày lấy mẫu và (nếu đợt chưa có dòng) các thông số không tự động của điểm."""
	permit = active_permit(doc.wastewater_point, doc.sampled_on or today())
	doc.wastewater_permit = permit
	if permit and not doc.get("results"):
		for row in permit_rows(permit, doc.wastewater_point, include_auto=False):
			doc.append("results", {"parameter": row.parameter, "unit": row.unit})
	return permit


def _check_lab(doc):
	lab = frappe.db.get_value(
		"Supplier", doc.supplier, ["tc_vimcerts_no", "tc_vimcerts_valid_until"], as_dict=True
	)
	if not lab or not cstr(lab.tc_vimcerts_no).strip() or not lab.tc_vimcerts_valid_until:
		raise blocked(
			"WW_VIMCERTS_MISSING",
			_("Monitoring unit not certified"),
			_("{0} has no VIMCERTS certificate number or expiry date.").format(doc.supplier),
			_("Enter the VIMCERTS number and expiry date on the supplier, or choose a certified unit."),
		)
	if getdate(lab.tc_vimcerts_valid_until) < getdate(doc.sampled_on):
		raise blocked(
			"WW_VIMCERTS_EXPIRED",
			_("VIMCERTS expired"),
			_("{0} expired on {1}, before the sampling date {2}.").format(
				lab.tc_vimcerts_no,
				frappe.format(lab.tc_vimcerts_valid_until, "Date"),
				frappe.format(doc.sampled_on, "Date"),
			),
			_("Choose a monitoring unit whose VIMCERTS is valid on the sampling date."),
		)
	doc.vimcerts_no = lab.tc_vimcerts_no


def _check_remonitor(doc):
	if not doc.is_remonitor_of:
		return
	parent = frappe.db.get_value(
		DOCTYPE, doc.is_remonitor_of, ["wastewater_point", "docstatus", "overall_result"], as_dict=True
	)
	if (
		not parent
		or parent.docstatus != 1
		or parent.overall_result != FAIL
		or parent.wastewater_point != doc.wastewater_point
	):
		raise blocked(
			"WW_REMONITOR_INVALID",
			_("Not a re-monitoring"),
			_("Round {0} is not a posted failed round of point {1}.").format(
				doc.is_remonitor_of, doc.wastewater_point
			),
			_("Choose the failed round of this point, or clear Re-monitoring Of."),
		)


def snapshot(permit, limit):
	return f"{permit.name} · {limit.parameter} {band(limit)} {limit.unit or ''} · {permit.standard} {permit.standard_column}"


def validate(doc):
	"""Gọi từ ``WastewaterMonitoring.validate``."""
	doc.sampled_on = getdate(doc.sampled_on or today())
	if doc.sampled_on > getdate(today()):
		raise blocked(
			"WW_SAMPLE_DATE_INVALID",
			_("Sampling date in the future"),
			_("Sampling date {0} is after today.").format(frappe.format(doc.sampled_on, "Date")),
			_("Enter the day the sample was taken."),
		)
	point = _point(doc.wastewater_point)
	doc.point_name, doc.point_type = point.point_name, point.point_type
	_check_remonitor(doc)
	_check_lab(doc)
	name = load_parameters(doc)
	if not name:
		raise blocked(
			"WW_PERMIT_MISSING",
			_("No permit in effect"),
			_("No approved environmental permit covers point {0} on {1}.").format(
				point.point_name, frappe.format(doc.sampled_on, "Date")
			),
			_("Ask the head of infection control to approve the permit for this point."),
		)
	permit = frappe.get_doc(PERMIT_DOCTYPE, name)
	doc.standard_applied = f"{permit.standard} · {permit.standard_column}"
	point_rows = permit_rows(name, doc.wastewater_point)
	limits = {cstr(row.parameter).strip().lower(): row for row in point_rows}
	required = {key for key, row in limits.items() if not cint(row.auto_monitored)}
	doc.period_label = period_of(doc.sampled_on, point_frequency(point_rows) or 12)["label"]
	inlet = point.point_type == INLET
	done = set()
	for row in doc.results:
		key = cstr(row.parameter).strip().lower()
		limit = limits.get(key)
		if not limit:
			row.limit_applied, row.result = "—", None
			continue
		row.unit = row.unit or limit.unit
		row.limit_applied = snapshot(permit, limit)
		if cint(row.below_detection):
			row.value = 0
		row.result = None if inlet else evaluate(limit, row)
		if measured(row):
			done.add(key)
	if inlet:
		doc.overall_result = REFERENCE
	elif any(row.result == FAIL for row in doc.results):
		doc.overall_result = FAIL
	elif required - done:
		doc.overall_result = INCOMPLETE
	else:
		doc.overall_result = PASS


def before_submit(doc):
	if not cstr(doc.attachment).strip():
		raise blocked(
			"WW_REPORT_FILE_REQUIRED",
			_("Result report required"),
			_("Round {0} has no result report file from the monitoring unit.").format(doc.name),
			_("Attach the signed result report (PDF or image), then post."),
		)
	if doc.overall_result != FAIL:
		doc.nc_status = None


# --- ghi sổ: cờ, việc quan trắc lại, thông báo, đề nghị NC (FR-M15-11) --------------------------------------------------


def _chain(doc):
	seen, name = [], doc.is_remonitor_of
	while name and name not in seen:
		seen.append(name)
		name = frappe.db.get_value(DOCTYPE, name, "is_remonitor_of")
	return seen


def _opened_nc(doc):
	for name in _chain(doc):
		row = frappe.db.get_value(DOCTYPE, name, ["nc_status", "nc_name"], as_dict=True)
		if row and row.nc_status == OPENED and row.nc_name:
			return row.nc_name
	return None


def _close_tasks(name):
	for todo in frappe.get_all(
		"ToDo", filters={"reference_type": DOCTYPE, "reference_name": name, "status": "Open"}, pluck="name"
	):
		frappe.db.set_value("ToDo", todo, "status", "Closed")


def failed_parameters(doc):
	return [row.parameter for row in doc.results if row.result == FAIL]


def _remonitor_task(doc, point):
	user = point.responsible_user or frappe.session.user
	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": user,
			"assigned_by": frappe.session.user,
			"reference_type": DOCTYPE,
			"reference_name": doc.name,
			"date": today(),
			"priority": "High",
			"description": _("Re-monitor wastewater point {0}: round {1} exceeded ({2}).").format(
				point.point_name, doc.name, ", ".join(failed_parameters(doc))
			),
		}
	).insert(ignore_permissions=True)
	return user


def _notify(doc, point, task_user):
	notification.emit(
		FAILED_EVENT,
		doc,
		subject=_("Wastewater round {0} exceeded limits — {1}").format(doc.name, point.point_name),
		message=_(
			"{0}, sampled {1}: {2} exceeded the permit limits. Re-monitor and decide on a non-conformance."
		).format(point.point_name, frappe.format(doc.sampled_on, "Date"), ", ".join(failed_parameters(doc))),
		users=[user for user in (point.responsible_user, task_user) if user],
	)


def unresolved_failures(point):
	rows = frappe.get_all(
		DOCTYPE,
		filters={"wastewater_point": point, "docstatus": 1},
		fields=["name", "overall_result", "is_remonitor_of"],
		order_by="sampled_on asc, creation asc",
	)
	children = {}
	for row in rows:
		if row.is_remonitor_of:
			children.setdefault(row.is_remonitor_of, []).append(row)

	def resolved(name, depth=0):
		return depth < 50 and any(
			child.overall_result == PASS or resolved(child.name, depth + 1)
			for child in children.get(name, ())
		)

	return [row.name for row in rows if row.overall_result == FAIL and not resolved(row.name)]


def refresh_flag(point):
	if not point:
		return
	pending = unresolved_failures(point)
	frappe.db.set_value(
		POINT_DOCTYPE,
		point,
		{"awaiting_remonitor": 1 if pending else 0, "flag_monitoring": pending[-1] if pending else None},
		update_modified=False,
	)


def on_submit(doc):
	point = _point(doc.wastewater_point)
	if doc.is_remonitor_of:
		_close_tasks(doc.is_remonitor_of)
	if doc.overall_result == FAIL:
		opened = _opened_nc(doc)
		doc.db_set(
			{"nc_status": OPENED, "nc_name": opened} if opened else {"nc_status": SUGGESTED, "nc_name": None}
		)
		user = _remonitor_task(doc, point)
		_notify(doc, point, user)
	refresh_flag(doc.wastewater_point)


def on_cancel(doc):
	_close_tasks(doc.name)
	refresh_flag(doc.wastewater_point)


# --- quyết định NC (FR-M15-11; chỉ R01 — FR-M15-13.1) -------------------------------------------------------------------


def can_decide(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & NC_ROLES)


def _require_decider():
	if not can_decide():
		frappe.throw(
			_(
				"Only the head of infection control (R01) can open or dismiss a non-conformance from a wastewater round."
			),
			frappe.PermissionError,
		)


def _suggested(name):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	if doc.docstatus != 1 or doc.nc_status not in (SUGGESTED, OPENED):
		raise blocked(
			"WW_NC_NOT_SUGGESTED",
			_("No non-conformance to open"),
			_("Round {0} has no failed result waiting for a decision.").format(name),
			_("Open a non-conformance from the incident screen if it is still needed."),
		)
	return doc


def open_nc(name):
	"""Tạo (hoặc trả) Incident Environment nguồn Wastewater Monitoring; trả tên Incident."""
	_require_decider()
	doc = _suggested(name)
	if doc.nc_status == OPENED and doc.nc_name:
		return doc.nc_name
	description = _("Wastewater round {0} exceeded limits: point {1}, sampled {2}, {3} ({4}).").format(
		doc.name,
		doc.point_name,
		frappe.format(doc.sampled_on, "Date"),
		", ".join(failed_parameters(doc)),
		doc.standard_applied,
	)
	# Nước thải là toàn viện: Incident gắn khoa KSNK (IC Program Settings.ic_department) vì Incident cần một đối tượng liên kết
	department = frappe.db.get_single_value("IC Program Settings", "ic_department")
	if not department:
		raise blocked(
			"WW_IC_DEPARTMENT_MISSING",
			_("Infection control department not set"),
			_("A non-conformance needs a department, and no infection control department is set."),
			_("Set the infection control department in IC Program Settings, then open the non-conformance."),
		)
	ctx = {
		"source_doctype": DOCTYPE,
		"source_name": doc.name,
		"department": department,
		"description": description,
	}
	results = [result for result in extension.run(NC_HOOK, ctx) if result]
	if not results:
		frappe.throw(_("No module handles non-conformances from wastewater rounds."))
	doc.db_set({"nc_status": OPENED, "nc_name": results[0]})
	return results[0]


def dismiss_nc(name, reason):
	_require_decider()
	reason = cstr(reason).strip()
	if not reason:
		raise blocked(
			"REASON_REQUIRED",
			_("Reason required"),
			_("No reason was given for not opening a non-conformance."),
			_("Enter why no non-conformance is needed."),
		)
	doc = _suggested(name)
	if doc.nc_status == OPENED:
		raise blocked(
			"WW_NC_NOT_SUGGESTED",
			_("Non-conformance already opened"),
			_("Round {0} already has incident {1}.").format(name, doc.nc_name),
			_("Follow the incident until it is closed."),
		)
	doc.db_set({"nc_status": DISMISSED, "nc_reason": reason})
	audit.log(
		"Update", DOCTYPE, name, old={"nc_status": SUGGESTED}, new={"nc_status": DISMISSED}, reason=reason
	)


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: điểm đang cờ + đợt chờ quyết định NC + kỳ quá hạn năm nay (R01/R11)."""
	if user != "Administrator" and not set(frappe.get_roles(user)) & FLAG_ROLES:
		return {}
	from tracecore.environmental_hygiene import wastewater_schedule

	flagged = frappe.db.count(POINT_DOCTYPE, {"awaiting_remonitor": 1, "disabled": 0})
	return {BADGE_SLUG: cint(flagged) + wastewater_schedule.overdue_count()}
