"""Instrument Set Type: mã loại bộ dùng trong Set ID GIAI (§5.3.3) và dữ liệu đóng gói T4 (FEAT-018).

GTIN-14 của loại bộ (AI 01 của Cycle ID): tự cấp khi tạo nếu viện đã khai mã doanh nghiệp GS1, vẫn nhập tay được; đã in
lên nhãn thì khóa, R10 đổi có lý do qua tracecore.instrument.gtin (A-76).
Luật phần đầu FEAT-015 (khoa, loại gói có hạn lưu, ghi đè ngắn hơn, cấy ghép, thời gian lắp ráp, phiên bản BOM hiện
hành chỉ server ghi, đổi phương pháp kiểm lại BOM) ở tracecore.instrument.set_type; tạo loại bộ (cùng BOM v1), phiên bản
BOM, sao chép ở tracecore.instrument.bom_versions. Ảnh bộ đã xếp ``tray_image``/``_2``/``_3`` và thumbnail
``tray_thumbnail``/``_2``/``_3`` (chỉ server ghi) theo luật file chung ở tracecore.instrument.media (S6).
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import code_registry, gs1
from tracecore.instrument import bom, media
from tracecore.instrument import gtin as gtin_rules
from tracecore.instrument import set_type as set_type_rules

TYPE_CODE_PATTERN = re.compile(r"[A-Z0-9]{2,8}")


class InstrumentSetType(Document):
	def before_naming(self):
		self.type_code = (self.type_code or "").strip().upper()

	def validate(self):
		# FR-M1-03.1, S1: loại bộ chỉ tạo cùng BOM phiên bản 1 qua tracecore.instrument.bom_versions (cờ flags.tc_bom);
		# Desk "New", Duplicate, frappe.client.insert đều bị chặn
		if self.is_new() and not self.flags.tc_bom:
			frappe.throw(_("A set type can only be created together with its BOM version 1."))
		self.type_code = (self.type_code or "").strip().upper()
		if not TYPE_CODE_PATTERN.fullmatch(self.type_code):
			frappe.throw(_("Type Code must be 2-8 uppercase letters or digits."))
		self._validate_gtin()
		set_type_rules.validate_header(self)
		# S6: 1-3 ảnh bộ đã xếp cùng luật file với ảnh dụng cụ (File riêng tư của chính loại bộ, kiểm nội dung),
		# thumbnail 320 px chỉ server ghi
		media.validate_fields(self)
		media.refresh_thumbnail(self)
		# cấp sau cùng: kiểm tra phần đầu sai thì khỏi tốn số (A-76). Loại bộ mượn luôn mang sẵn GTIN của hãng.
		if self.is_new() and not self.gtin:
			self.gtin = code_registry.next_gtin(self.doctype, self.name)

	def on_update(self):
		# tên/phương pháp/ảnh khay (và thumbnail) nằm trong payload BOM của trạm: xóa cache mọi phiên bản (S11)
		if bom.payload_changed(self, bom.SET_TYPE_PAYLOAD_FIELDS):
			bom.invalidate(set_type=self.name)

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
		on_label = frappe.db.get_value("Pack", {"gtin": self.gtin, "set_type": ("!=", self.name)}, "set_type")
		if on_label:
			frappe.throw(_("GTIN-14 {0} is already used by Set Type {1}.").format(self.gtin, on_label))
		self._warn_foreign_prefix()

	def _warn_foreign_prefix(self):
		current = None if self.is_new() else frappe.db.get_value("Instrument Set Type", self.name, "gtin")
		if self.gtin != current and gtin_rules.is_foreign(self.name, self.gtin):
			frappe.msgprint(
				_("GTIN-14 {0} does not start with the declared GS1 company prefix {1}.").format(
					self.gtin, gs1.declared_company_prefix()
				),
				indicator="orange",
				alert=True,
			)

	def _guard_gtin_after_pack(self):
		# GTIN đã in vào Cycle ID của gói thì không đổi bằng đường lưu thường (D6); R10 đổi qua gtin.change_locked (A-76)
		if self.is_new() or self.flags.tc_gtin_unlock:
			return
		current = frappe.db.get_value("Instrument Set Type", self.name, "gtin") or None
		if self.gtin != current and gtin_rules.pack_count(self.name, current):
			frappe.throw(
				_(
					"GTIN-14 of Set Type {0} cannot be changed because packs have already been issued for it."
				).format(self.name)
			)
