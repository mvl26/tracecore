"""Instrument Set Type: mã loại bộ dùng trong Set ID GIAI (§5.3.3) và dữ liệu đóng gói T4 (FEAT-018).

GTIN-14 của loại bộ (AI 01 của Cycle ID) do R10 nhập tay, không sinh bằng công thức (D6, OQ-05).
Luật phần đầu FEAT-015 (khoa, loại gói có hạn lưu, ghi đè ngắn hơn, cấy ghép, thời gian lắp ráp, phiên bản BOM hiện
hành chỉ server ghi, đổi phương pháp kiểm lại BOM) ở tracecore.instrument.set_type.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import gs1
from tracecore.instrument import set_type as set_type_rules

TYPE_CODE_PATTERN = re.compile(r"[A-Z0-9]{2,8}")


class InstrumentSetType(Document):
	def before_naming(self):
		self.type_code = (self.type_code or "").strip().upper()

	def validate(self):
		self.type_code = (self.type_code or "").strip().upper()
		if not TYPE_CODE_PATTERN.fullmatch(self.type_code):
			frappe.throw(_("Type Code must be 2-8 uppercase letters or digits."))
		self._validate_gtin()
		set_type_rules.validate_header(self)

	def _validate_gtin(self):
		# Trống được (loại bộ chưa có GTIN thì chưa sinh được Cycle ID); lưu NULL để chỉ mục unique
		# không coi nhiều dòng "" là trùng nhau.
		self.gtin = (self.gtin or "").strip() or None
		self._guard_gtin_after_pack()
		if self.gtin is None:
			return
		if not gs1.is_valid_gtin14(self.gtin):
			frappe.throw(_("GTIN-14 must be 14 digits with a valid check digit."))
		used_by = frappe.db.get_value(
			"Instrument Set Type", {"gtin": self.gtin, "name": ("!=", self.name)}, "name"
		)
		if used_by:
			frappe.throw(_("GTIN-14 {0} is already used by Set Type {1}.").format(self.gtin, used_by))

	def _guard_gtin_after_pack(self):
		# GTIN đã in vào Cycle ID của gói thì không đổi nữa (D6). Đọc Pack theo tên DocType, không import M2.
		if self.is_new():
			return
		current = frappe.db.get_value("Instrument Set Type", self.name, "gtin") or None
		if self.gtin != current and frappe.db.exists("Pack", {"set_type": self.name}):
			frappe.throw(
				_(
					"GTIN-14 of Set Type {0} cannot be changed because packs have already been issued for it."
				).format(self.name)
			)
