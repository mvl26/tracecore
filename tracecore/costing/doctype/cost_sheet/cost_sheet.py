import frappe
from frappe import _
from frappe.model.document import Document


class CostSheet(Document):
	"""Giá thành mẻ/lô và gói (A-53); chỉ `costing.sheet` ghi (cờ ``flags.tc_cost_sheet``), không xóa."""

	def validate(self):
		if not self.flags.tc_cost_sheet:
			frappe.throw(_("Cost sheets are written by the costing service only."))

	def on_trash(self):
		frappe.throw(_("Cost sheets cannot be deleted."))
