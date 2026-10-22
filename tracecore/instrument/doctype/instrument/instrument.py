"""Instrument: dụng cụ đơn lẻ (DT-INSTR, FR-M1-01, A-06 I9-I15).

Mã chuẩn hóa và gợi ý mã trùng ở ``instrument.catalog``. Trường bắt buộc (mã, tên, Spaulding, ít nhất một phương
pháp) nêu trong một thông báo; chuỗi chỉ toàn khoảng trắng coi như thiếu. ``status``, ``retired_on``,
``retired_reason``, ``version_no`` chỉ đổi qua dịch vụ danh mục (cờ ``flags.tc_instrument``): ngừng sử dụng qua
``catalog.retire`` (một chiều), phiên bản tăng khi tập phương pháp đổi (``versions``, A-06 I1/I3).
Ảnh/IFU phải là File riêng tư đính vào chính dụng cụ; ``image_thumbnail`` do ``media.refresh_thumbnail`` sinh từ ảnh,
không sửa tay được (A-06 I11). Mã GIAI khắc laser (``giai_code``, ``giai_etched_on``, ``giai_position``) chỉ ghi qua
``catalog.assign_giai``/``catalog.record_etching`` (cờ ``flags.tc_giai``); mã đã cấp không đổi, không xóa; cờ tính năng
tắt vẫn lưu được dụng cụ có mã cũ (A-06 I7/I8, FR-M1-02.3).
"""

from decimal import ROUND_HALF_UP, Decimal

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from tracecore.instrument import catalog, media, thresholds, versions

REQUIRED_FIELDS = ("instrument_code", "instrument_name", "spaulding_class", "compatible_methods")
TEXT_FIELDS = ("instrument_name", "manufacturer", "model")
CONTROLLED_DEFAULTS = {"status": "Active", "retired_on": None, "retired_reason": None, "version_no": 1}
# trường dẫn xuất từ file (A-06 I11): chỉ media.refresh_thumbnail ghi, kể cả khi lưu qua cờ của danh mục
DERIVED_FIELDS = ("image_thumbnail",)
# mã GIAI khắc laser và bản ghi khắc (A-06 I8): chỉ dịch vụ danh mục ghi (flags.tc_giai)
GIAI_FIELDS = ("giai_code", "giai_etched_on", "giai_position")


