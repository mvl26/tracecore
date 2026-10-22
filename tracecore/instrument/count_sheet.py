"""Phiếu kiểm đếm của loại bộ theo phiên bản BOM (FEAT-015 S8, S9; FR-M1-03, FR-M1-03.2, EI-HW-007).

``context`` dựng dữ liệu phiếu: phần đầu loại bộ, phiên bản BOM (ngày hiệu lực, lý do, trạng thái), dòng theo thứ tự
xếp, tổng dòng/tổng dụng cụ, 1-3 ảnh bộ đã xếp và DataMatrix ``BOM-<TYPE_CODE>-V<n>`` (``core.gs1``) nhúng ``data:``
base64. ``render_html`` dựng HTML bằng Print Format Jinja chuẩn ``TC Count Sheet`` (cùng template Desk dùng ở menu
Print, phiên bản hiệu lực); ``render_pdf`` sinh PDF bằng wkhtmltopdf của Frappe (``frappe.utils.pdf.get_pdf``) khi
được yêu cầu: không lưu File (phiên bản bất biến nên phiếu tái lập được), không ghi Audit (chỉ đọc), không URL nào
trong HTML (ảnh qua ``media.print_image_data_uri``, không đọc mạng).

wkhtmltopdf không hiểu CSS custom property nên màu/cỡ chữ/khoảng cách đọc ở server từ ``public/css/tokens.css`` đã sinh
(``token_values``), không gõ hex trong template.
"""

import base64
import re

import frappe
from frappe import _
from frappe.utils import cint, escape_html, get_fullname, getdate, now_datetime

from tracecore.core import gs1
from tracecore.core.errors import BlockedError
from tracecore.instrument import bom, bom_versions, media, shelf_life

SET_TYPE = "Instrument Set Type"
PRINT_FORMAT = "TC Count Sheet"
TEMPLATE_PATH = ("instrument", "print_format", "tc_count_sheet", "tc_count_sheet.html")
TOKENS_PATH = ("public", "css", "tokens.css")
PDF_OPTIONS = {"page-size": "A4", "orientation": "Portrait"}
DATE_FORMAT = "%d/%m/%Y"
DATETIME_FORMAT = "%d/%m/%Y %H:%M"
# khóa trong template → biến --tc-* của tokens.css (đen trắng khi in, design.md gap 11)
TOKEN_VARS = {
	"text": "text",
	"muted": "text-muted",
	"heading": "text-heading",
	"border": "frame",
	"line": "border-input",
	"zebra": "zebra",
	"paper": "card",
	"photo_bg": "photo-bg",
	"photo_border": "photo-border",
	"photo_text": "photo-text",
	"font_sans": "font-sans",
	"font_mono": "font-mono",
	"fw_bold": "fw-bold",
	"fs_xs": "fs-xs",
	"fs_sm": "fs-sm",
	"fs_md": "fs-md",
	"fs_lg": "fs-lg",
	"fs_2xl": "fs-2xl",
	"lh_snug": "lh-snug",
	"ls_code": "ls-code",
	"sp_1": "sp-1",
	"sp_2": "sp-2",
	"sp_3": "sp-3",
	"sp_4": "sp-4",
	"bw_hair": "bw-hair",
	"bw_thick": "bw-thick",
}
# font dự phòng có chữ Việt trên server Linux (A-07: Liberation/DejaVu thay Arial/Segoe UI, Courier New)
PRINT_FONT_FALLBACK = {
	"font_sans": ('"Liberation Sans"', '"DejaVu Sans"'),
	"font_mono": ('"Liberation Mono"', '"DejaVu Sans Mono"'),
}
_ROOT_VAR = re.compile(r"--tc-([a-z0-9-]+)\s*:\s*([^;}]+);")
# giá trị token chèn vào <style>: chỉ ký tự của màu/cỡ/tên font, không thể đóng thẻ hay khối CSS
_SAFE_VALUE = re.compile(r'[#A-Za-z0-9 ,."().%-]+')
_cache: dict = {}


class TokenError(RuntimeError):
	"""tokens.css đã sinh thiếu biến hoặc có giá trị lạ: lỗi cấu hình build (F-11), để CI bắt."""


