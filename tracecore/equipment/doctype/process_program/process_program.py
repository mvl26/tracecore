"""Process Program: chương trình xử lý của một máy (FR-M5-02, FEAT-038).

Mã chương trình viết hoa, chỉ ``[A-Z0-9-]``, là tên bản ghi. Không xóa: ngừng dùng bằng ``is_active = 0``
và mọi dữ liệu được giữ (FR-M5-02.3, BRU-EQP-003). ``norm_status`` / ``outside_safe_range`` là trường chỉ
đọc do ``validate`` tính qua ``tracecore.equipment.norms``; thiếu định mức hay ngoài dải chỉ cảnh báo, không chặn.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from tracecore.core import audit
from tracecore.equipment import norms

PROGRAM_CODE_PATTERN = re.compile(r"[A-Z0-9-]+")
NON_NEGATIVE_FIELDS = (
	("duration_min", "Duration (min)"),
	("kwh_per_cycle", "Electricity per Cycle (kWh)"),
	("water_l_per_cycle", "Water per Cycle (L)"),
	("steam_kg_per_cycle", "Steam per Cycle (kg)"),
)


def _normalize_code(code):
	code = (code or "").strip().upper()
	if not PROGRAM_CODE_PATTERN.fullmatch(code):
		frappe.throw(_("Program Code may contain only uppercase letters, digits and hyphens."))
	return code


class ProcessProgram(Document):
	def before_naming(self):
		# name = mã: chuẩn hóa và kiểm tra trước khi đặt tên
		self.program_code = _normalize_code(self.program_code)

	def validate(self):
		self.program_code = _normalize_code(self.program_code)
		self._validate_equipment()
		self._validate_norms()
		self._apply_norms()
		self._validate_consumables()
		self._validate_pack_types()
		self._validate_parameters()
		self._warn_safe_range()

	def on_trash(self):
		audit.block_delete(self, "on_trash")

	def _validate_equipment(self):
		# chặn tạo mới và bật lại chương trình trên máy đã ngừng; chương trình có sẵn vẫn sửa/ngừng dùng được
		reactivated = self.is_active and self.has_value_changed("is_active")
		if not (self.is_new() or reactivated):
			return
		if frappe.db.get_value("Equipment", self.equipment, "status") == "Retired":
			if self.is_new():
				frappe.throw(
					_("Equipment {0} is retired and cannot get a new process program.").format(self.equipment)
				)
			frappe.throw(
				_("Equipment {0} is retired: its process programs cannot be activated again.").format(
					self.equipment
				)
			)

	def _validate_norms(self):
		for fieldname, label in NON_NEGATIVE_FIELDS:
			if flt(self.get(fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(label)))

	def _apply_norms(self):
		if cint(self.use_default_norms) and not norms.default_norm(norms.equipment_type_of(self)):
			frappe.throw(
				_("Equipment type {0} has no default norms: add an Equipment Type Norm first.").format(
					_(norms.equipment_type_of(self), context="Equipment")
				)
			)
		status = norms.norm_status(self)
		if status == "Default":
			norms.apply_default(self)
		self.norm_status = status
		if status == "Missing":
			warning = _("Program {0} has incomplete norms: costing is not calculated until the norms are complete or default norms are used.")  # fmt: skip
			frappe.msgprint(warning.format(self.program_code), indicator="orange")

	def _warn_safe_range(self):
		equipment = frappe.db.get_value(
			"Equipment", self.equipment, ["safe_temp_min", "safe_temp_max", "safe_pressure_max"], as_dict=True
		)
		warnings = norms.range_warnings(self, equipment) if equipment else []
		self.outside_safe_range = 1 if warnings else 0
		for message in warnings:
			frappe.msgprint(message, indicator="orange")

	def _validate_consumables(self):
		seen = set()
		for row in self.consumables:
			if row.item in seen:
				frappe.throw(_("Row {0}: consumable {1} is listed twice.").format(row.idx, row.item))
			seen.add(row.item)
			if flt(row.qty_per_load) < 0 or flt(row.qty_per_pack) < 0:
				frappe.throw(_("Row {0}: quantities cannot be negative.").format(row.idx))
			if flt(row.qty_per_load) <= 0 and flt(row.qty_per_pack) <= 0:
				frappe.throw(
					_("Row {0}: enter a quantity per load or per pack greater than zero.").format(row.idx)
				)

	def _validate_pack_types(self):
		seen = set()
		for row in self.compatible_pack_types:
			if row.pack_type in seen:
				frappe.throw(_("Row {0}: pack type {1} is listed twice.").format(row.idx, row.pack_type))
			seen.add(row.pack_type)

	def _validate_parameters(self):
		seen = set()
		for row in self.parameters:
			row.parameter_name = (row.parameter_name or "").strip()
			if not row.parameter_name:
				frappe.throw(_("Row {0}: parameter name is required.").format(row.idx))
			key = row.parameter_name.casefold()
			if key in seen:
				frappe.throw(_("Row {0}: parameter {1} is listed twice.").format(row.idx, row.parameter_name))
			seen.add(key)
			# Float chưa nhập đọc lại là 0 = "không đặt" đầu đó: chỉ kiểm khi đặt cả hai (dải một phía hợp lệ)
			low, high = flt(row.min_value), flt(row.max_value)
			if low > 0 and high > 0 and low > high:
				frappe.throw(
					_("Row {0}: Minimum cannot be above Maximum for parameter {1}.").format(
						row.idx, row.parameter_name
					)
				)
