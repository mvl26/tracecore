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
WASH_TYPES = ("Washer-Disinfector", "Ultrasonic Cleaner")
STERILIZER_TYPES = ("Steam Sterilizer", "Plasma Sterilizer")
LAUNDRY_TYPES = ("Laundry Washer", "Dryer")
DRYER_TYPE = "Dryer"
KIND_REGULAR, KIND_TEST = "Regular", "Test"
PACKAGING_GROUP = "Packaging"
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
		self._normalize_kind()
		self._normalize_wash_indicator()
		self._validate_norms()
		self._validate_laundry()
		self._apply_norms()
		self._validate_consumables()
		self._default_unit_prices()
		self._validate_consumable_units()
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

	def _normalize_kind(self):
		# chương trình test chỉ có ở máy tiệt khuẩn và không bao giờ nhận gói (A-83)
		if norms.equipment_type_of(self) not in STERILIZER_TYPES:
			self.program_kind = KIND_REGULAR
		self.program_kind = self.program_kind or KIND_REGULAR
		if self.program_kind == KIND_TEST:
			self.compatible_pack_types = []

	def _normalize_wash_indicator(self):
		# chỉ thị rửa chỉ có nghĩa với máy rửa/siêu âm (A-77); ảnh chỉ bắt buộc khi chỉ thị bắt buộc
		if norms.equipment_type_of(self) not in WASH_TYPES:
			self.requires_wash_indicator = 0
		if not cint(self.requires_wash_indicator):
			self.requires_wash_indicator_photo = 0

	def _validate_norms(self):
		for fieldname, label in NON_NEGATIVE_FIELDS:
			if flt(self.get(fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(label)))

	def _validate_laundry(self):
		"""Chương trình giặt/sấy (A-104): tải tối đa không vượt tải máy; máy sấy không dùng nước (BRU-LIN-005)."""
		equipment_type = norms.equipment_type_of(self)
		if equipment_type not in LAUNDRY_TYPES:
			return
		load = flt(self.get("max_load_kg"))
		if load < 0:
			frappe.throw(_("{0} cannot be negative.").format(_("Max Load per Batch (kg)")))
		capacity = flt(frappe.db.get_value("Equipment", self.equipment, "capacity_kg"))
		if capacity and load > capacity:
			frappe.throw(
				_("Max load {0} kg is above the {1} kg capacity of machine {2}.").format(
					load, capacity, self.equipment
				)
			)
		if equipment_type == DRYER_TYPE and flt(self.water_l_per_cycle) > 0:
			frappe.throw(_("A dryer program uses no water: set Water per Cycle to 0."))

	def _default_unit_prices(self):
		"""Dòng định mức của chương trình giặt/sấy chưa có đơn giá thì lấy giá trị tồn kho của vật tư; đã nhập thì giữ (A-104)."""
		laundry = norms.equipment_type_of(self) in LAUNDRY_TYPES
		for row in self.consumables:
			if flt(row.get("unit_price")) < 0:
				frappe.throw(_("Row {0}: the unit price cannot be negative.").format(row.idx))
			if laundry and not flt(row.get("unit_price")):
				row.unit_price = flt(frappe.db.get_value("Item", row.item, "valuation_rate"), 0)

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
			if flt(row.qty_per_load) < 0 or flt(row.qty_per_pack) < 0 or flt(row.qty_per_kg) < 0:
				frappe.throw(_("Row {0}: quantities cannot be negative.").format(row.idx))
			if flt(row.qty_per_load) <= 0 and flt(row.qty_per_pack) <= 0 and flt(row.qty_per_kg) <= 0:
				frappe.throw(
					_("Row {0}: enter a quantity per load, per pack or per kg greater than zero.").format(
						row.idx
					)
				)

	def _validate_consumable_units(self):
		"""Định mức khai theo ĐVT khác ĐVT tồn kho (vd. ml cho hóa chất tồn theo Can) cần dòng quy đổi trên Item (A-72)."""
		for row in self.consumables:
			stock_uom = frappe.db.get_value("Item", row.item, "stock_uom")
			if not row.uom or row.uom == stock_uom:
				continue
			factor = flt(
				frappe.db.get_value(
					"UOM Conversion Detail",
					{"parent": row.item, "parenttype": "Item", "uom": row.uom},
					"conversion_factor",
				)
			)
			if not factor:
				frappe.throw(
					_(
						"Row {0}: item {1} has no conversion from {2} to {3}. Add it to the unit of measure table of the item."
					).format(row.idx, row.item, row.uom, stock_uom)
				)
			if not frappe.db.get_value("UOM", stock_uom, "must_be_whole_number"):
				continue
			for qty in (row.qty_per_load, row.qty_per_pack, row.qty_per_kg):
				stock_qty = flt(qty) * factor
				if abs(stock_qty - round(stock_qty)) > 1e-7:
					frappe.msgprint(
						_(
							"Row {0}: item {1} is stocked in {2}, which must be a whole number, so a norm of {3} {4} ({5} {2}) cannot be deducted. Turn off 'Must be Whole Number' in unit {2}."
						).format(row.idx, row.item, stock_uom, qty, row.uom, flt(stock_qty, 6)),
						indicator="orange",
					)
					break

	def _validate_pack_types(self):
		seen = set()
		for row in self.compatible_pack_types:
			if row.pack_type in seen:
				frappe.throw(_("Row {0}: pack type {1} is listed twice.").format(row.idx, row.pack_type))
			seen.add(row.pack_type)
		if norms.equipment_type_of(self) not in STERILIZER_TYPES or self.program_kind == KIND_TEST:
			return
		for row in self.compatible_pack_types:
			if frappe.db.get_value("Item", row.pack_type, "tc_item_group_cssd") != PACKAGING_GROUP:
				frappe.throw(_("Row {0}: item {1} is not a packaging item.").format(row.idx, row.pack_type))
		# chương trình đã ngừng dùng vẫn lưu được; nhập từ file chưa có cột loại gói, danh sách rỗng thì chưa nhận gói (A-83)
		if cint(self.is_active) and not self.compatible_pack_types and not self.flags.tc_import_no_pack_types:
			frappe.throw(
				_(
					"Program {0} is a regular sterilization program: list at least one compatible pack type."
				).format(self.program_code)
			)

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
			self._validate_default_value(row, low, high)

	def _validate_default_value(self, row, low, high):
		# A-89: giá trị điền sẵn form chu trình; rỗng = không có mặc định
		text = (row.default_value or "").strip().replace(",", ".")
		row.default_value = text or None
		if not text:
			return
		try:
			value = float(text)
		except ValueError:
			frappe.throw(
				_("Row {0}: Default Value of parameter {1} must be a number.").format(
					row.idx, row.parameter_name
				)
			)
		if (low > 0 and value < low) or (high > 0 and value > high):
			frappe.throw(
				_("Row {0}: Default Value of parameter {1} is outside its range.").format(
					row.idx, row.parameter_name
				)
			)
