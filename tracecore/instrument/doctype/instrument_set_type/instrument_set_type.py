"""Instrument Set Type (khung FEAT-001): mã loại bộ dùng trong Set ID GIAI (§5.3.3)."""

import re

import frappe
from frappe import _
from frappe.model.document import Document

TYPE_CODE_PATTERN = re.compile(r"[A-Z0-9]{2,8}")


class InstrumentSetType(Document):
	def before_naming(self):
		self.type_code = (self.type_code or "").strip().upper()

	def validate(self):
		self.type_code = (self.type_code or "").strip().upper()
		if not TYPE_CODE_PATTERN.fullmatch(self.type_code):
			frappe.throw(_("Type Code must be 2-8 uppercase letters or digits."))
