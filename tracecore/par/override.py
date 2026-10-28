"""Ghi đè cơ số có phê duyệt (M8, FEAT-032, UC-31, FR-M8-04, BRU-PAR-004, WF-08, A-18).

Vòng đời ``Par Override``: R04 đề nghị (``request``, Nháp/Requested) → R01 hoặc R02 được ủy quyền duyệt/từ chối bằng PIN
(``approve``/``reject``, Ghi sổ) → bộ đóng gói tiếp trong phạm vi số chu trình thêm và thời hạn (``active_for``,
``consume``) → hết hiệu lực khi đủ số chu trình hoặc qua ngày (``expire_overdue``, cron 00:00).

Module không import M1-M10: đọc ``Set Unit`` theo tên DocType, đổi trạng thái bộ chỉ qua ``core.step_gate`` (ADR-005).
``tracecore.par.check`` import module này, nên module này chỉ import ``check`` bên trong hàm.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, cstr, get_first_day, get_last_day, getdate, now_datetime, today

from tracecore.core import notification, station_auth, step_gate
from tracecore.core.errors import Block, BlockedError

DOCTYPE = "Par Override"
FLAG = "tc_par_override"  # chỉ dịch vụ này được ghi quyết định và bộ đếm
R01, R02 = "TC R01", "TC R02"
SET_FIELDS = ("name", "set_type", "status", "cycles_used", "max_cycles", "current_cycle_no")
# Trường chỉ dịch vụ được đổi (kể cả khi ghi sổ rồi): người dùng sửa tay trên form bị chặn
PROTECTED = (
	"set_unit",
	"status",
	"cycles_used",
	"max_cycles",
	"requested_by",
	"requested_at",
	"extra_cycles",
	"valid_until",
	"decision_reason",
	"decided_by",
	"decided_by_employee",
	"decided_at",
	"pin_verified",
	"cycles_consumed",
	"last_cycle_no",
	"expiry_cause",
	"expired_at",
)


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


# --- Truy vấn ghi đè của một bộ -----------------------------------------------------------------------


def pending_for(set_unit):
	"""Tên đề nghị đang chờ duyệt của bộ, hoặc None."""
	return frappe.db.get_value(DOCTYPE, {"set_unit": set_unit, "docstatus": 0, "status": "Requested"}, "name")


def active_for(set_unit, cycle_no=0):
	"""Ghi đè đang cho bộ đóng gói: ``{name, extra_cycles, cycles_consumed, valid_until}`` hoặc None (A-18 Q9).

	Hiệu lực = Approved, ``valid_until`` chưa qua, và còn số chu trình (``cycles_consumed < extra_cycles``) hoặc đang ở
	đúng chu trình đã dùng ``last_cycle_no`` (void rồi đóng gói lại cùng chu trình không trừ thêm; kể cả khi chu trình
	đó là chu trình cuối làm ghi đè Expired do hết số chu trình).
	"""
	rows = frappe.get_all(
		DOCTYPE,
		filters={
			"set_unit": set_unit,
			"docstatus": 1,
			"status": ["in", ["Approved", "Expired"]],
			"valid_until": [">=", today()],
		},
		fields=[
			"name",
			"status",
			"extra_cycles",
			"cycles_consumed",
			"last_cycle_no",
			"valid_until",
			"expiry_cause",
		],
		order_by="creation desc",
	)
	for row in rows:
		same_cycle = bool(cycle_no) and cint(row.last_cycle_no) == cint(cycle_no)
		approved = row.status == "Approved" and (
			cint(row.cycles_consumed) < cint(row.extra_cycles) or same_cycle
		)
		spent = row.status == "Expired" and row.expiry_cause == "Cycles Used" and same_cycle
		if approved or spent:
			return {
				"name": row.name,
				"extra_cycles": cint(row.extra_cycles),
				"cycles_consumed": cint(row.cycles_consumed),
				"valid_until": str(row.valid_until),
			}
	return None


# --- Người được duyệt, người nhận thông báo -------------------------------------------------------------


def _delegate():
	return frappe.db.get_single_value("TraceCore Settings", "par_override_delegate")


def is_approver(user=None):
	"""R01, hoặc R02 là người được ủy quyền ``TraceCore Settings.par_override_delegate`` (FR-M8-04.1, A-18 Q6)."""
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	return R01 in roles or (R02 in roles and bool(user) and user == _delegate())


def _r01_users():
	holders = frappe.get_all("Has Role", filters={"role": R01, "parenttype": "User"}, pluck="parent")
	if not holders:
		return []
	return frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1}, pluck="name")


def _recipients():
	users = list(_r01_users())
	delegate = _delegate()
	if delegate and delegate not in users and frappe.db.get_value("User", delegate, "enabled"):
		users.append(delegate)
	return users


def _notify(event, users, subject, doc=None, link=None, content=None):
	"""Báo qua trung tâm thông báo (FEAT-010, A-18 Q11): người nhận theo nghiệp vụ + người R10 cấu hình thêm."""
	notification.emit(event, doc, subject, message=content, users=users, link=link)


# --- Đề nghị ------------------------------------------------------------------------------------------


def request(set_unit, reason, station=None):
	"""R04 đề nghị ghi đè cho bộ đã hết cơ số; trả Par Override ở trạng thái Requested (FR-M8-04, AC-4)."""
	doc = frappe.get_doc({"doctype": DOCTYPE, "set_unit": set_unit, "reason": reason, "station": station})
	doc.insert(ignore_permissions=True)
	return doc


def validate(doc):
	"""Luật của một Par Override; gọi từ ``ParOverride.validate``."""
	if doc.is_new():
		_prepare(doc)
	else:
		guard_changes(doc)


def _prepare(doc):
	"""Đề nghị mới: lý do, bộ phải đã hết cơ số, chưa có đề nghị/ghi đè khác; chụp mức dùng cơ số lúc đề nghị."""
	from tracecore.par import check

	doc.reason = cstr(doc.reason).strip()
	if not doc.reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason was entered for the override request."),
			_("Enter why the set is still needed although it reached its cycle limit."),
		)
	unit = frappe.db.get_value("Set Unit", doc.set_unit, SET_FIELDS, as_dict=True)
	if not unit:
		frappe.throw(_("Set Unit {0} not found.").format(doc.set_unit), frappe.DoesNotExistError)
	open_name = pending_for(unit.name)
	active = active_for(unit.name, unit.current_cycle_no)
	if open_name or active:
		raise _blocked(
			"OVERRIDE_PENDING",
			_("Override already requested"),
			_("Set {0} already has override {1}.").format(unit.name, open_name or active["name"]),
			_("Wait for R01 to decide, or pack the set within the approved override."),
		)
	par = check.evaluate(dict(unit))
	if par["state"] != "blocked" and unit.status != step_gate.END_OF_LIFE:
		raise _blocked(
			"PAR_NOT_EXCEEDED",
			_("Set has not reached its cycle limit"),
			_("Set {0} has used {1} of {2} cycles.").format(unit.name, par["cycles_used"], par["max_cycles"]),
			_("Pack the set normally; an override is needed only after the limit is reached."),
		)
	step_gate.end_of_life(
		unit.name, check.EOL_REASON
	)  # đề nghị trước khi T4 kịp chặn: bộ vẫn phải Hết vòng đời
	doc.update(
		{
			"status": "Requested",
			"requested_by": doc.requested_by or frappe.session.user,
			"requested_at": now_datetime(),
			"cycles_used": par["cycles_used"],
			"max_cycles": par["max_cycles"],
			"exceeded_instruments": "\n".join(
				f"{row['instrument_name']} ({row['instrument']}): {row['max_cycles']}"
				for row in par["instruments"]
				if row["state"] == "blocked"
			)
			or None,
		}
	)


def after_insert(doc):
	"""Thông báo R01 (và R02 được ủy quyền) có đề nghị mới (A-18 Q11)."""
	_notify(
		"PAR_OVERRIDE_REQUESTED",
		_recipients(),
		_("Override requested for set {0}").format(doc.set_unit),
		doc=doc,
		content=doc.reason,
	)


def guard_changes(doc):
	"""Chỉ dịch vụ được đổi quyết định và bộ đếm (cờ ``flags.tc_par_override``); sửa tay trên form bị chặn."""
	if doc.flags.get(FLAG) or doc.docstatus == 2:
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = [field for field in PROTECTED if cstr(before.get(field)) != cstr(doc.get(field))]
	if changed:
		frappe.throw(
			_("Override fields are changed only by approving or rejecting: {0}").format(", ".join(changed))
		)


def guard_submit(doc):
	if not doc.flags.get(FLAG):
		frappe.throw(_("Approve or reject the override request instead of submitting it."))


def before_cancel(doc):
	"""R01 thu hồi ghi đè đã duyệt: trạng thái Cancelled (A-18 Q8)."""
	doc.status = "Cancelled"


# --- Duyệt, từ chối -----------------------------------------------------------------------------------


def _pending_doc(name):
	if not name or not frappe.db.exists(DOCTYPE, name):
		raise _blocked(
			"OVERRIDE_NOT_FOUND",
			_("Override not found"),
			_("Override {0} does not exist.").format(name or "-"),
			_("Open the override from the list."),
		)
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)
	if doc.docstatus != 0 or doc.status != "Requested":
		raise _blocked(
			"OVERRIDE_NOT_PENDING",
			_("Override was already decided"),
			_("Override {0} is {1}.").format(doc.name, _(doc.status, context="Par Override")),
			_("Refresh the list; only a requested override can be approved or rejected."),
		)
	return doc


def _require_approver():
	if not is_approver():
		raise _blocked(
			"APPROVER_NOT_ALLOWED",
			_("Not allowed to decide"),
			_("Only R01, or the R02 user delegated by R10, can approve or reject an override."),
			_("Ask R01 to decide this request."),
		)


def _need_reason(reason):
	reason = cstr(reason).strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason was entered for the decision."),
			_("Enter why the override is approved or rejected."),
		)
	return reason


def _extra_cycles(value):
	text = cstr(value).strip()
	if isinstance(value, bool) or not text.isdigit() or int(text) < 1:
		raise _blocked(
			"EXTRA_CYCLES_INVALID",
			_("Extra cycles are not valid"),
			_("{0} is not a whole number of cycles of at least 1.").format(text or "-"),
			_("Enter how many reprocessing cycles beyond the limit are allowed."),
		)
	return int(text)


def _valid_until(value):
	try:
		day = getdate(value) if value else None
	except Exception:
		day = None
	if day is None or day < getdate(today()):
		raise _blocked(
			"VALID_UNTIL_INVALID",
			_("Valid-until date is not valid"),
			_("{0} is empty, not a date, or already past.").format(cstr(value) or "-"),
			_("Enter a date from today on."),
		)
	return day


def _verify_pin(pin):
	"""PIN 6 số của Employee gắn với user đang duyệt (A-18 Q7); sai 3 lần khóa 5 phút."""
	employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")
	if not employee:
		raise _blocked(
			"PIN_INVALID",
			_("PIN is incorrect"),
			_("No employee record with a PIN belongs to this account."),
			_("Ask R10 to link your employee record and set your PIN."),
		)
	station_auth.verify_pin(employee, pin)
	return employee


def _decide(doc, status, reason, pin, extra=None, until=None):
	employee = _verify_pin(pin)
	doc.flags[FLAG] = True
	doc.flags.ignore_permissions = (
		True  # người duyệt đã được kiểm (`_require_approver`, PIN); chỉ dịch vụ này ghi sổ
	)
	doc.flags.tc_audit_reason = reason
	doc.update(
		{
			"status": status,
			"decision_reason": reason,
			"decided_by": frappe.session.user,
			"decided_by_employee": employee,
			"decided_at": now_datetime(),
			"pin_verified": 1,
		}
	)
	if extra:
		doc.update({"extra_cycles": extra, "valid_until": until})
	doc.submit()
	return doc


def approve(name, extra_cycles, valid_until, reason, pin):
	"""R01/R02 ủy quyền duyệt: số chu trình thêm, thời hạn, lý do, PIN → Approved; bộ Hết vòng đời mở lại (AC-6)."""
	doc = _pending_doc(name)
	_require_approver()
	reason = _need_reason(reason)
	extra, until = _extra_cycles(extra_cycles), _valid_until(valid_until)
	_decide(doc, "Approved", reason, pin, extra, until)
	if frappe.db.get_value("Set Unit", doc.set_unit, "status") == step_gate.END_OF_LIFE:
		step_gate.reopen_after_override(doc.set_unit, doc.name)
	return doc


def reject(name, reason, pin):
	"""Từ chối đề nghị (lý do + PIN): Rejected; bộ giữ Hết vòng đời (AC-10)."""
	doc = _pending_doc(name)
	_require_approver()
	return _decide(doc, "Rejected", _need_reason(reason), pin)


# --- Tiêu thụ, hết hiệu lực ---------------------------------------------------------------------------


def consume(pack, ctx):
	"""Hook ``tracecore_after_cycle_id``: một Cycle ID sinh dưới ghi đè trừ một chu trình (khác ``cycle_no``)."""
	par = (ctx or {}).get("par") or {}
	active = par.get("override") if par.get("state") == "override" else None
	if not active:
		return
	doc = frappe.get_doc(DOCTYPE, active["name"], for_update=True)
	cycle_no = cint(pack.cycle_no)
	if cint(doc.last_cycle_no) == cycle_no or doc.docstatus != 1:
		return
	doc.flags[FLAG] = True
	doc.cycles_consumed = cint(doc.cycles_consumed) + 1
	doc.last_cycle_no = cycle_no
	if doc.cycles_consumed >= cint(doc.extra_cycles):
		doc.update({"status": "Expired", "expiry_cause": "Cycles Used", "expired_at": now_datetime()})
	doc.save(ignore_permissions=True)


def expire_overdue():
	"""Cron 00:00: ghi đè Approved quá ``valid_until`` → Expired (FR-M8-04.2, UC-31 A2)."""
	names = frappe.get_all(
		DOCTYPE,
		filters={"docstatus": 1, "status": "Approved", "valid_until": ["<", today()]},
		pluck="name",
	)
	for name in names:
		doc = frappe.get_doc(DOCTYPE, name, for_update=True)
		doc.flags[FLAG] = True
		doc.update({"status": "Expired", "expiry_cause": "Date Passed", "expired_at": now_datetime()})
		doc.save(ignore_permissions=True)


def notify_monthly_report():
	"""Cron hằng tháng: báo R01 xem báo cáo ghi đè tháng trước (FR-M8-04.3, A-18 Q11)."""
	first = get_first_day(add_months(getdate(today()), -1))
	last = get_last_day(first)
	link = f"/app/query-report/Par Override Report?from_date={first}&to_date={last}"
	_notify(
		"PAR_OVERRIDE_REPORT",
		_r01_users(),
		_("Par override report for {0}/{1} is ready").format(f"{first.month:02d}", first.year),
		link=link,
	)