def _read_tokens_css() -> str:
	with open(frappe.get_app_path("tracecore", *TOKENS_PATH), encoding="utf-8") as handle:
		return handle.read()


def _with_fallback(stack: str, extra: tuple[str, ...]) -> str:
	"""Chèn font dự phòng trước họ chung cuối (``sans-serif``/``monospace``) của chuỗi font token."""
	families = [family.strip() for family in stack.split(",") if family.strip()]
	generic = families.pop() if families and families[-1] in ("sans-serif", "monospace", "serif") else None
	families += [family for family in extra if family not in families]
	return ",".join(families + ([generic] if generic else []))


def token_values(refresh: bool = False) -> dict[str, str]:
	"""Giá trị các biến ``--tc-*`` mà phiếu dùng, đọc từ ``:root`` của ``tracecore/public/css/tokens.css`` đã sinh.

	Trả ``{khóa của TOKEN_VARS: giá trị}`` (``font_sans``/``font_mono`` thêm font dự phòng có chữ Việt). Thiếu biến
	hoặc giá trị có ký tự ngoài màu/cỡ/tên font → ``TokenError`` nêu tên biến. Cache trong tiến trình; ``refresh``
	đọc lại file.
	"""
	if refresh or "tokens" not in _cache:
		_cache.pop("tokens", None)
		css = _read_tokens_css()
		root = css[css.find(":root") :] if ":root" in css else ""
		found = {name: value.strip() for name, value in _ROOT_VAR.findall(root)}
		missing = sorted(f"--tc-{var}" for var in TOKEN_VARS.values() if var not in found)
		if missing:
			raise TokenError(
				f"tokens.css is missing {', '.join(missing)}; run scripts/build_tokens.py (F-11)."
			)
		values = {}
		for key, var in TOKEN_VARS.items():
			value = found[var]
			if not _SAFE_VALUE.fullmatch(value):
				raise TokenError(f"tokens.css has an unexpected value for --tc-{var}: {value[:40]!r}")
			values[key] = (
				_with_fallback(value, PRINT_FONT_FALLBACK[key]) if key in PRINT_FONT_FALLBACK else value
			)
		_cache["tokens"] = values
	return dict(_cache["tokens"])


def _status_labels() -> dict[str, str]:
	return {
		bom_versions.STATUS_EFFECTIVE: _("BOM in effect"),
		bom_versions.STATUS_SCHEDULED: _("BOM scheduled"),
		bom_versions.STATUS_SUPERSEDED: _("BOM superseded"),
		bom_versions.STATUS_SKIPPED: _("BOM replaced before taking effect"),
	}


def _shelf_life_text(info: dict) -> str:
	if not info.get("days"):
		return _("Shelf life not set")
	if info.get("source") == shelf_life.SOURCE_SET_TYPE:
		return _("{0} days (set type override)").format(cint(info["days"]))
	return _("{0} days (from pack type)").format(cint(info["days"]))


def _png_uri(content: bytes) -> str:
	return "data:image/png;base64," + base64.b64encode(content).decode("ascii")


def _label(doctype: str, name: str | None, field: str) -> str | None:
	return (frappe.db.get_value(doctype, name, field) or name) if name else None


