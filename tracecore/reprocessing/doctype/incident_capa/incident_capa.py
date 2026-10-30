"""Incident CAPA: sự cố / NC / CAPA (DT-INCIDENT, M2, FEAT-030, FR-M2-21, FR-M2-22, WF-06); luật ở ``reprocessing.incidents``.

New → Analysis → CAPA → Verification (Nháp) → Closed / Cancelled (Ghi sổ). Chỉ dịch vụ ``incidents`` đổi trạng thái
(cờ ``flags.tc_incident``); không submit tay, không hủy kiểu Frappe, không xóa (Audit ``block_delete``).
"""

from frappe.model.document import Document

from tracecore.reprocessing import incidents


class IncidentCAPA(Document):
	def validate(self):
		incidents.validate(self)

	def after_insert(self):
		incidents.after_insert(self)

	def before_submit(self):
		incidents.guard_submit(self)

	def before_cancel(self):
		incidents.guard_cancel(self)
