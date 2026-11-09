"""IC Annual Plan — kế hoạch KSNK năm (FEAT-058; FR-M11-04..06; BRU-ICP-004). Logic ở ``annual_plan``."""

from frappe.model.document import Document

from tracecore.infection_program import annual_plan


class ICAnnualPlan(Document):
	def validate(self):
		annual_plan.validate(self)

	def validate_amended_from(self):
		# A-133 Q1: bản sửa đổi lập khi bản gốc còn hiệu lực (Frappe chuẩn đòi bản gốc đã Hủy)
		annual_plan.check_amended_from(self)

	def before_update_after_submit(self):
		annual_plan.guard_after_submit(self)

	def before_submit(self):
		annual_plan.before_submit(self)

	def on_submit(self):
		annual_plan.on_submit(self)
