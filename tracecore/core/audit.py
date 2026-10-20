"""Ghi Audit Log cho mọi thao tác nghiệp vụ (ADR-008, NFR-SEC-03, F-6)."""

import frappe
from frappe import _
from frappe.model import default_fields, no_value_fields, table_fields
from frappe.utils import cstr, now_datetime

SKIP_FIELDTYPES = (*no_value_fields, "Password")
SKIP_FIELDNAMES = frozenset(default_fields) | {"_user_tags", "_comments", "_assign", "_liked_by", "_seen"}
EVENT_ACTIONS = {
	"after_insert": "Create",
	"on_update": "Update",
	"on_update_after_submit": "Update",
	"on_submit": "Submit",
	"on_cancel": "Cancel",
}


class AuditLogImmutableError(frappe.ValidationError):
	pass


def _header(name):
	try:
		return frappe.get_request_header(name)
	except Exception:
		return None


def _as_json(value):
	return None if value is None else frappe.as_json(value)


def snapshot(doc):
	"""Giá trị các trường dữ liệu của doc; bỏ trường Password và trường meta chuẩn.

	Trường bảng con chụp thành danh sách dòng (cùng quy tắc), để Update ghi được thay đổi của bảng con.
	"""
	result = {}
	for df in doc.meta.fields:
		if df.fieldname in SKIP_FIELDNAMES:
			continue
		if df.fieldtype in table_fields:
			result[df.fieldname] = [snapshot(row) for row in doc.get(df.fieldname) or []]
		elif df.fieldtype not in SKIP_FIELDTYPES:
			result[df.fieldname] = doc.get(df.fieldname)
	return result


def log(
	action,
	ref_doctype=None,
	ref_name=None,
	old=None,
	new=None,
	reason=None,
	station=None,
	device=None,
	client_ts=None,
):
	"""Ghi một dòng Audit Log; trạm/thiết bị/request lấy từ header nếu không truyền."""
	station = station or _header("X-TC-Station")
	if station and not frappe.db.exists("Zone Station", station):
		station = None
	doc = frappe.get_doc(
		{
			"doctype": "Audit Log",
			"timestamp": now_datetime(),
			"user": frappe.session.user,
			"station": station,
			"device": device or _header("X-TC-Device"),
			"request_id": _header("X-Request-ID"),
			"action": action,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"old_value": _as_json(old),
			"new_value": _as_json(new),
			"reason": reason,
			"client_ts": client_ts,
		}
	)
	# Bản ghi tham chiếu có thể đang tạo trong cùng transaction
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _diff(before, after):
	keys = [k for k in after if cstr(before.get(k)) != cstr(after.get(k))]
	return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def on_document_event(doc, method):
	"""Handler doc_events: after_insert/on_update/on_submit/on_cancel → Audit Log."""
	action = EVENT_ACTIONS.get(method)
	if not action or (method == "on_update" and doc.flags.in_insert):
		return
	if action == "Create":
		log("Create", doc.doctype, doc.name, new=snapshot(doc))
	elif action == "Update":
		before = doc.get_doc_before_save()
		old, new = _diff(snapshot(before) if before else {}, snapshot(doc))
		if new:
			log("Update", doc.doctype, doc.name, old=old, new=new)
	else:
		log(action, doc.doctype, doc.name, new={"docstatus": doc.docstatus})


def block_delete(doc, method):
	"""Handler on_trash: chứng từ/danh mục nghiệp vụ không được xóa."""
	frappe.throw(_("{0} {1} cannot be deleted.").format(_(doc.doctype), doc.name))
