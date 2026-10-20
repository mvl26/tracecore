"""Label Template: mẫu nhãn Jinja theo (đối tượng nhãn, phương pháp, ngôn ngữ máy in); R10 chỉnh không cần code.

Mỗi bộ ba (`label_object`, `method`, `language`) chỉ có đúng một mẫu active. Mẫu mẫu tạo ở
`tracecore.setup.label_templates.ensure_sample_templates`.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from tracecore.core import print as core_print


class LabelTemplate(Document):
	def validate(self):
		core_print.get_dialect(self.language)
		if flt(self.width_mm) <= 0 or flt(self.height_mm) <= 0 or cint(self.dpi) <= 0:
			frappe.throw(_("Label width, height and DPI must be greater than zero."))
		core_print.check_template_syntax(self.body)
		if self.is_active:
			self._validate_single_active()

	def _validate_single_active(self):
		other = frappe.db.get_value(
			"Label Template",
			{
				"label_object": self.label_object,
				"method": self.method,
				"language": self.language,
				"is_active": 1,
				"name": ["!=", self.name],
			},
			"name",
		)
		if other:
			frappe.throw(
				_("Template {3} is already active for {0} / {1} / {2}. Deactivate it first.").format(
					_(self.label_object), _(self.method), self.language, other
				)
			)
