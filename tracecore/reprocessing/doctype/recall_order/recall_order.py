"""Recall Order: lệnh thu hồi (DT-RECALL, M2, FEAT-029, FR-M2-20, WF-05); luật ở ``reprocessing.recall``.

Open (Nháp) → Closed (Ghi sổ) khi mọi gói đã xác nhận. Chỉ dịch vụ ``recall`` lập, xác nhận và đóng (cờ
``flags.tc_recall``); không sửa tay, không hủy kiểu Frappe, không xóa (Audit ``block_delete``).
"""

from frappe.model.document import Document

from tracecore.reprocessing import recall


class RecallOrder(Document):
	def validate(self):
		recall.guard_changes(self)

	def before_submit(self):
		recall.guard_submit(self)

	def before_cancel(self):
		recall.guard_cancel(self)
