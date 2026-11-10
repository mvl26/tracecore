"""HAI Case — ca NKBV (FEAT-063; FR-M13-05, 06, 15; BRU-HAI-001, BRU-HAI-005). Luật ở ``hai_surveillance.cases``.

Mã người bệnh là trường Password (``core.patient_code``); danh sách hiện ``patient_code_masked``; không có trường họ
tên người bệnh; không xóa.
"""

import frappe
from frappe.model.document import Document

from tracecore.hai_surveillance import cases


def on_doctype_update():
	frappe.db.add_index(cases.DOCTYPE, ["department", "reporting_period"])


class HAICase(Document):
	def validate(self):
		cases.validate(self)

	def before_submit(self):
		cases.before_submit(self)

	def before_update_after_submit(self):
		cases.before_update_after_submit(self)

	def before_cancel(self):
		cases.before_cancel(self)

	def on_trash(self):
		cases.on_trash(self)
