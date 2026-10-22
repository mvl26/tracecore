"""Thẻ kim loại và nhãn khay của Set Unit (FEAT-016 Task 3; FR-M1-05; BRU-ID-001; A-09 G3, G8).

- `KINDS`: loại bản in → `Label Template.label_object` (`core.print.SET_LABELS`); mỗi loại dùng mẫu active của nó.
- `tag_context`: `doc` của mẫu (Set ID, payload DataMatrix FNC1 + 8004 + GIAI, HRI ``(8004)…``, loại bộ, khoa, phương
  pháp, cấy ghép, ngày cấp ``dd/mm/yyyy`` theo giờ hệ thống, `is_test`). Mọi bản in, xem trước, xuất CSV đều dựng từ
  đây nên chặn tiền tố demo đặt ở đây: thẻ kim loại không sửa được, Set ID mang tiền tố demo ``952`` (DB dev chép sang
  site thật) không dựng được trên site không phải dev/test → ``BlockedError(GS1_PREFIX_NOT_CONFIGURED)`` (G3);
  trên dev/test thẻ in thêm dòng ``TEST``.
- `render` / `preview`: ZPL bằng `core.print.render_label`; ảnh PNG xem trước dựng từ chính ZPL (máy in không Unicode).
"""

import base64

import frappe
from frappe import _
from frappe.utils import cint, get_datetime

from tracecore.core import code_registry, gs1
from tracecore.core import print as core_print
from tracecore.core.errors import BlockedError
from tracecore.core.print_preview import zpl_preview_png

KINDS = {"tag": "Set Tag", "tray": "Set Tray Label"}
# Xem trước như máy in không hỗ trợ Unicode: ZPL bỏ dấu, ảnh vẽ bằng phông mặc định của Pillow
PREVIEW_PRINTER = {"language": core_print.DEFAULT_LANGUAGE, "supports_unicode": 0}
UNIT_FIELDS = ["name", "set_type", "department", "creation"]
SET_TYPE_FIELDS = ["type_code", "set_type_name", "method", "is_implant"]


def label_object(kind) -> str:
	"""`Label Template.label_object` của loại bản in `kind` (``tag`` | ``tray``); loại khác → ValidationError."""
	if not isinstance(kind, str) or kind not in KINDS:
		frappe.throw(_("Unknown set label kind: {0}").format(repr(kind)))
	return KINDS[kind]


def tag_context(set_unit: str, kind: str) -> dict:
	"""`doc` của mẫu thẻ kim loại / nhãn khay cho Set Unit `set_unit` (cùng khóa với `sample_set_context`).

	Set Unit không có → DoesNotExistError; Set ID mang tiền tố demo trên site không phải dev/test → BlockedError.
	"""
	label_object(kind)
	unit = frappe.db.get_value("Set Unit", set_unit, UNIT_FIELDS, as_dict=True) if set_unit else None
	if not unit:
		frappe.throw(_("Set Unit {0} not found.").format(set_unit), frappe.DoesNotExistError)
	set_type = frappe.db.get_value("Instrument Set Type", unit.set_type, SET_TYPE_FIELDS, as_dict=True) or {}
	block = code_registry.set_id_block(unit.name, set_type.get("type_code"))
	if block:
		raise BlockedError(block)
	department = (
		frappe.db.get_value("Department", unit.department, "department_name") if unit.department else ""
	)
	method = set_type.get("method")
	return {
		"set_id": unit.name,
		"payload": gs1.giai_payload(unit.name),
		"hri": gs1.giai_hri(unit.name),
		"type_code": set_type.get("type_code") or "",
		"set_type_name": set_type.get("set_type_name") or "",
		"department": department or "",
		"method": _(method) if method else "",
		"is_implant": bool(cint(set_type.get("is_implant"))),
		# `creation` do Frappe ghi theo giờ hệ thống (Asia/Ho_Chi_Minh), không đổi múi giờ thêm
		"issued_on": get_datetime(unit.creation).strftime("%d/%m/%Y"),
		"is_test": gs1.is_demo_prefix(unit.name),
	}


def render(set_unit: str, kind: str, printer: dict | None = None, with_template: bool = False):
	"""ZPL thẻ kim loại (``tag``) hoặc nhãn khay (``tray``) của `set_unit` bằng mẫu active theo ngôn ngữ máy in.

	`printer`, `with_template` như `core.print.render_label` (``(zpl, dòng mẫu)`` khi `with_template`).
	"""
	return core_print.render_label(label_object(kind), tag_context(set_unit, kind), printer, with_template)


def preview(set_unit: str, kind: str) -> dict:
	"""``{png_b64, zpl, hri}``: ZPL như máy in không Unicode và ảnh PNG đúng kích thước mẫu (dot) dựng từ ZPL đó."""
	context = tag_context(set_unit, kind)
	zpl, template = core_print.render_label(label_object(kind), context, PREVIEW_PRINTER, with_template=True)
	size = (
		core_print.mm_to_dots(template.width_mm, template.dpi),
		core_print.mm_to_dots(template.height_mm, template.dpi),
	)
	png = zpl_preview_png(zpl, context["payload"], size)
	return {"png_b64": base64.b64encode(png).decode("ascii"), "zpl": zpl, "hri": context["hri"]}
