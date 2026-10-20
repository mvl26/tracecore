"""Set BOM Item: một dòng BOM của loại bộ theo phiên bản (DT-SETBOM); đọc qua `tracecore.instrument.bom`."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class SetBOMItem(Document):
	def validate(self):
		if cint(self.qty) < 1:
			frappe.throw(_("Quantity must be at least 1."))


def on_doctype_update():
	# bom.lines tra theo (loại bộ, phiên bản)
	frappe.db.add_index("Set BOM Item", ["set_type", "bom_version"])
