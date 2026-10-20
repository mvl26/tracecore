"""Assembly Record: stub của trạm T3 trong FEAT-018; ghi sổ chứng từ thì ghi cổng T3 của chu trình hiện hành.

Chứng từ Lắp ráp đầy đủ (kiểm đếm dụng cụ, BOM…) thay thế stub này ở FEAT của T3; cổng T3 vẫn do
`tracecore.core.step_gate` ghi (ADR-005).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from tracecore.core import step_gate


class AssemblyRecord(Document):
	def validate(self):
		if not self.set_unit or not frappe.db.exists("Set Unit", self.set_unit):
			return  # kiểm trường bắt buộc/liên kết sẽ báo
		current = cint(frappe.db.get_value("Set Unit", self.set_unit, "current_cycle_no"))
		if not current:
			frappe.throw(_("No cycle has been started for Set Unit {0}.").format(self.set_unit))
		if self.is_new():
			self.cycle_no = current
		elif cint(self.cycle_no) != current:
			frappe.throw(
				_("Set Unit {0} is no longer in cycle {1}; create a new Assembly Record.").format(
					self.set_unit, self.cycle_no
				)
			)

	def on_submit(self):
		step_gate.record(self.set_unit, "T3", self.result, self.doctype, self.name)

	def before_cancel(self):
		# Hủy chứng từ phải đưa cổng T3 về lại; việc đó thuộc FEAT của T3, stub chưa hỗ trợ.
		frappe.throw(_("Assembly Record cannot be cancelled in this version."))
