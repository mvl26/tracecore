"""IC Program Settings — cài đặt chương trình KSNK (FEAT-056, FR-M11-01 nền; architecture §5.3.1, §8.2)."""

import frappe
from frappe import _
from frappe.model.document import Document

POSITIVE = ("surveillance_ratio_beds", "doc_review_months")
POSITIVE_IF_SET = ("patient_data_retention_months", "exposure_retention_months")


class ICProgramSettings(Document):
	def validate(self):
		if (self.bed_count or 0) < 0:
			frappe.throw(_("Planned beds cannot be negative."))
		for field in POSITIVE:
			if not self.get(field) or self.get(field) <= 0:
				frappe.throw(_("{0} must be greater than 0.").format(_(self.meta.get_label(field))))
		for field in POSITIVE_IF_SET:
			value = self.get(field)
			if value is not None and value != "" and value <= 0:
				frappe.throw(
					_("{0} must be greater than 0, or left empty.").format(_(self.meta.get_label(field)))
				)
