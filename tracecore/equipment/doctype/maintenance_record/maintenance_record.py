"""Maintenance Record: hồ sơ bảo trì, kiểm định, hiệu chuẩn, sự cố của máy (FEAT-039, UC-22; architecture §5.3 DT-MAINT, A-42).

Controller chỉ kiểm dữ liệu (số không âm, thành tiền phụ tùng); ghi sổ, lịch kế tiếp và đổi trạng thái máy do
`equipment.maintenance`. Không xóa (on_trash).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from tracecore.core import audit
from tracecore.equipment import maintenance


class MaintenanceRecord(Document):
	def validate(self):
		self.validate_numbers()
		self.compute_part_amounts()

	def before_submit(self):
		maintenance.before_submit(self)

	def on_submit(self):
		maintenance.on_submit(self)

	def validate_numbers(self):
		"""Chi phí, thời gian dừng, chu kỳ và SLA không âm (UC-22 E3)."""
		for label, value in (
			(_("Cost"), self.cost),
			(_("Downtime (hours)"), self.downtime_hours),
			(_("Cycle (months)"), self.cycle_months),
			(_("SLA (hours)"), self.sla_hours),
		):
			if flt(value) < 0:
				frappe.throw(_("{0} cannot be negative.").format(label))
		for row in self.parts:
			if flt(row.qty) < 0 or flt(row.rate) < 0:
				frappe.throw(_("Row {0}: quantity and rate cannot be negative.").format(row.idx))

	def compute_part_amounts(self):
		for row in self.parts:
			row.amount = flt(row.qty) * flt(row.rate)

	def on_trash(self):
		audit.block_delete(self, "on_trash")
