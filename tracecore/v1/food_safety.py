"""RPC tracecore.v1.food_safety.* — SCR-65 ATTP & truyền thông người bệnh (FEAT-073; FR-M17-01..06; UC-56; A-151).

- ``overview`` (GET): màn WEB trong Page `tc-ksnk` (slug ``attp``). R13 chỉ nhận số liệu tổng hợp.
- ``open_nc``, ``dismiss_nc``, ``dismiss_outbreak`` (POST, ``@idempotent``): R01/R11 quyết định sự cố ngộ độc; lỗi nghiệp
  vụ trả ``{ok: false, error: {code, title, reason, action}}`` để màn hiện ``alert-error`` inline.
- ``outbreak_prefill`` (GET): giá trị điền sẵn form điều tra ổ dịch M14 (A-151 Q1).
- ``publish_material``, ``withdraw_material`` (POST, ``@idempotent``): R01 ban hành / thu hồi tài liệu truyền thông.
- ``material_qr`` (GET): ảnh QR (data URI) trỏ URL cố định của tài liệu.
- ``material_file`` (GET, Guest): file của bản hiện hành — chỉ tài liệu loại Tài liệu truyền thông (A-151 Q3).
"""

import base64

import frappe
from frappe import _

from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.food_safety import dashboard, events
from tracecore.infection_program import procedure_documents as documents
from tracecore.ui import ksnk
from tracecore.v1._common import reject_block

SUMMARY_ONLY_ROLES = frozenset({"TC R13"})
DETAIL_ROLES = frozenset({"TC R01", "TC R11", "System Manager"})
MATERIAL_FIELDS = ["name", "doc_code", "title", "version_no", "status", "issued_on", "withdrawn_reason"]


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == dashboard.SCREEN_SLUG)
	if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(_("You are not allowed to open the food safety screen."), frappe.PermissionError)


def _summary_only():
	roles = set(frappe.get_roles())
	return (
		frappe.session.user != "Administrator"
		and bool(roles & SUMMARY_ONLY_ROLES)
		and not roles & DETAIL_ROLES
	)


def _data_uri(png):
	return "data:image/png;base64," + base64.b64encode(png).decode()


def _materials():
	"""Bản mới nhất (theo số phiên bản) của mỗi mã tài liệu truyền thông, kèm URL cố định và QR."""
	rows = frappe.get_all(
		documents.DOCTYPE,
		filters={"doc_type": documents.MATERIAL_TYPE},
		fields=MATERIAL_FIELDS,
		order_by="doc_code asc, version_no desc, creation desc",
	)
	latest = {}
	for row in rows:
		if row.status == documents.reminders.SUPERSEDED:
			continue
		latest.setdefault(row.doc_code, row)
	result = []
	for row in latest.values():
		row["url"] = documents.material_url(row.doc_code)
		row["qr"] = _data_uri(documents.material_qr_png(row.doc_code))
		result.append(row)
	return result


@frappe.whitelist(methods=["GET"])
def overview():
	"""Dữ liệu SCR-65."""
	_require_screen()
	summary_only = _summary_only()
	result = dashboard.build(summary_only=summary_only)
	if summary_only:
		return result
	result.update(
		{
			"can_decide": events.can_decide(),
			"can_publish": documents.can_publish(),
			"outbreak_ready": events.outbreak_ready(),
			"materials": _materials(),
		}
	)
	return result


def _decide(fn, name, *args, client_ts=None, doctype=events.DOCTYPE):
	timestamp = parse_client_ts(client_ts) if client_ts else None
	try:
		value = fn(name, *args)
	except BlockedError as error:
		return reject_block(error.block, doctype, name, client_ts=timestamp)
	return {"ok": True, "result": value}


@frappe.whitelist(methods=["POST"])
@idempotent
def open_nc(event=None, client_ts=None):
	"""R01/R11 mở NC Food Safety cho sự cố: ``{ok, result: incident}``."""
	return _decide(events.open_nc, event, client_ts=client_ts)


@frappe.whitelist(methods=["POST"])
@idempotent
def dismiss_nc(event=None, reason=None, client_ts=None):
	return _decide(events.dismiss_nc, event, reason, client_ts=client_ts)


@frappe.whitelist(methods=["POST"])
@idempotent
def dismiss_outbreak(event=None, reason=None, client_ts=None):
	return _decide(events.dismiss_outbreak, event, reason, client_ts=client_ts)


@frappe.whitelist(methods=["GET"])
def outbreak_prefill(event=None):
	return events.outbreak_prefill(event)


@frappe.whitelist(methods=["POST"])
@idempotent
def publish_material(name=None, client_ts=None):
	return _decide(documents.publish, name, client_ts=client_ts, doctype=documents.DOCTYPE)


@frappe.whitelist(methods=["POST"])
@idempotent
def withdraw_material(name=None, reason=None, client_ts=None):
	return _decide(documents.withdraw, name, reason, client_ts=client_ts, doctype=documents.DOCTYPE)


@frappe.whitelist(methods=["GET"])
def material_qr(name=None):
	"""QR của tài liệu (in dán tại khoa): ``{url, qr, title, version_no, status}``."""
	doc = frappe.get_doc(documents.DOCTYPE, name)
	doc.check_permission("read")
	return {
		"url": documents.material_url(doc.doc_code),
		"qr": _data_uri(documents.material_qr_png(doc.doc_code)),
		"title": doc.title,
		"doc_code": doc.doc_code,
		"version_no": doc.version_no,
		"status": doc.status,
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def material_file(code=None):
	"""File của bản hiện hành tài liệu truyền thông ``code`` cho người quét QR (không cần đăng nhập)."""
	current = documents.current_material(code or "")
	if current["state"] != "current" or not current.get("file"):
		raise frappe.DoesNotExistError(_("This document is not available."))
	file_name = frappe.db.get_value("File", {"file_url": current["file"]}, "name")
	if not file_name:
		raise frappe.DoesNotExistError(_("This document is not available."))
	file_doc = frappe.get_doc("File", file_name)
	frappe.local.response.filename = file_doc.file_name
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "binary"
