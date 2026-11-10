"""Device Episode — đợt thiết bị xâm lấn (FEAT-062). Luật ở ``hai_surveillance.episodes``.

Mã người bệnh là trường Password (``core.patient_code``); danh sách hiện ``patient_code_masked``; không có trường họ
tên người bệnh (BRU-HAI-005, NFR-PRIV-01); không xóa.
"""

import frappe
from frappe.model.document import Document

from tracecore.hai_surveillance import episodes


def on_doctype_update():
	frappe.db.add_index(episodes.DOCTYPE, ["department", "status"])


class DeviceEpisode(Document):
	def validate(self):
		episodes.validate(self)

	def on_trash(self):
		episodes.on_trash(self)