def context(set_type: str, version: int | None = None) -> dict:
	"""Dữ liệu phiếu kiểm đếm của loại bộ ở phiên bản `version` (trống → phiên bản hiệu lực hôm nay).

	Trả ``{set_type, set_type_name, department, department_name, method, method_label, is_implant,
	assembly_minutes, default_pack_type, pack_type_name, shelf_life (shelf_life.effective), shelf_life_text,
	bom_version, effective_from (date | None), effective_from_text, reason, status, status_label, code, code_png,
	photos [data URI…], lines [{position, instrument, instrument_name, qty}], total_lines, total_qty, printed_at,
	printed_by, tc}``. Dòng và tổng lấy từ ``bom.payload`` (cache). Ảnh bộ đã xếp là ảnh hiện tại của loại bộ (gap S6);
	ảnh không hợp lệ bị bỏ qua. Kiểm quyền đọc loại bộ. Loại bộ / phiên bản không có → ``BlockedError``
	(``SET_TYPE_NOT_FOUND`` / ``BOM_VERSION_NOT_FOUND``). Không ghi gì.
	"""
	header = frappe.db.get_value(
		SET_TYPE,
		set_type,
		[
			"name",
			"set_type_name",
			"department",
			"method",
			"is_implant",
			"assembly_minutes",
			"default_pack_type",
		],
		as_dict=True,
	)
	if not header:
		raise BlockedError(bom_versions.not_found_block(set_type))
	frappe.has_permission(SET_TYPE, "read", doc=header.name, throw=True)
	data = bom.payload(header.name, version)
	number = data["bom_version"]
	info = next((row for row in bom_versions.versions(header.name) if row["bom_version"] == number), {})
	effective = getdate(data["effective_from"]) if data.get("effective_from") else None
	code = gs1.make_bom_code(header.name, number)
	photos = [media.print_image_data_uri(image["image_url"]) for image in data["tray_images"]]
	shelf = shelf_life.effective(header.name)
	return {
		"set_type": header.name,
		"set_type_name": header.set_type_name,
		"department": header.department,
		"department_name": _label("Department", header.department, "department_name"),
		"method": header.method,
		"method_label": _(header.method) if header.method else None,
		"is_implant": cint(header.is_implant),
		"assembly_minutes": cint(header.assembly_minutes),
		"default_pack_type": header.default_pack_type,
		"pack_type_name": _label("Item", header.default_pack_type, "item_name"),
		"shelf_life": shelf,
		"shelf_life_text": _shelf_life_text(shelf),
		"bom_version": number,
		"effective_from": effective,
		"effective_from_text": effective.strftime(DATE_FORMAT) if effective else None,
		"reason": info.get("reason"),
		"status": data["status"],
		"status_label": _status_labels().get(data["status"], data["status"]),
		"code": code,
		"code_png": _png_uri(gs1.encode_datamatrix_png(code)),
		"photos": [photo for photo in photos if photo],
		"lines": [
			{
				"position": line["position"],
				"instrument": line["instrument"],
				"instrument_name": line["instrument_name"],
				"qty": line["qty"],
			}
			for line in data["lines"]
		],
		"total_lines": data["total_lines"],
		"total_qty": data["total_qty"],
		"printed_at": now_datetime().strftime(DATETIME_FORMAT),
		"printed_by": get_fullname(frappe.session.user),
		"tc": token_values(),
	}


def tc_count_sheet_context(set_type: str, version: int | None = None) -> dict:
	"""Hàm Jinja (hook ``jinja.methods``) cho Print Format ``TC Count Sheet`` in từ Desk.

	Như ``context``; lỗi nghiệp vụ (vd loại bộ cũ chưa có BOM) trả ``{"error": {title, reason, action}, "tc"}`` để
	phiếu hiện lý do thay vì lỗi template. Tên riêng (không phải ``context``) để không chiếm một tên chung trong môi
	trường Jinja dùng cho mọi template của site.
	"""
	try:
		return context(set_type, version)
	except BlockedError as error:
		block = error.block
		return {
			"error": {"title": block.title, "reason": block.reason, "action": block.action},
			"tc": token_values(),
		}


def _template() -> str:
	with open(frappe.get_app_path("tracecore", *TEMPLATE_PATH), encoding="utf-8") as handle:
		return handle.read()


def render_html(set_type: str, version: int | None = None) -> str:
	"""HTML đầy đủ (``<!DOCTYPE html>``) của phiếu: Print Format ``TC Count Sheet`` render với ``context``."""
	sheet = context(set_type, version)
	body = frappe.render_template(
		_template(), {"doc": frappe._dict(name=sheet["set_type"]), "tc_sheet": sheet}
	)
	title = escape_html(_("Count sheet") + " " + sheet["code"])
	lang = escape_html(frappe.local.lang or "vi")
	return (
		f'<!DOCTYPE html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n<title>{title}</title>\n</head>\n'
		f'<body>\n<div class="print-format">\n{body}\n</div>\n</body>\n</html>\n'
	)


def render_pdf(set_type: str, version: int | None = None) -> bytes:
	"""PDF A4 dọc của phiếu (wkhtmltopdf qua ``frappe.utils.pdf.get_pdf``), sinh trong bộ nhớ, không lưu File."""
	from frappe.utils.pdf import get_pdf

	return get_pdf(render_html(set_type, version), dict(PDF_OPTIONS))
