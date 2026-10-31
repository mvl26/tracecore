"""Dirty Receipt: phiếu tiếp nhận nhiều bộ tại T1 (FEAT-019, UC-05, FR-M2-01, FR-M2-23).

Phiếu chỉ do dịch vụ tiếp nhận (`tracecore.reprocessing.receiving`) tạo và đổi, bằng cờ ``doc.flags.tc_receiving``:
R03/R02/System Manager có quyền write và submit trên Desk nhưng không được tự thêm bộ, tick dòng hay ghi sổ ngoài
dịch vụ (ghi sổ phiếu là lúc mở chu trình và ghi cổng T1 cho từng bộ). Không hủy chứng từ, không xóa.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class DirtyReceipt(Document):
	def before_insert(self):
		self._require_service()
		if cint(self.needs_card):
			# người giao không thẻ chỉ có tên; Desk có thể tự điền deliverer bằng nhân viên của người tạo (FR-M2-01.7)
			self.deliverer = None

	def validate(self):
		self._require_service()
		sets = [row.set_unit for row in self.items]
		if len(set(sets)) != len(sets):
			frappe.throw(_("A set unit appears more than once in the receipt."))

	def before_submit(self):
		self._require_service()

	def before_update_after_submit(self):
		self._require_service()

	def before_cancel(self):
		frappe.throw(_("A dirty receipt cannot be cancelled."))

	def _require_service(self):
		if not self.flags.tc_receiving:
			frappe.throw(_("A dirty receipt is created and changed only by the receiving screen service."))
