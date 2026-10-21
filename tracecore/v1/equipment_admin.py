"""RPC tracecore.v1.equipment_admin.*: thao tác quản trị thiết bị từ Desk (SCR-21, FEAT-038 Task 5).

`retire` (nút "Ngừng sử dụng", Q5) và `copy_program` (nút "Sao chép sang máy khác", FR-M5-02). Chỉ R10, R02 và
System Manager; `set_status` lưu bằng ignore_permissions nên quyền được kiểm ở đây TRƯỚC mọi thao tác ghi.
Từ chối nghiệp vụ: body chuẩn ``{"ok": false, "error"}`` + mã HTTP + Audit Log `Reject` (`reject_block`).
"""

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block
from tracecore.core.idempotency import idempotent
from tracecore.equipment import programs
from tracecore.equipment.status import set_status
from tracecore.v1._common import BadRequestError, reject_block, require_any_role

ADMIN_ROLES = ("TC R10", "TC R02", "System Manager")
RETIRE_FIELDS = ("name", "status", "retired_on", "retired_reason")
SAVEPOINT = "tc_equipment_admin"


def _text(value, name):
	if value is not None and not isinstance(value, str):
		raise BadRequestError(_("{0} must be text.").format(name))
	return value


@frappe.whitelist(methods=["POST"])
@idempotent
def retire(equipment, reason, client_ts=None):
	"""Cho thiết bị `equipment` ngừng sử dụng (một chiều), bắt buộc `reason`; chỉ từ trạng thái ``Ready``.

	Thành công: ``{"ok": true, "equipment": {name, status, retired_on, retired_reason}}`` (Audit Log Update do hook
	của Equipment ghi). Từ chối: ``REASON_REQUIRED`` (422), ``EQUIPMENT_NOT_FOUND`` (404),
	``EQUIPMENT_NOT_RETIRABLE`` (409: đã ngừng, đang khóa hoặc đang sửa).
	"""
	require_any_role(*ADMIN_ROLES)
	timestamp = parse_client_ts(client_ts)
	equipment = _text(equipment, "equipment")
	reason = (_text(reason, "reason") or "").strip()
	row = frappe.db.get_value("Equipment", equipment, "status", as_dict=True) if equipment else None
	if not row:
		return reject_block(
			Block(
				"EQUIPMENT_NOT_FOUND",
				_("Equipment not found"),
				_("Equipment {0} does not exist in TraceCore.").format(equipment or "-"),
				_("Check the QR code on the equipment or call R10."),
			),
			"Equipment",
			equipment,
			client_ts=timestamp,
		)
	if not reason:
		return reject_block(
			Block(
				"REASON_REQUIRED",
				_("Reason is required"),
				_("A reason is required to retire equipment."),
				_("Enter the reason for retiring this equipment."),
			),
			"Equipment",
			equipment,
			client_ts=timestamp,
		)
	if row.status != "Ready":
		return reject_block(
			Block(
				"EQUIPMENT_NOT_RETIRABLE",
				_("Equipment cannot be retired"),
				_("Equipment {0} is {1}; only equipment that is Ready can be retired.").format(
					equipment, _(row.status, context="Equipment")
				),
				_("Release or finish the current state first, or call R10."),
			),
			"Equipment",
			equipment,
			client_ts=timestamp,
		)
	set_status(equipment, "Retired", reason)
	values = frappe.db.get_value("Equipment", equipment, list(RETIRE_FIELDS), as_dict=True)
	# chuỗi thuần để response lưu (JSON) và response trả lần đầu giống nhau
	return {"ok": True, "equipment": {key: None if v is None else str(v) for key, v in values.items()}}


def _copy_block(error):
	"""Lỗi miền của `programs.copy_program` thành `Block`; lỗi không có mã riêng thành PROGRAM_COPY_INVALID."""
	if isinstance(error, programs.ProgramModelMismatchError):
		code, title, action = (
			"PROGRAM_MODEL_MISMATCH",
			_("Different model"),
			_("Choose equipment of the same manufacturer and model."),
		)
	elif isinstance(error, programs.EquipmentRetiredError):
		code, title, action = (
			"EQUIPMENT_RETIRED",
			_("Equipment retired"),
			_("Choose another machine or call R10."),
		)
	elif isinstance(error, frappe.DuplicateEntryError):
		code, title, action = (
			"PROGRAM_CODE_EXISTS",
			_("Program code already used"),
			_("Enter a different program code."),
		)
	else:
		code, title, action = (
			"PROGRAM_COPY_INVALID",
			_("Program could not be copied"),
			_("Check the target equipment and the new program code, then try again."),
		)
	reason = str(error)
	if code == "PROGRAM_CODE_EXISTS":
		reason = _("Program code {0} is already used.").format(error.args[1] if len(error.args) > 1 else "-")
	return Block(code, title, reason, action)


@frappe.whitelist(methods=["POST"])
@idempotent
def copy_program(program, equipment, new_code, client_ts=None):
	"""Sao chép chương trình `program` sang máy `equipment` (cùng hãng và model) với mã `new_code`.

	Thành công: ``{"ok": true, "program": "<tên chương trình mới>"}``. Từ chối: ``PROGRAM_MODEL_MISMATCH`` (422),
	``EQUIPMENT_RETIRED`` (409), ``PROGRAM_CODE_EXISTS`` (409); lỗi khác của miền (cùng máy, mã sai định dạng…)
	là ``PROGRAM_COPY_INVALID`` (422) mang thông báo đã dịch.
	"""
	require_any_role(*ADMIN_ROLES)
	timestamp = parse_client_ts(client_ts)
	program = _text(program, "program")
	equipment = _text(equipment, "equipment")
	new_code = _text(new_code, "new_code")
	frappe.db.savepoint(SAVEPOINT)
	try:
		name = programs.copy_program(program, equipment, new_code)
	except (frappe.ValidationError, frappe.DuplicateEntryError) as error:
		frappe.db.rollback(save_point=SAVEPOINT)
		frappe.clear_messages()
		return reject_block(_copy_block(error), "Process Program", program, client_ts=timestamp)
	return {"ok": True, "program": name}
