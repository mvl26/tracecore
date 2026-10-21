"""RPC tracecore.v1.label_template.* — xem trước mẫu nhãn trên Desk cho R10 (FEAT-002 E7, FR-M2-08.4)."""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import print as core_print
from tracecore.core.errors import Block
from tracecore.setup.label_templates import sample_pack_context
from tracecore.v1._common import BadRequestError, require_any_role

PREVIEW_ROLES = ("System Manager", "TC R10")


@frappe.whitelist(methods=["GET", "POST"])
def preview(template, unicode=0):
	"""Dựng mẫu `template` bằng dữ liệu mẫu theo kích thước, dpi, ngôn ngữ của chính mẫu; trả `{"ok", "zpl"}`.

	Chỉ đọc (không ghi Audit Log, không gọi dịch vụ ngoài). Mẫu lỗi → ``ok: false`` + `LABEL_RENDER_FAILED` (422),
	không phải 500. `unicode` bật thì giữ dấu tiếng Việt, như máy in có phông Unicode.
	"""
	require_any_role(*PREVIEW_ROLES)
	if not template or not isinstance(template, str):
		raise BadRequestError(_("template must be a label template name."))
	row = frappe.db.get_value("Label Template", template, core_print.TEMPLATE_FIELDS, as_dict=True)
	if not row:
		raise frappe.DoesNotExistError(_("Label template {0} does not exist.").format(template))
	logged = len(frappe.local.message_log)
	try:
		zpl = core_print.render(
			row.body,
			sample_pack_context(),
			bool(cint(unicode)),
			dpi=row.dpi,
			width_mm=row.width_mm,
			height_mm=row.height_mm,
			language=row.language,
			name=row.name,
		)
	except Exception as error:  # mẫu lỗi bất kỳ kiểu nào: 422 có body, không phải 500
		del frappe.local.message_log[logged:]  # lỗi thành body, không để msgprint lên Desk
		if not isinstance(error, frappe.ValidationError):
			frappe.log_error(
				title=_("Label template could not be rendered"), message=f"{row.name}: {error!r}"
			)
		block = Block(
			"LABEL_RENDER_FAILED",
			_("Label template could not be rendered"),
			str(error),
			_("Fix the template body, then preview it again."),
		)
		if getattr(frappe.local, "request", None):
			frappe.local.response["http_status_code"] = block.http_status
		return {"ok": False, "error": block.as_dict()}
	return {"ok": True, "zpl": zpl}
