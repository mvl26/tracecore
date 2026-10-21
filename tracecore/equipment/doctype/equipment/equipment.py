"""Equipment: hồ sơ thiết bị CSSD (FR-M5-01, FEAT-038).

Mã ``TB-.####`` do hệ thống sinh và ghi Code Registry; khu vào/ra theo ``core.zones``; khấu hao/mẻ tính
trên chính bản ghi (Q2); ``status`` chỉ đổi qua ``equipment.status.set_status`` bằng cờ ``flags.tc_equipment``
(giống guard của Pack), chuyển sang ``Retired`` là một chiều.
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import cint, flt, getdate, today

from tracecore.core import audit, code_registry, zones

CODE_PREFIX = "TB"
CONTROLLED_FIELDS = ("status", "retired_on", "retired_reason")
SAFE_RANGE_FIELDS = ("safe_temp_min", "safe_temp_max", "safe_pressure_max")
RECOMPUTE_SAVEPOINT = "tc_equipment_programs"
DEFAULT_STATUS = "Ready"


def compute_depreciation_per_load(purchase_value, years, loads) -> int:
	"""Nguyên giá chia (số năm nhân số mẻ/năm), làm tròn nửa lên đến đồng; 0 khi một số hạng bằng 0."""
	divisor = flt(years) * flt(loads)
	if not flt(purchase_value) or divisor <= 0:
		return 0
	value = Decimal(str(flt(purchase_value))) / (Decimal(str(flt(years))) * Decimal(str(flt(loads))))
	return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


class Equipment(Document):
	def autoname(self):
		# mã không bao giờ lấy từ người dùng; bỏ qua số đã dùng
		while True:
			name = make_autoname("TB-.####", doc=self)
			if not frappe.db.exists("Equipment", name):
				self.name = name
				return

	def validate(self):
		self._guard_controlled_fields()
		self._guard_equipment_type()
		self.serial_no = (self.serial_no or "").strip()
		self._validate_serial()
		self._validate_cost()
		self._validate_zones()
		self._validate_safe_range()
		self._validate_retirement()
		self.depreciation_per_load = compute_depreciation_per_load(
			self.purchase_value, self.depreciation_years, self.planned_loads_year
		)

	def after_insert(self):
		if not code_registry.is_issued(self.name):
			code_registry.register(self.name, CODE_PREFIX, "Equipment", self.name)

	def on_update(self):
		if not self.flags.in_insert and any(self.has_value_changed(f) for f in SAFE_RANGE_FIELDS):
			self._recompute_programs()

	def on_trash(self):
		audit.block_delete(self, "on_trash")

	def _guard_equipment_type(self):
		# norm_status / outside_safe_range của chương trình tính theo loại máy: máy không đổi loại (set_only_once)
		before = None if self.is_new() else self.get_doc_before_save()
		if before and before.equipment_type != self.equipment_type:
			frappe.throw(_("Equipment Type cannot be changed after the equipment is created."))

	def _recompute_programs(self):
		"""Dải an toàn đổi: lưu lại mọi chương trình của máy qua validate để cờ ngoài dải và định mức tính lại, có audit.

		Chương trình không lưu lại được thì ghi Error Log và bỏ qua; không bao giờ chặn việc lưu thiết bị.
		"""
		for name in frappe.get_all(
			"Process Program", filters={"equipment": self.name}, pluck="name", order_by="name asc"
		):
			messages = len(frappe.local.message_log)
			frappe.db.savepoint(RECOMPUTE_SAVEPOINT)
			try:
				frappe.get_doc("Process Program", name).save(ignore_permissions=True)
			except Exception:
				frappe.db.rollback(save_point=RECOMPUTE_SAVEPOINT)
				del frappe.local.message_log[messages:]
				frappe.log_error(
					title=_("Process program {0} was not recalculated after the safe range changed").format(
						name
					),
					reference_doctype="Process Program",
					reference_name=name,
				)

	def _guard_controlled_fields(self):
		if self.flags.tc_equipment:
			return
		before = self.get_doc_before_save()
		if self.is_new() and not self.status:
			self.status = DEFAULT_STATUS
		for field in CONTROLLED_FIELDS:
			old = before.get(field) if before else (DEFAULT_STATUS if field == "status" else None)
			if str(self.get(field) or "") != str(old or ""):
				frappe.throw(
					_("Equipment status and retirement fields are changed only by the equipment service.")
				)

	def _validate_serial(self):
		if not self.serial_no:
			frappe.throw(_("Serial No is required."))
		key = self.serial_no.casefold()
		candidates = frappe.get_all(
			"Equipment",
			filters={"serial_no": self.serial_no, "name": ("!=", self.name)},
			fields=["name", "serial_no"],
		)
		for row in candidates:
			if (row.serial_no or "").strip().casefold() == key:
				frappe.throw(
					_("Serial No {0} is already used by equipment {1}.").format(self.serial_no, row.name)
				)

	def _validate_cost(self):
		if flt(self.purchase_value) < 0:
			frappe.throw(_("Purchase Value cannot be negative."))
		if cint(self.depreciation_years) < 1:
			frappe.throw(_("Depreciation Years must be at least 1."))
		if cint(self.planned_loads_year) < 1:
			frappe.throw(_("Planned Loads per Year must be at least 1."))

	def _validate_zones(self):
		# check_pass_through kiểm zone_in là khu (không phải trạm) và quy tắc máy hai cửa
		zones.check_pass_through(self.zone_in, self.zone_out or None)

	def _validate_safe_range(self):
		# Int chưa nhập đọc lại là 0 → 0 nghĩa là "không đặt"
		low, high = cint(self.safe_temp_min), cint(self.safe_temp_max)
		if low and high and low > high:
			frappe.throw(_("Safe Temperature Min cannot be above Safe Temperature Max."))

	def _validate_retirement(self):
		if self.status == "Retired":
			if not (self.retired_reason or "").strip():
				frappe.throw(_("A reason is required to retire equipment."))
			if not self.retired_on:
				self.retired_on = today()
			elif getdate(self.retired_on) > getdate(today()):
				frappe.throw(_("Retired On cannot be in the future."))
		before = self.get_doc_before_save()
		if before and before.status == "Retired" and self.status != "Retired":
			frappe.throw(_("Retired equipment cannot be put back into use."))
