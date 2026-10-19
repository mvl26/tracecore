"""Set Unit: bộ dụng cụ vật lý; Set ID GIAI do hệ thống cấp, không sửa (FR-M1-05, BRU-ID-001).

Trạng thái (`status`) chỉ được đổi bởi `tracecore.core.step_gate` (ADR-005).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from tracecore.core import code_registry

# Trường vòng đời: read_only trên form không được Frappe kiểm ở server, nên chặn tại đây.
# Chỉ core.step_gate được đổi, bằng cờ flags.tc_step_gate — ADR-005.
LIFECYCLE_DEFAULTS = {"status": "New", "cycles_used": 0, "current_station": None, "active_cycle_id": None}


class SetUnit(Document):
	def before_naming(self):
		# Set ID luôn do hệ thống cấp (FR-M9-07): bỏ mọi tên nhập tay, kể cả khi import
		self.name = None

	def autoname(self):
		type_code = frappe.db.get_value("Instrument Set Type", self.set_type, "type_code")
		if not type_code:
			frappe.throw(_("Set Type {0} not found.").format(self.set_type))
		self.name = self.set_id = code_registry.next_set_id(type_code)

	def validate(self):
		if self.set_id != self.name:
			frappe.throw(_("Set ID is issued by the system and cannot be changed."))
		if cint(self.max_cycles) <= 0:
			frappe.throw(_("Max Cycles must be greater than zero."))
		if not self.flags.tc_step_gate:
			self._guard_lifecycle_fields()

	def _guard_lifecycle_fields(self):
		if self.is_new():
			self.update(LIFECYCLE_DEFAULTS)
			return
		before = self.get_doc_before_save()
		changed = [
			f for f in LIFECYCLE_DEFAULTS if before and str(before.get(f) or "") != str(self.get(f) or "")
		]
		if changed:
			frappe.throw(
				_("Status and cycle fields are changed only by the step gate: {0}").format(", ".join(changed))
			)
