"""Surgical Procedure Group — nhóm phẫu thuật giám sát NKVM (FEAT-064; FR-M13-07, 07.2; BRU-HAI-004; A-147 Q2, a).

Danh mục cấu hình do R01 duyệt (D10): T của NNIS, cửa sổ 30/90 ngày, lịch theo dõi sau ra viện. Luật ở
``hai_surveillance.ssi``.
"""

from frappe.model.document import Document

from tracecore.hai_surveillance import ssi


class SurgicalProcedureGroup(Document):
	def validate(self):
		ssi.validate_group(self)
