"""Phiên bản dụng cụ theo tập phương pháp tương thích và cảnh báo BOM (FEAT-014; FR-M1-01.3; A-06 I1, I3).

``Instrument.version_no`` tăng đúng 1 khi **tập** phương pháp tương thích đổi (đổi thứ tự, sửa trường khác không
tính; điền phương pháp lần đầu cho dụng cụ cũ chưa có phương pháp cũng không tính). Không có DocType phiên bản:
lịch sử dựng lại từ Audit Log append-only (Create có snapshot đủ, Update có giá trị mới kể cả bảng con).

Khi phiên bản tăng: msgprint cam + một Comment (Info) trên timeline mỗi loại bộ có BOM hiện hành chứa dụng cụ.
Chỉ cảnh báo, không chặn; gói và bộ đang giữa chu trình không bị đụng tới.
"""

import frappe
from frappe import _
from frappe.utils import cint, escape_html

from tracecore.core import audit
from tracecore.instrument import catalog


def _method_labels(methods) -> str:
	labels = [
		_(method, context="Instrument Compatible Method") for method in catalog.ordered_methods(methods)
	]
	return ", ".join(labels) or "-"


def bump_if_methods_changed(doc) -> bool:
	"""Gọi trong ``Instrument.validate``: tăng ``version_no`` một lần nếu tập phương pháp đổi so với bản đã lưu.

	Đặt ``doc.flags.tc_version_bumped`` và ``doc.flags.tc_version_change`` (phiên bản, phương pháp cũ/mới).
	"""
	doc.flags.tc_version_bumped = False
	before = None if doc.is_new() else doc.get_doc_before_save()
	if before is None:
		return False
	old, new = catalog.method_set(before), catalog.method_set(doc)
	if old == new or not old:
		return False
	old_version = cint(before.version_no) or 1
	doc.version_no = old_version + 1
	doc.flags.tc_version_bumped = True
	doc.flags.tc_version_change = {
		"old_version": old_version,
		"new_version": doc.version_no,
		"old_methods": catalog.ordered_methods(old),
		"new_methods": catalog.ordered_methods(new),
	}
	return True


def _set_type_line(row) -> str:
	text = f"{escape_html(row['set_type'])}: {escape_html(row['set_type_name'] or '')}"
	if not row["compatible"]:
		text += " - " + escape_html(_("not compatible (set type method {0})").format(_(row["method"])))
	return f"<li>{text}</li>"


def notify_boms(doc) -> list[dict]:
	"""Gọi trong ``Instrument.on_update`` khi phiên bản vừa tăng: cảnh báo mọi loại bộ có BOM hiện hành chứa dụng cụ.

	Trả (và đặt vào ``doc.flags.tc_bom_usage``) danh sách ``catalog.bom_usage``.
	"""
	usage = catalog.bom_usage(doc.name)
	doc.flags.tc_bom_usage = usage
	if not usage:
		return usage
	change = doc.flags.tc_version_change or {}
	old_version = change.get("old_version") or max(cint(doc.version_no) - 1, 1)
	old_methods = _method_labels(change.get("old_methods") or ())
	new_methods = _method_labels(catalog.method_set(doc))
	user = frappe.session.user
	for row in usage:
		note = (
			_("The set type remains compatible with the instrument.")
			if row["compatible"]
			else _("The set type (method {0}) is not compatible with the instrument.").format(
				_(row["method"])
			)
		)
		content = _(
			"Instrument {0} ({1}) changed from version {2} to {3} by {4}. Compatible methods: {5} → {6}. {7}"
		).format(
			doc.name,
			doc.instrument_name,
			old_version,
			doc.version_no,
			user,
			old_methods,
			new_methods,
			note,
		)
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "Instrument Set Type",
				"reference_name": row["set_type"],
				"content": escape_html(content),
			}
		).insert(ignore_permissions=True)
	intro = _(
		"Instrument {0} is now version {1} (compatible methods: {2}). The current BOM of these set types uses it:"
	).format(doc.name, doc.version_no, new_methods)
	outro = _("Packs and sets already in process are not changed. Review these BOMs.")
	frappe.msgprint(
		f"<p>{escape_html(intro)}</p><ul>{''.join(_set_type_line(row) for row in usage)}</ul>"
		f"<p>{escape_html(outro)}</p>",
		title=_("Instrument version changed"),
		indicator="orange",
	)
	return usage


def _versions(instrument: str) -> list[dict]:
	"""Các phiên bản cũ → mới: ``{version_no, changed_on, changed_by, state}`` (state = trạng thái cuối của phiên bản)."""
	if not frappe.db.exists("Instrument", instrument):
		frappe.throw(_("Instrument {0} not found.").format(instrument), frappe.DoesNotExistError)
	entries = frappe.get_all(
		"Audit Log",
		filters={"ref_doctype": "Instrument", "ref_name": instrument, "action": ["in", ["Create", "Update"]]},
		fields=["action", "timestamp", "user", "new_value"],
		order_by="name asc",
	)
	result, state = [], {}
	for entry in entries:
		values = frappe.parse_json(entry.new_value) or {}
		state = dict(values) if entry.action == "Create" else {**state, **values}
		number = cint(state.get("version_no")) or 1
		if result and result[-1]["version_no"] == number:
			result[-1]["state"] = state
		else:
			result.append(
				{
					"version_no": number,
					"changed_on": entry.timestamp,
					"changed_by": entry.user,
					"state": state,
				}
			)
	if not result:
		# dụng cụ chưa có dòng Audit Log nào (dữ liệu trước khi bật audit): chỉ có phiên bản hiện tại
		doc = frappe.get_doc("Instrument", instrument)
		result.append(
			{
				"version_no": cint(doc.version_no) or 1,
				"changed_on": doc.creation,
				"changed_by": doc.owner,
				"state": audit.snapshot(doc),
			}
		)
	return result


def history(instrument: str) -> list[dict]:
	"""Lịch sử phiên bản cũ → mới: ``{version_no, methods, changed_on, changed_by}`` (A-06 I1)."""
	return [
		{
			"version_no": row["version_no"],
			"methods": catalog.ordered_methods(catalog.method_set(row["state"])),
			"changed_on": row["changed_on"],
			"changed_by": row["changed_by"],
		}
		for row in _versions(instrument)
	]


def snapshot_at(instrument: str, version_no: int) -> dict:
	"""Bản ghi dụng cụ ở phiên bản `version_no` (trạng thái cuối của phiên bản đó), dựng lại từ Audit Log."""
	for row in _versions(instrument):
		if row["version_no"] == cint(version_no):
			return frappe._dict(row["state"])
	frappe.throw(
		_("Instrument {0} has no version {1}.").format(instrument, version_no), frappe.DoesNotExistError
	)
