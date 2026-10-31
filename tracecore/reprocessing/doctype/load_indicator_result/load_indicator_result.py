"""Load Indicator Result: kết quả chỉ thị của mẻ tiệt khuẩn hoặc lô rửa (FEAT-023, UC-10, A-257, architecture §5.3 DT-LOADTEST).

Chỉ dịch vụ giải phóng (`reprocessing.releasing`, cờ ``doc.flags.tc_releasing``) và dịch vụ rửa
(`reprocessing.washing`, cờ ``doc.flags.tc_washing``) ghi. Mỗi dòng thuộc đúng một mẻ hoặc một lô. Chỉ thị sinh học tạo
ở ``Pending`` rồi đọc thành ``Pass``/``Fail``; không xóa.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import audit


class LoadIndicatorResult(Document):
	def validate(self):
		if not (self.flags.tc_releasing or self.flags.tc_washing):
			frappe.throw(_("An indicator result can only be recorded by the release or wash service."))
		if bool(self.load) == bool(self.wash_batch):
			frappe.throw(_("An indicator result belongs to exactly one load or one wash batch."))

	def on_trash(self):
		audit.block_delete(self, "on_trash")
