"""Ghi Audit Log cho mọi thao tác nghiệp vụ (ADR-008, NFR-SEC-03, F-6)."""

from decimal import Decimal

import frappe
from frappe import _
from frappe.model import default_fields, no_value_fields, table_fields
from frappe.model.delete_doc import check_if_doc_is_dynamically_linked, check_if_doc_is_linked
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
	entry_mode=None,
):
	"""Ghi một dòng Audit Log; trạm/thiết bị/request lấy từ header nếu không truyền.

	`entry_mode` (Scan / Manual, A-68) chỉ có ở thao tác nhập mã trên trạm."""
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
			"entry_mode": entry_mode,
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


def _comparable(value):
	"""Dạng so sánh của một giá trị snapshot: số nguyên dạng float thành int, mọi giá trị thành chuỗi (``None`` → "");
	dòng bảng con chuẩn hóa từng giá trị, khóa theo thứ tự cố định. Tránh ghi cả bảng con chỉ vì đổi kiểu (1 với 1.0)."""
	if isinstance(value, list):
		return [_comparable(row) for row in value]
	if isinstance(value, dict):
		return {key: _comparable(value[key]) for key in sorted(value)}
	if isinstance(value, float | Decimal) and value == int(value):
		value = int(value)
	return cstr(value)


def _diff(before, after):
	keys = [k for k in after if _comparable(before.get(k)) != _comparable(after.get(k))]
	return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def changes(before, doc) -> dict:
	"""Trường dữ liệu đã đổi giữa `before` và `doc` (cùng quy tắc so sánh như dòng Audit Log Update): ``{trường: mới}``."""
	return _diff(snapshot(before), snapshot(doc))[1]


def on_document_event(doc, method):
	"""Handler doc_events: after_insert/on_update/on_submit/on_cancel → Audit Log.

	Lý do (cột ``reason``) lấy từ ``doc.flags.tc_audit_reason`` nếu dịch vụ ghi đặt (vd. khởi tạo bộ đếm bảo dưỡng).
	"""
	action = EVENT_ACTIONS.get(method)
	if not action or (method == "on_update" and doc.flags.in_insert):
		return
	reason = doc.flags.tc_audit_reason or None
	if action == "Create":
		log("Create", doc.doctype, doc.name, new=snapshot(doc), reason=reason)
	elif action == "Update":
		before = doc.get_doc_before_save()
		old, new = _diff(snapshot(before) if before else {}, snapshot(doc))
		if new:
			log("Update", doc.doctype, doc.name, old=old, new=new, reason=reason)
	else:
		log(action, doc.doctype, doc.name, new={"docstatus": doc.docstatus})


# Danh mục R10 được xóa hẳn khi chưa có giao dịch nào liên kết (FEAT-004, A-37 d, FR-M9-16); người khác chỉ ngừng dùng
MASTER_DOCTYPES = frozenset(
	{
		"Instrument",
		"Instrument Group",
		"Instrument Set Type",
		"Par Level",
		"Sterile Location",
		"Printer",
		"Label Template",
		"Zone Station",
		"Equipment",
		"Process Program",
		"Equipment Type Norm",
	}
)
MASTER_DELETE_ROLE = "TC R10"


def _may_delete_master(doc):
	"""R10 thật (không phải Administrator, vốn mang mọi role) xóa danh mục chưa có giao dịch liên kết."""
	user = frappe.session.user
	if doc.doctype not in MASTER_DOCTYPES or user == "Administrator":
		return False
	if not frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": MASTER_DELETE_ROLE}):
		return False
	check_if_doc_is_linked(doc)
	check_if_doc_is_dynamically_linked(doc)
	return True


def _disable_codes(doc):
	"""Mã đã cấp cho danh mục bị xóa vẫn nằm trong sổ (không cấp lại) nhưng bị vô hiệu."""
	for name in frappe.get_all(
		"Code Registry",
		filters={"ref_doctype": doc.doctype, "ref_name": doc.name, "status": ("!=", "Disabled")},
		pluck="name",
	):
		code = frappe.get_doc("Code Registry", name)
		code.update(
			{
				"status": "Disabled",
				"disabled_reason": _("{0} {1} deleted").format(_(doc.doctype), doc.name),
				"disabled_on": now_datetime(),
			}
		)
		code.save(ignore_permissions=True)


def block_delete(doc, method):
	"""Handler on_trash: chứng từ/danh mục nghiệp vụ không được xóa; trừ danh mục chưa dùng do R10 xóa (ghi Audit)."""
	if _may_delete_master(doc):
		if (
			not doc.flags.tc_delete_logged
		):  # handler có thể chạy hai lần (hook doc_events và on_trash của class)
			doc.flags.tc_delete_logged = True
			log("Delete", doc.doctype, doc.name, old=snapshot(doc))
			_disable_codes(doc)
		return
	frappe.throw(_("{0} {1} cannot be deleted.").format(_(doc.doctype), doc.name))
