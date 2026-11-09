"""Microbiology Isolate — chủng phân lập + kháng sinh đồ (FEAT-067). Luật ở ``microbiology.isolates``.

Mã người bệnh là trường Password (``core.patient_code``); danh sách hiện ``patient_code_masked``; không có trường họ
tên người bệnh (BRU-HAI-005, NFR-PRIV-01).
"""

import frappe
from frappe.model.document import Document

from tracecore.microbiology import isolates


def on_doctype_update():
	"""Khóa (mã mẫu, vi khuẩn) duy nhất ở cả DB, không chỉ ở ``validate`` (hai lần ghi song song)."""
	frappe.db.add_unique(
		isolates.DOCTYPE, ["lab_sample_id", "organism"], constraint_name="tc_lab_sample_organism"
	)
	frappe.db.add_index(isolates.DOCTYPE, ["patient_code_hash", "organism", "period_key"])


class MicrobiologyIsolate(Document):
	def validate(self):
		isolates.validate(self)

	def after_insert(self):
		isolates.after_insert(self)
