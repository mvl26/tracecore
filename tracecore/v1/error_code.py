"""Hướng dẫn xử lý theo mã lỗi (FEAT-052, A-71, FR-M9-19).

Không cần phiên: màn đăng nhập trạm chưa có phiên vẫn phải mở được hướng dẫn NS-001/NS-003; nội dung là HDSD, không có dữ liệu riêng.
"""

import frappe
from frappe import _
from frappe.utils.html_utils import clean_html

from tracecore.core.errors import Block
from tracecore.v1._common import _block_body


@frappe.whitelist(allow_guest=True, methods=["GET"])
def guide(error_code=None):
	row = None
	if isinstance(error_code, str):
		row = frappe.db.get_value(
			"TraceCore Error Code", error_code, ["name", "error_name", "guide"], as_dict=True
		)
	if not row:
		return _block_body(
			Block(
				"ERROR_CODE_NOT_FOUND",
				_("Error code not found"),
				_("Error code {0} is not in the catalog.").format(error_code or "-"),
				_("Check the code in the message."),
			)
		)
	return {
		"ok": True,
		"code": row.name,
		"name": _(row.error_name),
		"guide_html": clean_html(row.guide or ""),
	}
