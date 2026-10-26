"""Loaner Set: bộ mượn từ hãng (DT-LOANER, M1, FEAT-017, A-38; UC-04, FR-M1-07, FR-M1-08); luật ở ``instrument.loaner``.

Nháp → Ghi sổ (= nhận: dụng cụ, loại bộ mượn, Set ID LN) → trả hãng bằng thao tác trả. Không hủy kiểu Frappe, không
xóa (Audit ``block_delete``). Trường dịch vụ chỉ ``instrument.loaner`` ghi.
"""

from frappe.model.document import Document

from tracecore.instrument import loaner


class LoanerSet(Document):
	def validate(self):
		loaner.validate(self)

	def on_submit(self):
		loaner.on_submit(self)

	def before_cancel(self):
		loaner.guard_cancel(self)
