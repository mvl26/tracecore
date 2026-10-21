"""Label Template: mẫu nhãn Jinja theo (đối tượng nhãn, phương pháp, ngôn ngữ máy in); R10 chỉnh không cần code.

Mỗi bộ ba (`label_object`, `method`, `language`) chỉ có đúng một mẫu active. `method` chỉ có nghĩa (và bắt buộc)
với nhãn gói; nhãn QR đối tượng (FEAT-005) không có phương pháp. Mẫu mẫu tạo ở
`tracecore.setup.label_templates.ensure_sample_templates` / `ensure_object_templates`.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from tracecore.core import print as core_print
from tracecore.setup.label_templates import sample_context

# Lượt thử thứ ba giữ khóa này (payload cho DataMatrix) và để trống mọi khóa khác, như khi dữ liệu thiếu.
REQUIRED_SAMPLE_KEYS = ("payload",)


class LabelTemplate(Document):
	def validate(self):
		core_print.get_dialect(self.language)
		self._validate_method()
		if flt(self.width_mm) <= 0 or flt(self.height_mm) <= 0 or cint(self.dpi) <= 0:
			frappe.throw(_("Label width, height and DPI must be greater than zero."))
		core_print.check_template_syntax(self.body)
		self._validate_renders()
		if self.is_active:
			self._validate_single_active()

	def _validate_method(self):
		if self.label_object != "Pack":
			self.method = None  # phương pháp tiệt khuẩn không áp dụng cho nhãn đối tượng
		elif not self.method:
			frappe.throw(_("Sterilization Method is required for pack labels."))

	def _validate_renders(self):
		"""Mẫu phải dựng được nhãn, nếu không mỗi lần in và mỗi lần đổi cuộn của phương pháp này đều lỗi.

		Dựng thử bằng dữ liệu mẫu của loại đối tượng (gói: GTIN test; đối tượng: mã mẫu) theo kích thước, dpi, ngôn
		ngữ của chính mẫu, ở cả hai chế độ Unicode, và một lượt với mọi giá trị trừ payload để trống (phép toán trên
		giá trị thiếu cũng lỗi khi in thật).
		"""
		sample = sample_context(self.label_object)
		blank = {key: (value if key in REQUIRED_SAMPLE_KEYS else None) for key, value in sample.items()}
		for doc, unicode in ((sample, False), (sample, True), (blank, False)):
			core_print.render(
				self.body,
				doc,
				unicode,
				dpi=self.dpi,
				width_mm=self.width_mm,
				height_mm=self.height_mm,
				language=self.language,
				name=self.name or self.template_name,
			)

	def _validate_single_active(self):
		other = frappe.db.get_value(
			"Label Template",
			{
				"label_object": self.label_object,
				"method": core_print.method_filter(self.method),
				"language": self.language,
				"is_active": 1,
				"name": ["!=", self.name],
			},
			"name",
		)
		if other and self.label_object != "Pack":
			frappe.throw(
				_("Template {2} is already active for {0} / {1}. Deactivate it first.").format(
					_(self.label_object), self.language, other
				)
			)
		if other:
			frappe.throw(
				_("Template {3} is already active for {0} / {1} / {2}. Deactivate it first.").format(
					_(self.label_object), _(self.method), self.language, other
				)
			)
