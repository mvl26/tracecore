"""Microbiology Isolate — chủng phân lập + kháng sinh đồ (FEAT-067). Luật ở ``microbiology.isolates``.

Mã người bệnh là trường Password (``core.patient_code``); danh sách hiện ``patient_code_masked``; không có trường họ
tên người bệnh (BRU-HAI-005, NFR-PRIV-01).
"""

from frappe.model.document import Document

from tracecore.microbiology import isolates


class MicrobiologyIsolate(Document):
	def validate(self):
		isolates.validate(self)

	def after_insert(self):
		isolates.after_insert(self)
