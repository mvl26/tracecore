"""RPC tracecore.v1.set_type.*: đọc BOM theo phiên bản cho trạm/PDA (cache + etag), danh sách phiên bản, so sánh hai
phiên bản, dữ liệu form Desk của loại bộ (FEAT-015 Task 6; S10, S11; FR-M1-03, FR-M1-04.3, F-17) và tải phiếu kiểm
đếm PDF (Task 7, S9).

Chỉ đọc: ``@frappe.whitelist(methods=["GET"])``, không ``@idempotent``. Quyền đọc ``Instrument Set Type`` (mọi TC role,
S12) kiểm **trước** khi tra loại bộ: người không có quyền không biết được mã có tồn tại hay không, và không có dòng
Audit nào được ghi. Loại bộ / phiên bản không có → ``SET_TYPE_NOT_FOUND`` / ``BOM_VERSION_NOT_FOUND`` (404) qua
``reject_block`` (Audit ``Reject``, đặt ``flags.commit`` cho request GET). Tham số sai kiểu → ``BadRequestError`` (400).
Nghiệp vụ ở ``tracecore.instrument.bom`` / ``bom_versions`` / ``set_type`` / ``shelf_life`` / ``media``.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import gs1
from tracecore.core.errors import BlockedError
from tracecore.instrument import bom as bom_service
from tracecore.instrument import bom_versions, media, shelf_life
from tracecore.instrument import count_sheet as count_sheet_service
from tracecore.instrument import gtin as gtin_rules
from tracecore.instrument import set_type as set_type_rules
from tracecore.v1._common import BadRequestError, reject_block
from tracecore.v1.set_type_admin import ADMIN_ROLES

SET_TYPE = "Instrument Set Type"


def _code(set_type) -> str:
	return set_type.strip().upper()[: gs1.MAX_SCAN_LENGTH] if isinstance(set_type, str) else ""


def _version(value, name="version") -> int | None:
	"""Số phiên bản từ query string: trống → None; số nguyên → int (≤ 0 thì không có phiên bản nào); khác → 400."""
	if value is None or value == "":
		return None
	number = bom_versions.whole_number(value)
	if number is None:
		raise BadRequestError(_("{0} must be a whole number.").format(name))
	return number


def _open(set_type):
	"""Kiểm quyền đọc rồi tra loại bộ: ``(tên, None)`` hoặc ``(None, body từ chối 404)``."""
	frappe.has_permission(SET_TYPE, "read", throw=True)
	code = _code(set_type)
	name = frappe.db.get_value(SET_TYPE, code, "name") if code else None
	if not name:
		return None, reject_block(
			bom_versions.not_found_block(code), SET_TYPE, code or None, raw=code or None
		)
	frappe.has_permission(SET_TYPE, "read", doc=name, throw=True)
	return name, None


@frappe.whitelist(methods=["GET"])
def bom(set_type=None, version=None, if_none_match=None):
	"""BOM của loại bộ ở phiên bản `version` (trống → phiên bản hiệu lực hôm nay) cho trạm/PDA (S11).

	Trả ``{"ok": True, set_type, set_type_name, method, bom_version, effective_from, status, lines, tray_images,
	total_lines, total_qty, etag}`` (``bom.payload``). ``if_none_match`` = ``etag`` hiện tại →
	``{"ok": True, "not_modified": True, etag, set_type, bom_version, status}`` (``status`` đi kèm vì không nằm trong
	etag: phiên bản đã lên lịch thành hiệu lực mà nội dung không đổi). Từ chối: ``SET_TYPE_NOT_FOUND``,
	``BOM_VERSION_NOT_FOUND`` (404).
	"""
	name, rejected = _open(set_type)
	if rejected:
		return rejected
	number = _version(version)
	try:
		if number is not None and number < 1:
			raise BlockedError(bom_service.version_not_found_block(name, number))
		data = bom_service.payload(name, number)
	except BlockedError as error:
		return reject_block(error.block, SET_TYPE, name, raw=name)
	tag = if_none_match.strip().strip('"') if isinstance(if_none_match, str) else None
	if tag and tag == data["etag"]:
		return {
			"ok": True,
			"not_modified": True,
			"etag": data["etag"],
			"set_type": data["set_type"],
			"bom_version": data["bom_version"],
			"status": data["status"],
		}
	return {"ok": True, **data}


@frappe.whitelist(methods=["GET"])
def versions(set_type=None):
	"""Các phiên bản BOM của loại bộ, mới → cũ: ``{"ok": True, set_type, effective_version, versions}``.

	``versions`` = ``bom_versions.versions`` (ngày hiệu lực, lý do, người tạo, tổng dòng/tổng dụng cụ, trạng thái).
	Từ chối: ``SET_TYPE_NOT_FOUND`` (404).
	"""
	name, rejected = _open(set_type)
	if rejected:
		return rejected
	return {
		"ok": True,
		"set_type": name,
		"effective_version": bom_versions.effective_version(name),
		"versions": bom_versions.versions(name),
	}


@frappe.whitelist(methods=["GET"])
def compare(set_type=None, from_version=None, to_version=None):
	"""So sánh hai phiên bản BOM (S10, FR-M1-04.3): ``{"ok": True, **bom_versions.compare(...)}``.

	Từ chối: ``SET_TYPE_NOT_FOUND``, ``BOM_VERSION_NOT_FOUND`` (404), ``BOM_LINE_INVALID`` (422, cùng một phiên bản).
	"""
	name, rejected = _open(set_type)
	if rejected:
		return rejected
	old, new = _version(from_version, "from_version"), _version(to_version, "to_version")
	try:
		return {"ok": True, **bom_versions.compare(name, old, new)}
	except BlockedError as error:
		return reject_block(error.block, SET_TYPE, name, raw=name)


@frappe.whitelist(methods=["GET"])
def count_sheet(set_type=None, version=None):
	"""Tải phiếu kiểm đếm PDF của loại bộ ở phiên bản `version` (trống → phiên bản hiệu lực) (S9, FR-M1-03, EI-HW-007).

	Thành công: response file ``<type_code>-BOM-V<n>.pdf`` (``frappe.local.response`` ``type = "pdf"``), sinh khi yêu
	cầu, không lưu File, không ghi Audit (chỉ đọc). Quyền đọc loại bộ (mọi TC role, S12). Từ chối (JSON):
	``SET_TYPE_NOT_FOUND``, ``BOM_VERSION_NOT_FOUND`` (404); ``version`` không phải số nguyên → 400.
	"""
	name, rejected = _open(set_type)
	if rejected:
		return rejected
	number = _version(version)
	try:
		if number is not None and number < 1:
			raise BlockedError(bom_service.version_not_found_block(name, number))
		number = bom_service.resolve_version(name, number)
		pdf = count_sheet_service.render_pdf(name, number)
	except BlockedError as error:
		return reject_block(error.block, SET_TYPE, name, raw=name)
	frappe.local.response.filename = f"{name}-BOM-V{number}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "pdf"


def _missing(name: str, photos: list) -> list[dict]:
	"""Cảnh báo dữ liệu còn thiếu (không chặn lưu, S6/S13): ảnh bộ đã xếp, thời gian lắp ráp chuẩn."""
	missing = []
	if not photos:
		missing.append(
			{
				"code": "PHOTOS",
				"message": _("No photo of the assembled set yet. The count sheet will show an empty frame."),
			}
		)
	if cint(frappe.db.get_value(SET_TYPE, name, "assembly_minutes")) <= 0:
		missing.append(
			{"code": "ASSEMBLY_MINUTES", "message": _("Standard assembly time has not been entered.")}
		)
	return missing


@frappe.whitelist()
def pack_type_query(doctype=None, txt=None, searchfield=None, start=0, page_len=20, filters=None):
	"""Gợi ý của trường Link ``default_pack_type`` trên form Desk (Task 8, FR-M1-03.5): chỉ loại gói dùng được.

	Hàm query chuẩn của Frappe (``frappe.desk.search.search_widget`` gọi với chữ ký này): lọc
	``shelf_life.usable_pack_types()`` theo chuỗi gõ (mã hoặc tên, không phân biệt hoa thường), trả
	``[(mã Item, tên, "N ngày")]`` để ô gợi ý hiện số ngày. Cùng tiêu chí với kiểm khi lưu nên JS không chép luật.
	Quyền đọc ``Instrument Set Type`` (người không đọc được loại bộ không cần gợi ý này).
	"""
	frappe.has_permission(SET_TYPE, "read", throw=True)
	rows = [
		(row["item"], row["item_name"], _("{0} days").format(row["shelf_life_days"]))
		for row in shelf_life.usable_pack_types()
	]
	return _page(_matching(rows, txt), start, page_len)


@frappe.whitelist()
def department_query(doctype=None, txt=None, searchfield=None, start=0, page_len=20, filters=None):
	"""Gợi ý của trường Link ``department`` (khoa sở hữu loại bộ, FR-M1-03) trên form Desk (Task 8).

	TC R02/R10 tạo/sửa loại bộ (S12) nhưng không có quyền đọc ``Department`` của ERPNext/HRMS, nên ô gợi ý chuẩn trả
	403. Query này chỉ trả ``[(mã khoa, tên khoa)]`` của khoa chưa tắt, lọc theo chuỗi gõ; quyền đọc
	``Instrument Set Type``. Lưu loại bộ vẫn kiểm Link tồn tại ở server.
	"""
	frappe.has_permission(SET_TYPE, "read", throw=True)
	rows = frappe.get_all(
		"Department",
		filters={"disabled": 0},
		fields=["name", "department_name"],
		order_by="department_name asc, name asc",
		as_list=True,
	)
	return _page(_matching([tuple(row) for row in rows], txt), start, page_len)


def _matching(rows: list[tuple], txt) -> list[tuple]:
	"""Dòng có cột 1 (mã) hoặc cột 2 (tên) chứa chuỗi gõ, không phân biệt hoa thường."""
	needle = txt.strip().lower() if isinstance(txt, str) else ""
	if not needle:
		return rows
	return [row for row in rows if needle in str(row[0]).lower() or needle in str(row[1] or "").lower()]


def _page(rows: list[tuple], start, page_len) -> list[tuple]:
	offset, limit = max(cint(start), 0), cint(page_len)
	return rows[offset : offset + limit] if limit > 0 else rows[offset:]


@frappe.whitelist(methods=["GET"])
def form_context(set_type=None):
	"""Dữ liệu cho form Desk của loại bộ; chỉ đọc, không chép quy tắc nghiệp vụ sang JS.

	Trả ``{"ok": True, set_type, effective_version, versions, shelf_life, usable_pack_types, derived_max_cycles,
	photos, missing, permissions}``: ``shelf_life`` = ``shelf_life.effective``; ``derived_max_cycles`` =
	``set_type.derived_max_cycles``; ``photos`` = ``media.set_type_photos``; ``missing`` = ``[{code, message}]``
	(``PHOTOS``, ``ASSEMBLY_MINUTES``); ``permissions`` = ``{can_edit, can_set_shelf_life}`` (nút ghi người dùng được
	thấy; RPC ghi vẫn kiểm lại). Từ chối: ``SET_TYPE_NOT_FOUND`` (404).
	"""
	name, rejected = _open(set_type)
	if rejected:
		return rejected
	admin = bool(set(frappe.get_roles()) & set(ADMIN_ROLES))
	photos = media.set_type_photos(name)
	return {
		"ok": True,
		"set_type": name,
		"effective_version": bom_versions.effective_version(name),
		"versions": bom_versions.versions(name),
		"shelf_life": shelf_life.effective(name),
		"usable_pack_types": shelf_life.usable_pack_types(),
		"derived_max_cycles": set_type_rules.derived_max_cycles(name),
		"photos": photos,
		"missing": _missing(name, photos),
		"gtin": gtin_rules.context(name),
		"permissions": {
			"can_edit": admin and bool(frappe.has_permission(SET_TYPE, "write", doc=name)),
			"can_set_shelf_life": admin,
		},
	}
