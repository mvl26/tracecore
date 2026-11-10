"""Isolation Order — lệnh cách ly tại khoa (FEAT-068; FR-M14-06; BRU-MDR-003; A-146). Luật ở ``microbiology.isolation``.

Mã người bệnh là trường Password (``core.patient_code``); danh sách hiện ``patient_code_masked``; không có trường họ
tên người bệnh (BRU-HAI-005, NFR-PRIV-01).
"""

from frappe.model.document import Document

from tracecore.microbiology import isolation


class IsolationOrder(Document):
	def validate(self):
		isolation.validate_order(self)

	def on_submit(self):
		isolation.on_submit(self)

	def before_update_after_submit(self):
		isolation.guard_after_submit(self)

	def on_cancel(self):
		isolation.on_cancel(self)
