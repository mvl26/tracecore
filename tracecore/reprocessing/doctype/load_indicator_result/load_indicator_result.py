"""Load Indicator Result: kết quả chỉ thị của mẻ tiệt khuẩn (FEAT-023, UC-10, architecture §5.3 DT-LOADTEST).

Chỉ dịch vụ giải phóng (`reprocessing.releasing`) ghi, bằng cờ ``doc.flags.tc_releasing``. Chỉ thị sinh học tạo ở
``Pending`` rồi đọc thành ``Pass``/``Fail``; không xóa.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import audit


class LoadIndicatorResult(Document):
	def validate(self):
		if not self.flags.tc_releasing:
			frappe.throw(_("An indicator result can only be recorded by the release service."))

	def on_trash(self):
		audit.block_delete(self, "on_trash")
