"""Ward Daily Census — mẫu số ngày theo khoa (FEAT-062). Luật ở ``hai_surveillance.census``.

Một bản ghi mỗi (ngày, khoa) ở cả DB (BRU-HAI-002); không xóa; bản đã khóa kỳ không sửa.
"""

import frappe
from frappe.model.document import Document

from tracecore.hai_surveillance import census


def on_doctype_update():
	frappe.db.add_unique(
		census.DOCTYPE, ["census_date", "department"], constraint_name="tc_census_date_department"
	)


class WardDailyCensus(Document):
	def validate(self):
		census.validate(self)

	def on_trash(self):
		census.on_trash(self)
