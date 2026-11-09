"""IC Indicator — danh mục chỉ số KSNK (FEAT-056, FR-M9-27, FR-M11-04; architecture §5.3.1).

Nội dung chuyên môn do R01 duyệt (D10); hàm tính do module đăng ký qua hook ``tracecore_ic_indicators``
(``core.indicators``). Chỉ số đang dùng phải trỏ tới một hàm đã đăng ký.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import indicators


class ICIndicator(Document):
	def validate(self):
		if (self.min_sample or 0) < 0:
			frappe.throw(_("Minimum sample cannot be negative."))
		# mục tiêu 0 hợp lệ khi đã chọn chiều (vd 0 ổ dịch); mục tiêu khác 0 mà thiếu chiều thì không chấm Đạt được
		if self.national_target and not self.target_direction:
			frappe.throw(_("Choose whether higher or lower values meet the target."))
		if self.is_active:
			self._validate_method()

	def _validate_method(self):
		if not self.source_method:
			frappe.throw(_("Choose a calculation method before activating indicator {0}.").format(self.code))
		if self.source_method not in indicators.registry():
			frappe.throw(
				_("Calculation method {0} is not registered by any module.").format(self.source_method)
			)
