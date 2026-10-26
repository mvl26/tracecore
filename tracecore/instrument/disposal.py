"""Thanh lý bộ (FEAT-004, A-37 a, FR-M1-05.2, FR-M1-06): R02 đề nghị kèm lý do, R01 duyệt/từ chối bằng PIN trên Desk.

Bộ đề nghị được: Hết vòng đời, hoặc Xử lý lại do Assembly Record của chu trình hiện hành rẽ nhánh Thanh lý (T3).
Duyệt → ``step_gate.dispose`` (Đã thanh lý, không quay lại) và vô hiệu Set ID trong Code Registry (không cấp lại).
Trường ``disposal_*`` của Set Unit chỉ ghi ở đây (cờ ``flags.tc_disposal``) nên Audit Log Update ghi đủ lịch sử.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, now_datetime

from tracecore.core import code_registry, station_auth, step_gate
from tracecore.core.errors import Block, BlockedError

REQUESTER = "TC R02"
APPROVER = "TC R01"
REQUESTED = "Requested"
DOCTYPE = "Set Unit"


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _require_role(role, action):
	if role not in frappe.get_roles():
		raise _blocked(
			"DISPOSAL_NOT_ALLOWED",
			_("Not allowed"),
			_("Only {0} can {1}.").format(role, action),
			_("Ask {0} to do this step.").format(role),
		)


def _text(value, what):
	value = cstr(value).strip()
	if not value:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No {0} was entered.").format(what),
			_("Enter the {0}, then try again.").format(what),
		)
	return value


def _users_with(role):
	holders = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
	if not holders:
		return []
	return frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1}, pluck="name")


def _notify(users, subject, set_unit):
	"""Thông báo chuông Desk (Notification Log); email/SMS thuộc FEAT-010."""
	for user in dict.fromkeys(users):
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"from_user": frappe.session.user,
				"type": "Alert",
				"subject": subject,
				"document_type": DOCTYPE,
				"document_name": set_unit,
			}
		).insert(ignore_permissions=True)


def _unit(set_unit):
	if not set_unit or not frappe.db.exists(DOCTYPE, set_unit):
		frappe.throw(_("Set Unit {0} not found.").format(set_unit or "-"), frappe.DoesNotExistError)
	return frappe.get_doc(DOCTYPE, set_unit, for_update=True)


def _sent_to_disposal(unit):
	"""Assembly Record đã ghi sổ của chu trình hiện hành rẽ nhánh Thanh lý (đọc theo tên DocType, không import M2)."""
	return bool(
		frappe.db.exists(
			"Assembly Record",
			{
				"set_unit": unit.name,
				"cycle_no": cint(unit.current_cycle_no),
				"branch": "Disposal",
				"docstatus": 1,
			},
		)
	)


def eligible(unit):
	"""Bộ đề nghị thanh lý được: Hết vòng đời, hoặc Xử lý lại vì rẽ nhánh Thanh lý ở T3."""
	if unit.status == step_gate.END_OF_LIFE:
		return True
	return unit.status == "Reprocess" and _sent_to_disposal(unit)


def _save(unit, **fields):
	unit.update(fields)
	unit.flags.tc_disposal = True
	unit.save(ignore_permissions=True)


def request(set_unit, reason):
	"""R02 đề nghị thanh lý kèm lý do; thông báo R01. Trả ``{"set_id", "disposal_status"}``."""
	_require_role(REQUESTER, _("request a disposal"))
	reason = _text(reason, _("disposal reason"))
	unit = _unit(set_unit)
	if unit.disposal_status == REQUESTED:
		raise _blocked(
			"DISPOSAL_PENDING",
			_("Disposal already requested"),
			_("Set {0} is waiting for R01 to decide on its disposal.").format(unit.name),
			_("Wait for the decision of R01."),
		)
	if not eligible(unit):
		raise _blocked(
			"DISPOSAL_NOT_ELIGIBLE",
			_("Set cannot be disposed"),
			_("Set {0} is {1}; only a set at end of life or sent to disposal at T3 can be disposed.").format(
				unit.name, _(unit.status, context=DOCTYPE)
			),
			_("Check the set status before requesting a disposal."),
		)
	_save(
		unit,
		disposal_status=REQUESTED,
		disposal_reason=reason,
		disposal_requested_by=frappe.session.user,
		disposal_requested_at=now_datetime(),
		disposal_decided_by=None,
		disposal_decided_at=None,
		disposal_decision_note=None,
	)
	_notify(
		_users_with(APPROVER), _("Disposal requested for set {0}: {1}").format(unit.name, reason), unit.name
	)
	return {"set_id": unit.name, "disposal_status": unit.disposal_status}


def _verify_pin(pin):
	"""PIN 6 số của Employee gắn với user đang duyệt; sai 3 lần khóa 5 phút."""
	employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")
	if not employee:
		raise _blocked(
			"PIN_INVALID",
			_("PIN is incorrect"),
			_("No employee record with a PIN belongs to this account."),
			_("Ask R10 to link your employee record and set your PIN."),
		)
	station_auth.verify_pin(employee, pin)


def _pending(set_unit, note, pin):
	_require_role(APPROVER, _("decide on a disposal"))
	note = _text(note, _("decision note"))
	unit = _unit(set_unit)
	if unit.disposal_status != REQUESTED:
		raise _blocked(
			"DISPOSAL_NOT_PENDING",
			_("No disposal request"),
			_("Set {0} has no disposal request waiting for a decision.").format(unit.name),
			_("Ask R02 to request the disposal first."),
		)
	_verify_pin(pin)
	return unit, note


def _decide(unit, status, note):
	_save(
		unit,
		disposal_status=status,
		disposal_decided_by=frappe.session.user,
		disposal_decided_at=now_datetime(),
		disposal_decision_note=note,
	)
	_notify(
		[unit.disposal_requested_by] if unit.disposal_requested_by else [],
		_("Disposal of set {0}: {1}").format(unit.name, _(status, context=DOCTYPE)),
		unit.name,
	)


def approve(set_unit, note, pin):
	"""R01 duyệt bằng PIN: bộ Đã thanh lý, Set ID vô hiệu vĩnh viễn. Trả ``{"set_id", "status", "disposal_status"}``."""
	unit, note = _pending(set_unit, note, pin)
	if not eligible(unit):
		raise _blocked(
			"DISPOSAL_NOT_ELIGIBLE",
			_("Set cannot be disposed"),
			_("Set {0} is {1}; it can no longer be disposed.").format(
				unit.name, _(unit.status, context=DOCTYPE)
			),
			_("Reject the request and ask R02 to check the set."),
		)
	_decide(unit, "Approved", note)
	reason = f"{unit.disposal_reason} / {note}"
	step_gate.dispose(unit.name, reason)
	code_registry.disable(unit.name, reason)
	return {"set_id": unit.name, "status": step_gate.DISPOSED, "disposal_status": "Approved"}


def reject(set_unit, note, pin):
	"""R01 từ chối bằng PIN kèm ghi chú; bộ giữ nguyên trạng thái. Trả ``{"set_id", "status", "disposal_status"}``."""
	unit, note = _pending(set_unit, note, pin)
	_decide(unit, "Rejected", note)
	return {"set_id": unit.name, "status": unit.status, "disposal_status": "Rejected"}
