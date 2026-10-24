"""Par Override: ghi đè cơ số có phê duyệt (DT-OVERRIDE, M8, FEAT-032, FR-M8-04, WF-08); luật ở ``tracecore.par.override``.

Requested (Nháp) → Approved / Rejected (Ghi sổ) → Expired; Hủy = Cancelled. Chỉ dịch vụ ``par.override`` được ghi quyết
định và bộ đếm (cờ ``flags.tc_par_override``); không submit tay, không xóa (Audit ``block_delete``).
"""

from frappe.model.document import Document

from tracecore.par import override


class ParOverride(Document):
	def validate(self):
		override.validate(self)

	def after_insert(self):
		override.after_insert(self)

	def before_submit(self):
		override.guard_submit(self)

	def before_cancel(self):
		override.before_cancel(self)

	def before_update_after_submit(self):
		override.guard_changes(self)
