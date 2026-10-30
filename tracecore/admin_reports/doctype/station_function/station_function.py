"""Station Function: danh mục chức năng trạm (A-64, FEAT-051).

Chức năng hệ thống (``is_system``) có màn và cổng do code quy định: R10 chỉ đổi tên và bật/tắt. Chức năng R10 tự tạo chỉ
có màn tra cứu chung và không ghi cổng. Thứ tự các chức năng có cổng không cấu hình được (FR-M2-00.4, BRU-FLOW-003).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from tracecore.core import audit, zones

LOCKED_FIELDS = ("process_order", "gate_step", "screen_key", "is_required", "is_system")


class StationFunction(Document):
	def validate(self):
		if self.flags.tc_seed:  # chỉ ``seed.ensure_station_catalog`` tạo chức năng hệ thống
			return
		before = self.get_doc_before_save()
		if before and cint(before.is_system):
			self._validate_system_unchanged(before)
		elif self.gate_step or self.screen_key or cint(self.is_system) or cint(self.is_required):
			frappe.throw(_("Only system functions have a gate or a business screen."), frappe.ValidationError)
		if before and cint(before.is_active) and not cint(self.is_active):
			self._validate_not_in_use()

	def on_trash(self):
		audit.block_delete(self, "on_trash")

	def _validate_system_unchanged(self, before):
		for fieldname in LOCKED_FIELDS:
			if str(before.get(fieldname) or "") != str(self.get(fieldname) or ""):
				frappe.throw(
					_("{0} of a system function cannot be changed.").format(_(self.meta.get_label(fieldname))),
					frappe.ValidationError,
				)

	def _validate_not_in_use(self):
		stations = zones.stations_with_function(self.name)
		if stations:
			frappe.throw(
				_("Function {0} is used by active stations: {1}.").format(
					_(self.function_name), ", ".join(stations)
				),
				frappe.ValidationError,
			)
