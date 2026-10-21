"""Set BOM Item: một dòng BOM của loại bộ theo phiên bản (DT-SETBOM); đọc qua `tracecore.instrument.bom`."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class SetBOMItem(Document):
	def validate(self):
		if cint(self.qty) < 1:
			frappe.throw(_("Quantity must be at least 1."))
		self._reject_retired_instrument()

	def _reject_retired_instrument(self):
		# FR-M1-01, A-06 I13: dòng mới (hoặc đổi dụng cụ) không nhận dụng cụ đã Ngừng sử dụng; dòng cũ giữ nguyên
		if not self.instrument or not (self.is_new() or self.has_value_changed("instrument")):
			return
		if frappe.db.get_value("Instrument", self.instrument, "status") == "Retired":
			frappe.throw(_("Instrument {0} is retired and cannot be added to a BOM.").format(self.instrument))


def on_doctype_update():
	# bom.lines tra theo (loại bộ, phiên bản)
	frappe.db.add_index("Set BOM Item", ["set_type", "bom_version"])
