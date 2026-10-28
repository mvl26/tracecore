"""RPC tracecore.v1.competency.* — ma trận năng lực SCR-20 trên Desk (FEAT-037, FR-M4-03, API-M4-02).

Quy tắc ở `tracecore.hr.competency`. Lỗi nghiệp vụ trả body ``ok: false`` (Audit Log ``Reject``), không ném.
"""

import frappe
from frappe import _

from tracecore.core.errors import BlockedError
from tracecore.hr import competency
from tracecore.v1._common import reject_block


def _require_login():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to open TraceCore."), frappe.PermissionError)


def _types(value):
	"""Danh sách loại chứng chỉ, gửi dạng JSON hoặc mảng; sai kiểu thì báo lỗi validation."""
	if not value:
		return []
	try:
		value = frappe.parse_json(value) if isinstance(value, str) else value
	except ValueError:
		value = None
	if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
		frappe.throw(_("required_certificates must be a list of certificate types."), frappe.ValidationError)
	return value


@frappe.whitelist(methods=["GET"])
def matrix(zone=None):
	"""Ma trận nhân viên theo trạm. Trả ``{"ok", "stations", "employees", "can_edit"}``."""
	_require_login()
	try:
		return {"ok": True, **competency.matrix(zone or None)}
	except BlockedError as error:
		return reject_block(error.block, "Station Competency")


@frappe.whitelist(methods=["POST"])
def grant(
	employee, station, valid_until, valid_from=None, required_certificates=None, is_temporary=0, reason=None
):
	"""Gán năng lực `station` cho `employee`; quyền tạm cần `reason` và tối đa 24 giờ."""
	_require_login()
	types = _types(required_certificates)
	try:
		doc = competency.grant(
			employee,
			station,
			valid_until,
			valid_from=valid_from,
			required_certificates=types,
			is_temporary=is_temporary,
			reason=reason,
		)
	except BlockedError as error:
		return reject_block(error.block, "Station Competency", employee)
	return {"ok": True, "name": doc.name}


@frappe.whitelist(methods=["POST"])
def revoke(name, reason=None):
	"""Thu hồi một năng lực (giữ bản ghi); lý do bắt buộc."""
	_require_login()
	try:
		doc = competency.revoke(name, reason)
	except BlockedError as error:
		return reject_block(error.block, "Station Competency", name)
	return {"ok": True, "name": doc.name}
