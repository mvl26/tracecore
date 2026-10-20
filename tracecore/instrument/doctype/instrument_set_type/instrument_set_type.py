"""Instrument Set Type: mã loại bộ dùng trong Set ID GIAI (§5.3.3) và dữ liệu đóng gói T4 (FEAT-018).

GTIN-14 của loại bộ (AI 01 của Cycle ID) do R10 nhập tay, không sinh bằng công thức (D6, OQ-05).
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import gs1

TYPE_CODE_PATTERN = re.compile(r"[A-Z0-9]{2,8}")


class InstrumentSetType(Document):
	def before_naming(self):
		self.type_code = (self.type_code or "").strip().upper()

	def validate(self):
		self.type_code = (self.type_code or "").strip().upper()
		if not TYPE_CODE_PATTERN.fullmatch(self.type_code):
			frappe.throw(_("Type Code must be 2-8 uppercase letters or digits."))
		self._validate_gtin()

	def _validate_gtin(self):
		# Trống được (loại bộ chưa có GTIN thì chưa sinh được Cycle ID); lưu NULL để chỉ mục unique
		# không coi nhiều dòng "" là trùng nhau.
		self.gtin = (self.gtin or "").strip() or None
		if self.gtin is None:
			return
		if not gs1.is_valid_gtin14(self.gtin):
			frappe.throw(_("GTIN-14 must be 14 digits with a valid check digit."))
		used_by = frappe.db.get_value(
			"Instrument Set Type", {"gtin": self.gtin, "name": ("!=", self.name)}, "name"
		)
		if used_by:
			frappe.throw(_("GTIN-14 {0} is already used by Set Type {1}.").format(self.gtin, used_by))
