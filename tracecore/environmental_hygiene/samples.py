"""Mẫu môi trường (FEAT-070; FR-M15-03, .1, FR-M15-04, .1; BRU-ENV-002, BRU-ENV-003; UC-54 bước 4-6, E2, E5; A-148 d).

- So kết quả với phiên bản ngưỡng có hiệu lực tại ``sampled_on`` (``limits.active_limit``), lưu Link phiên bản và bản chụp
  ``limit_applied``; chứng từ đã ghi sổ không sửa được nên đổi ngưỡng sau đó không đổi kết quả mẫu cũ.
- Không đạt (ghi sổ): cờ vùng "Chờ lấy mẫu lại", ToDo lấy mẫu lại, thông báo R01, R11 và bên chịu trách nhiệm,
  ``nc_status`` = Suggested (hoặc nối NC đã mở của chuỗi mẫu lại, UC-54 E5). R01/R11 ``open_nc`` → hook
  ``tracecore_environment_nc`` (M2 tạo Incident CAPA loại Environment, M15 không import M2) hoặc ``dismiss_nc`` có lý do.
- Mẫu lại (``is_resample_of``) phải trỏ mẫu Không đạt đã ghi sổ của cùng vùng; ghi sổ thì đóng việc lấy mẫu lại của mẫu
  gốc, Đạt thì tắt cờ vùng.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, getdate, today

from tracecore.core import audit, extension, notification
from tracecore.environmental_hygiene import limits, plans, zones
from tracecore.environmental_hygiene.zones import blocked

DOCTYPE = "Environmental Sample"
PASS, FAIL = "Pass", "Fail"
SUGGESTED, OPENED, DISMISSED = "Suggested", "Opened", "Dismissed"
NC_HOOK = "tracecore_environment_nc"
NC_ROLES = frozenset({"TC R01", "TC R11", "System Manager"})
FAILED_EVENT = "ENV_SAMPLE_FAILED"
BADGE_SLUG = "moi-truong"
NETWORK_ROLES = ("TC R08", "TC R12")


# --- so ngưỡng (FR-M15-03) ----------------------------------------------------------------------------------------


def _zone(doc):
	zone = frappe.db.get_value(
		zones.DOCTYPE,
		doc.environment_zone,
		["name", "area_name", "department", "risk_level", "responsible_party", "supplier", "disabled"],
		as_dict=True,
	)
	if not zone:
		frappe.throw(_("Zone {0} not found.").format(doc.environment_zone))
	return zone


def _missing_limit(doc, zone):
	return blocked(
		"ENV_LIMIT_MISSING",
		_("No limit in effect"),
		_("No approved {0} limit ({1}) for risk level {2} is in effect on {3}.").format(
			_(doc.sample_type),
			_(doc.method),
			zone.risk_level,
			frappe.format(doc.sampled_on, "Date"),
		),
		_("Ask the head of infection control to approve the limit, or choose the right limit code."),
	)


def _resolve_limit(doc, zone):
	code = cstr(doc.limit_code).strip()
	if not code:
		codes = limits.candidates(doc.sample_type, doc.method, zone.risk_level, doc.sampled_on)
		if not codes:
			raise _missing_limit(doc, zone)
		if len(codes) > 1:
			raise blocked(
				"ENV_LIMIT_AMBIGUOUS",
				_("Choose the limit"),
				_("Several limits match this sample: {0}.").format(", ".join(codes)),
				_("Enter the limit code of the test, then save."),
			)
		code = codes[0]
	doc.limit_code = limits.normalize_code(code)
	name = limits.active_limit(doc.limit_code, doc.sampled_on)
	limit = frappe.get_doc(limits.DOCTYPE, name) if name else None
	if not limit or not limits.matches(limit, doc.sample_type, doc.method, zone.risk_level):
		raise _missing_limit(doc, zone)
	return limit


def _check_resample(doc):
	if not doc.is_resample_of:
		return
	parent = frappe.db.get_value(
		DOCTYPE, doc.is_resample_of, ["environment_zone", "docstatus", "result"], as_dict=True
	)
	if (
		not parent
		or parent.docstatus != 1
		or parent.result != FAIL
		or parent.environment_zone != doc.environment_zone
	):
		raise blocked(
			"ENV_RESAMPLE_INVALID",
			_("Not a resample"),
			_("Sample {0} is not a posted failed sample of zone {1}.").format(
				doc.is_resample_of, doc.environment_zone
			),
			_("Choose the failed sample of this zone, or clear Resample Of."),
		)


def validate(doc):
	"""Gọi từ ``EnvironmentalSample.validate``."""
	doc.sampled_on = getdate(doc.sampled_on or today())
	if doc.sampled_on > getdate(today()):
		raise blocked(
			"ENV_SAMPLE_DATE_INVALID",
			_("Sampling date in the future"),
			_("Sampling date {0} is after today.").format(frappe.format(doc.sampled_on, "Date")),
			_("Enter the day the sample was taken."),
		)
	zone = _zone(doc)
	doc.department = zone.department
	doc.risk_level = zone.risk_level
	doc.responsible_party = zone.responsible_party
	doc.supplier = zone.supplier
	_check_resample(doc)
	limit = _resolve_limit(doc, zone)
	doc.environmental_limit = limit.name
	doc.unit = limit.unit
	doc.limit_applied = limits.snapshot(limit)
	doc.result = limits.evaluate(limit, doc.result_value)


def before_submit(doc):
	if doc.result != FAIL:
		doc.nc_status = None


# --- ghi sổ: cờ, việc lấy mẫu lại, thông báo, đề nghị NC (FR-M15-04) ---------------------------------------------


def _chain(doc):
	"""Các mẫu gốc của chuỗi mẫu lại (mẫu cha, ông...)."""
	seen, name = [], doc.is_resample_of
	while name and name not in seen:
		seen.append(name)
		name = frappe.db.get_value(DOCTYPE, name, "is_resample_of")
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


def _task_owner(doc):
	if doc.sampling_plan:
		assignee = frappe.db.get_value(plans.DOCTYPE, doc.sampling_plan, "assignee")
		user = assignee and frappe.db.get_value("Employee", assignee, "user_id")
		if user:
			return user
	if doc.sampled_by:
		user = frappe.db.get_value("Employee", doc.sampled_by, "user_id")
		if user:
			return user
	return frappe.session.user


def _resample_task(doc, zone):
	user = _task_owner(doc)
	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": user,
			"assigned_by": frappe.session.user,
			"reference_type": DOCTYPE,
			"reference_name": doc.name,
			"date": today(),
			"priority": "High",
			"description": _("Resample zone {0} ({1}): sample {2} failed ({3}).").format(
				zone.area_name, _(doc.sample_type), doc.name, doc.limit_applied
			),
		}
	).insert(ignore_permissions=True)
	return user


def responsible_users(zone):
	"""Người dùng của bên chịu trách nhiệm: R08/R12 của khoa (User Permission) hoặc portal user của NCC thuê ngoài."""
	if zone.responsible_party == zones.PARTY_VENDOR and zone.supplier:
		return frappe.get_all(
			"Portal User", filters={"parenttype": "Supplier", "parent": zone.supplier}, pluck="user"
		)
	users = frappe.get_all(
		"User Permission", filters={"allow": "Department", "for_value": zone.department}, pluck="user"
	)
	if not users:
		return []
	with_role = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "parent": ["in", users], "role": ["in", list(NETWORK_ROLES)]},
		pluck="parent",
	)
	return sorted(set(with_role))


def _notify(doc, zone, task_user):
	notification.emit(
		FAILED_EVENT,
		doc,
		subject=_("Environmental sample {0} failed — {1}").format(doc.name, zone.area_name),
		message=_("{0}, {1}: {2} {3} against {4}. Resample and decide on a non-conformance.").format(
			zone.area_name,
			_(doc.sample_type),
			frappe.format(doc.result_value, "Float"),
			doc.unit or "",
			doc.limit_applied,
		),
		users=[*responsible_users(zone), task_user],
	)


def on_submit(doc):
	zone = _zone(doc)
	if doc.is_resample_of:
		_close_tasks(doc.is_resample_of)
	if doc.result == FAIL:
		opened = _opened_nc(doc)
		doc.db_set(
			{"nc_status": OPENED, "nc_name": opened} if opened else {"nc_status": SUGGESTED, "nc_name": None}
		)
		user = _resample_task(doc, zone)
		_notify(doc, zone, user)
	zones.refresh_flag(doc.environment_zone)
	if not doc.is_resample_of:
		plans.on_sample(doc)


def on_cancel(doc):
	_close_tasks(doc.name)
	zones.refresh_flag(doc.environment_zone)


# --- quyết định NC (FR-M15-04) -------------------------------------------------------------------------------------


def can_decide(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & NC_ROLES)


def _require_decider():
	if not can_decide():
		frappe.throw(
			_("Only R01 or R11 can open or dismiss a non-conformance from an environmental sample."),
			frappe.PermissionError,
		)


def _suggested(name):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")
	if doc.docstatus != 1 or doc.nc_status not in (SUGGESTED, OPENED):
		raise blocked(
			"ENV_NC_NOT_SUGGESTED",
			_("No non-conformance to open"),
			_("Sample {0} has no failed result waiting for a decision.").format(name),
			_("Open a non-conformance from the incident screen if it is still needed."),
		)
	return doc


def open_nc(name):
	"""Tạo (hoặc trả) Incident Environment liên kết mẫu nguồn; trả tên Incident."""
	_require_decider()
	doc = _suggested(name)
	if doc.nc_status == OPENED and doc.nc_name:
		return doc.nc_name
	zone = _zone(doc)
	description = _(
		"Environmental sample {0} failed: zone {1}, {2}, sampled {3}, result {4} {5} against {6}."
	).format(
		doc.name,
		zone.area_name,
		_(doc.sample_type),
		frappe.format(doc.sampled_on, "Date"),
		frappe.format(doc.result_value, "Float"),
		doc.unit or "",
		doc.limit_applied,
	)
	ctx = {"sample": doc.name, "department": doc.department, "description": description}
	results = [result for result in extension.run(NC_HOOK, ctx) if result]
	if not results:
		frappe.throw(_("No module handles non-conformances from environmental samples."))
	doc.db_set({"nc_status": OPENED, "nc_name": results[0]})
	return results[0]


def dismiss_nc(name, reason):
	"""Không mở NC: bắt buộc lý do, ghi Audit Log."""
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
			"ENV_NC_NOT_SUGGESTED",
			_("Non-conformance already opened"),
			_("Sample {0} already has incident {1}.").format(name, doc.nc_name),
			_("Follow the incident until it is closed."),
		)
	doc.db_set({"nc_status": DISMISSED, "nc_reason": reason})
	audit.log(
		"Update", DOCTYPE, name, old={"nc_status": SUGGESTED}, new={"nc_status": DISMISSED}, reason=reason
	)


def badges(user):
	"""Hook ``tracecore_ksnk_badges``: mẫu chờ quyết định NC + vùng chờ lấy mẫu lại (R01/R11)."""
	if not can_decide(user):
		return {}
	pending = frappe.db.count(DOCTYPE, {"docstatus": 1, "nc_status": SUGGESTED})
	flagged = frappe.db.count(zones.DOCTYPE, {"awaiting_resample": 1, "disabled": 0})
	return {BADGE_SLUG: cint(pending) + cint(flagged)}
