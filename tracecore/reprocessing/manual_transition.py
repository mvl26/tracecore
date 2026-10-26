"""Chuyển trạng thái bộ/gói thủ công khi hệ thống lỗi (FEAT-004, A-37 b, FR-M2-00.3).

Chỉ R02, bắt buộc lý do và số ticket sự cố. Bộ đi qua ``core.step_gate.force_status`` (ADR-005), gói qua dịch vụ kho
``storage.force_status``. Mỗi lần chuyển ghi Audit Log "Override" (lý do kèm ticket) và tự tạo một Incident CAPA loại
Khác để R02 phân tích nguyên nhân.
"""

import frappe
from frappe import _
from frappe.utils import cstr

from tracecore.core import audit, step_gate
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import incidents, storage

ROLE = "TC R02"
ACTION = "Override"


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _check(reason, ticket):
	if ROLE not in frappe.get_roles():
		raise _blocked(
			"TRANSITION_NOT_ALLOWED",
			_("Not allowed"),
			_("Only R02 can change a status by hand."),
			_("Ask R02 to do this step."),
		)
	reason, ticket = cstr(reason).strip(), cstr(ticket).strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason was entered for the manual status change."),
			_("Enter why the status is changed by hand."),
		)
	if not ticket:
		raise _blocked(
			"TICKET_REQUIRED",
			_("Incident ticket is required"),
			_("No incident ticket number was entered for the manual status change."),
			_("Enter the ticket number of the system incident."),
		)
	return reason, ticket


def _invalid(doctype, name, current, target):
	return _blocked(
		"STATUS_INVALID",
		_("Status change not allowed"),
		_("{0} {1} cannot be moved from {2} to {3} by hand.").format(
			_(doctype), name, _(current or "-", context=doctype), _(target or "-", context=doctype)
		),
		_("Choose another status."),
	)


def _record(doctype, name, old, new, reason, ticket, links):
	text = f"{ticket}: {reason}"
	audit.log(ACTION, doctype, name, old={"status": old}, new={"status": new}, reason=text)
	incident = incidents.create(
		{
			"incident_type": "Other",
			"severity": "Medium",
			"description": _("Manual status change of {0} {1} from {2} to {3}, ticket {4}: {5}").format(
				_(doctype),
				name,
				_(old, context=doctype),
				_(new, context=doctype),
				ticket,
				reason,
			),
			**links,
		},
		auto=True,
	)
	return {"name": name, "old_status": old, "status": new, "incident": incident.name}


def force_set_status(set_unit, status, reason, ticket):
	"""R02 chuyển trạng thái Set Unit. Trả ``{"name", "old_status", "status", "incident"}``."""
	reason, ticket = _check(reason, ticket)
	current = frappe.db.get_value("Set Unit", set_unit, "status", for_update=True)
	if current is None:
		frappe.throw(_("Set Unit {0} not found.").format(set_unit or "-"), frappe.DoesNotExistError)
	if status not in step_gate.FORCE_TARGETS or status == current or current in step_gate.NOT_RETIRABLE:
		raise _invalid("Set Unit", set_unit, current, status)
	step_gate.force_status(set_unit, status, f"{ticket}: {reason}")
	return _record("Set Unit", set_unit, current, status, reason, ticket, {"set_unit": set_unit})


def force_pack_status(pack, status, reason, ticket, void_reason=None):
	"""R02 chuyển trạng thái Pack; tới Void cần ``void_reason``. Trả ``{"name", "old_status", "status", "incident"}``."""
	reason, ticket = _check(reason, ticket)
	row = frappe.db.get_value("Pack", pack, ["status", "docstatus", "set_unit"], as_dict=True)
	if not row:
		frappe.throw(_("Pack {0} not found.").format(pack or "-"), frappe.DoesNotExistError)
	if (
		row.docstatus != 1
		or row.status not in storage.FORCE_PACK_FROM
		or status not in storage.FORCE_PACK_TARGETS
		or status == row.status
	):
		raise _invalid("Pack", pack, row.status, status)
	if status == "Void" and not void_reason:
		raise _blocked(
			"VOID_REASON_REQUIRED",
			_("Void reason is required"),
			_("Choose why pack {0} is void.").format(pack),
			_("Choose the void reason, then try again."),
		)
	storage.force_status(pack, status, void_reason=void_reason, note=f"{ticket}: {reason}")
	return _record("Pack", pack, row.status, status, reason, ticket, {"pack": pack, "set_unit": row.set_unit})
