"""Surgical Surveillance — ca phẫu thuật giám sát NKVM (FEAT-064; FR-M13-07..09; BRU-HAI-003, 004, 005). Luật ở
``hai_surveillance.ssi``.

Mã người bệnh là trường Password (``core.patient_code``); danh sách hiện ``patient_code_masked``; không có trường họ
tên người bệnh; không xóa.
"""

import frappe
from frappe.model.document import Document

from tracecore.hai_surveillance import ssi


def on_doctype_update():
	frappe.db.add_index(ssi.DOCTYPE, ["reporting_period", "procedure_group"])


class SurgicalSurveillance(Document):
	def validate(self):
		ssi.validate(self)

	def on_trash(self):
		ssi.on_trash(self)
