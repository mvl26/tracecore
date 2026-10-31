"""GTIN-14 của loại bộ (A-76): cấp bù có xem trước, đổi GTIN đã khóa, trạng thái cho form.

Công thức và bộ đếm ở ``tracecore.core.gs1`` và ``tracecore.core.code_registry``; ở đây chỉ có luật của loại bộ. Loại bộ
mượn ``LN#####`` mang GTIN của hãng (A-38): không tự cấp, không cấp bù, không cảnh báo khác prefix. Pack đọc theo tên
DocType, không import M2.
"""

import re

import frappe
from frappe import _
from frappe.utils import cstr

from tracecore.core import audit, code_registry, gs1
from tracecore.core.errors import Block, BlockedError

SET_TYPE = "Instrument Set Type"
PACK = "Pack"
ADMIN_ROLE = "TC R10"
LOANER_TYPE = re.compile(r"LN\d{5}")
REASON_MAX = 500


def is_loaner_type(name):
	return bool(LOANER_TYPE.fullmatch(cstr(name)))


def under_declared_prefix(gtin, prefix):
	"""GTIN có mã doanh nghiệp `prefix` ngay sau số chỉ thị."""
	return cstr(gtin)[1:].startswith(prefix)


def is_foreign(name, gtin):
	"""Loại bộ của viện mang GTIN không thuộc prefix đã khai: chỉ cảnh báo, không chặn."""
	prefix = gs1.declared_company_prefix()
	return bool(prefix and gtin and not is_loaner_type(name) and not under_declared_prefix(gtin, prefix))


def pack_count(name, gtin=None):
	filters = {"set_type": name}
	if gtin:
		filters["gtin"] = gtin
	return frappe.db.count(PACK, filters)


def is_locked(name, gtin):
	"""GTIN đã nằm trên Cycle ID của gói thì không đổi bằng đường lưu thường (D6, A-76)."""
	return bool(pack_count(name, gtin))


def _require_admin():
	if ADMIN_ROLE not in frappe.get_roles():
		raise frappe.PermissionError(_("Only TC R10 can do this."))


def _reason(reason):
	reason = cstr(reason).strip()[:REASON_MAX]
	if not reason:
		raise BlockedError(
			Block(
				"REASON_REQUIRED",
				_("GTIN-14 not changed"),
				_("This set type already has packs labelled with its GTIN-14."),
				_("Enter the reason for the change, then try again."),
			)
		)
	return reason


def _candidates():
	"""Loại bộ của viện đang trống GTIN hoặc mang mã thử dải 952 chưa thuộc prefix đã khai, theo mã loại bộ."""
	prefix = gs1.declared_company_prefix()
	rows = []
	for row in frappe.get_all(SET_TYPE, fields=["name", "set_type_name", "gtin"], order_by="name"):
		if is_loaner_type(row.name):
			continue
		if not row.gtin or (gs1.is_test_gtin(row.gtin) and not under_declared_prefix(row.gtin, prefix)):
			rows.append(row)
	return rows


def backfill_preview():
	"""Danh sách sẽ cấp và mã dự kiến; không ghi gì. ``next_ref`` là mốc để xác nhận biết danh sách đã cũ chưa."""
	_require_admin()
	rows = _candidates()
	state = code_registry.gtin_range()
	if not state:
		raise BlockedError(code_registry.prefix_not_declared_block())
	result = []
	for row, new_gtin in zip(rows, code_registry.peek_gtins(SET_TYPE, len(rows)), strict=True):
		result.append(
			{
				"set_type": row.name,
				"set_type_name": row.set_type_name,
				"current_gtin": row.gtin or None,
				"is_demo": bool(row.gtin),
				"pack_count": pack_count(row.name, row.gtin) if row.gtin else 0,
				"new_gtin": new_gtin,
			}
		)
	return {
		"rows": result,
		"next_ref": state["next_ref"],
		"prefix": state["prefix"],
		"needs_reason": any(row["pack_count"] for row in result),
	}


def backfill(set_types, next_ref, reason=None):
	"""Cấp GTIN-14 đúng danh sách đã xem, trong một transaction; danh sách hoặc bộ đếm đã đổi thì không ghi gì."""
	_require_admin()
	state = code_registry.gtin_range(lock=True)
	if not state:
		raise BlockedError(code_registry.prefix_not_declared_block())
	rows = _candidates()
	if state["next_ref"] != next_ref or {row.name for row in rows} != set(set_types):
		raise BlockedError(
			Block(
				"GTIN_BACKFILL_STALE",
				_("GTIN-14 not issued"),
				_("The list of set types or the counter changed after the preview was opened."),
				_("Close this window and open the preview again."),
			)
		)
	code_registry.peek_gtins(SET_TYPE, len(rows))
	if any(row.gtin and pack_count(row.name, row.gtin) for row in rows):
		reason = _reason(reason)
	note = reason or _("GTIN-14 backfill")
	for row in rows:
		new_gtin = code_registry.next_gtin(SET_TYPE, row.name)
		frappe.db.set_value(SET_TYPE, row.name, "gtin", new_gtin)
		audit.log("Update", SET_TYPE, row.name, old={"gtin": row.gtin}, new={"gtin": new_gtin}, reason=note)
	return {"issued": len(rows), "next_ref": code_registry.gtin_range()["next_ref"]}


def change_locked(set_type, gtin, reason):
	"""R10 đổi GTIN đã in lên nhãn, có lý do (Audit Log qua doc_events). Mã cũ vào sổ để không cấp lại."""
	_require_admin()
	doc = frappe.get_doc(SET_TYPE, set_type)
	old = doc.gtin
	if not is_locked(doc.name, old):
		raise BlockedError(
			Block(
				"GTIN_NOT_LOCKED",
				_("GTIN-14 not changed"),
				_("The GTIN-14 of set type {0} is not locked.").format(doc.name),
				_("Edit it on the form."),
			)
		)
	reason = _reason(reason)
	gtin = cstr(gtin).strip()
	if not gtin:
		frappe.throw(_("GTIN-14 must be 14 digits with a valid check digit."))
	doc.gtin = gtin
	doc.flags.tc_gtin_unlock = True
	doc.flags.tc_audit_reason = reason
	doc.save()
	code_registry.retire_gtin(old, SET_TYPE, doc.name)
	return doc.gtin


def context(name):
	"""Trạng thái GTIN cho form loại bộ; RPC ghi vẫn kiểm lại."""
	gtin = frappe.db.get_value(SET_TYPE, name, "gtin")
	locked = is_locked(name, gtin) if gtin else False
	can_unlock = locked and ADMIN_ROLE in frappe.get_roles()
	suggested = None
	if can_unlock and code_registry.gtin_range():
		try:
			suggested = code_registry.peek_gtins(SET_TYPE, 1)[0]
		except BlockedError:
			suggested = None
	return {
		"prefix": gs1.declared_company_prefix(),
		"locked": locked,
		"pack_count": pack_count(name, gtin) if gtin else 0,
		"can_unlock": can_unlock,
		"foreign_prefix": is_foreign(name, gtin),
		"suggested": suggested,
	}
