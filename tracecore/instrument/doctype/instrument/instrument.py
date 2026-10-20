"""Instrument: dụng cụ đơn lẻ (DT-INSTR). Mã dụng cụ viết hoa, chỉ gồm chữ, số và dấu gạch ngang."""

import re

import frappe
from frappe import _
from frappe.model.document import Document

INSTRUMENT_CODE_PATTERN = re.compile(r"[A-Z0-9-]+")


def _normalize_code(code):
	code = (code or "").strip().upper()
	if not INSTRUMENT_CODE_PATTERN.fullmatch(code):
		frappe.throw(_("Instrument Code may contain only uppercase letters, digits and hyphens."))
	return code


class Instrument(Document):
	def before_naming(self):
		# name = mã: chuẩn hóa và kiểm tra trước khi đặt tên, kể cả ký tự mà Frappe cấm trong name
		self.instrument_code = _normalize_code(self.instrument_code)

	def validate(self):
		self.instrument_code = _normalize_code(self.instrument_code)
