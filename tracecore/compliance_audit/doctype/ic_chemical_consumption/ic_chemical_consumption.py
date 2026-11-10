"""IC Chemical Consumption — hóa chất KSNK theo khoa-tháng (FEAT-066, A-142). Luật ở ``compliance_audit.chemicals``."""

from frappe.model.document import Document

from tracecore.compliance_audit import chemicals


class ICChemicalConsumption(Document):
	def validate(self):
		chemicals.validate(self)

	def before_cancel(self):
		chemicals.before_cancel(self)

	def on_submit(self):
		chemicals.refresh_duplicates(self.period, self.department, self.item)

	def on_cancel(self):
		chemicals.refresh_duplicates(self.period, self.department, self.item)