def _round_vnd(value) -> int:
	return int(Decimal(str(flt(value))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


class Instrument(Document):
	def onload(self):
		# form ẩn/hiện khối GIAI theo cờ TraceCore Settings (depends_on đọc __onload)
		self.set_onload("giai_enabled", catalog.giai_enabled())

	def before_insert(self):
		self._prepare()
		if catalog.code_exists(self.instrument_code):
			catalog.throw_duplicate(self.instrument_code)

	def validate(self):
		self._prepare()
		if not self.is_new() and self.instrument_code != self.name:
			frappe.throw(_("Instrument Code cannot be changed after the instrument is created."))
		self._guard_retirement()
		self._guard_controlled_fields()
		self._guard_derived_fields()
		self._guard_giai_fields()
		media.validate_fields(self)
		self._validate_methods()
		versions.bump_if_methods_changed(self)
		self._validate_value()
		if not self._is_service_update():
			self._validate_item()
		self.max_cycles_status = "Defined" if cint(self.max_cycles) > 0 else "Undefined"
		media.refresh_thumbnail(self)

	def on_update(self):
		if self.flags.tc_version_bumped:
			versions.notify_boms(self)
		# đổi ngưỡng/nhóm: cảnh báo bộ sẽ đến hạn, không đụng bộ đếm (A-06 I5, Review Focus 4)
		thresholds.warn_rule_change(self)

	def db_insert(self, *args, **kwargs):
		# hai request cùng mã vượt qua kiểm tra trước: khóa chính chặn bản ghi thứ hai, báo kèm mã gợi ý
		try:
			return super().db_insert(*args, **kwargs)
		except (frappe.DuplicateEntryError, frappe.UniqueValidationError):
			catalog.throw_duplicate(self.instrument_code)

	def _prepare(self):
		for field in TEXT_FIELDS:
			if self.get(field) is not None:
				self.set(field, str(self.get(field)).strip())
		code = (self.instrument_code or "").strip()
		if not self._is_service_update():
			self._check_required(code)
		self.instrument_code = catalog.normalize_code(code)

	def _check_required(self, code):
		missing = []
		for field in REQUIRED_FIELDS:
			value = code if field == "instrument_code" else self.get(field)
			if field == "compatible_methods":
				value = catalog.method_set(self)
			if not value:
				missing.append(_(self.meta.get_label(field), context="Instrument"))
		if missing:
			frappe.throw(
				_("Required fields are missing: {0}.").format(", ".join(missing)),
				frappe.MandatoryError,
				title=_("Missing Values Required"),
			)

	def _is_retiring(self):
		# catalog.retire chỉ đổi trạng thái: dụng cụ cũ thiếu Spaulding/phương pháp hoặc Item đã bị vô hiệu sau này
		# vẫn phải ngừng sử dụng được (FEAT-014 Task 2 review)
		if not self.flags.tc_instrument or self.is_new() or self.status != "Retired":
			return False
		before = self.get_doc_before_save()
		return bool(before) and before.status != "Retired"

	def _is_service_update(self):
		# ngừng sử dụng và ghi mã GIAI chỉ đổi trường của dịch vụ: dụng cụ cũ thiếu trường bắt buộc vẫn đi qua
		return self._is_retiring() or bool(self.flags.tc_giai and not self.is_new())

	def _guard_giai_fields(self):
		before = None if self.is_new() else self.get_doc_before_save()
		for field in GIAI_FIELDS:
			old = before.get(field) if before else None
			if str(self.get(field) or "") == str(old or ""):
				continue
			if not self.flags.tc_giai:
				frappe.throw(
					_(
						"The GIAI code and etching record are set only by TraceCore (Assign GIAI, Record Etching)."
					)
				)
			if field == "giai_code" and old:
				frappe.throw(
					_("GIAI code {0} is already assigned and cannot be changed or removed.").format(old)
				)

	def _guard_retirement(self):
		# Ngừng sử dụng là một chiều (I13), kể cả khi lưu qua cờ của danh mục
		before = None if self.is_new() else self.get_doc_before_save()
		if before and before.status == "Retired" and self.status != "Retired":
			frappe.throw(_("A retired instrument cannot be returned to use."))

	def _guard_controlled_fields(self):
		if self.flags.tc_instrument:
			return
		before = None if self.is_new() else self.get_doc_before_save()
		for field, default in CONTROLLED_DEFAULTS.items():
			old = before.get(field) if before else default
			if str(self.get(field) or "") != str(old or ""):
				frappe.throw(
					_("Instrument status, retirement and version are changed only by the instrument catalog.")
				)

	def _guard_derived_fields(self):
		before = None if self.is_new() else self.get_doc_before_save()
		for field in DERIVED_FIELDS:
			old = before.get(field) if before else None
			if (self.get(field) or "") != (old or ""):
				frappe.throw(
					_(
						"The image thumbnail is generated by TraceCore from the instrument photo and cannot be edited."
					)
				)

	def _validate_methods(self):
		seen = set()
		for row in self.compatible_methods:
			if row.method in seen:
				frappe.throw(
					_("Compatible method {0} is listed more than once.").format(
						_(row.method, context="Instrument Compatible Method")
					)
				)
			seen.add(row.method)

	def _validate_value(self):
		if flt(self.value) < 0:
			frappe.throw(_("Value cannot be negative."))
		self.value = _round_vnd(self.value)

	def _validate_item(self):
		if self.item and cint(frappe.db.get_value("Item", self.item, "disabled")):
			frappe.throw(_("Item {0} is disabled and cannot be linked to an instrument.").format(self.item))
