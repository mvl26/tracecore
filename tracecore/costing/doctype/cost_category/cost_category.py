"""Cost Category: danh mục khoản mục chi phí (FEAT-044, FR-M7-01.1; architecture §5.3 DT-COSTCAT, A-47 C3).

12 khoản mục hệ thống do `costing.setup.ensure_categories` tạo; R09 thêm loại mới. Không loại nào bị xóa (Audit Log, hook `block_delete` trong hooks.py): khoản mục không dùng nữa thì tắt `is_active`;
loại hệ thống còn không đổi tên được.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class CostCategory(Document):
	def validate(self):
		# cờ hệ thống chỉ do app đặt (ensure_categories); người dùng không tự đánh dấu hay bỏ đánh dấu được
		if not self.flags.tc_system_category:
			self.is_system = (
				0 if self.is_new() else cint(frappe.db.get_value("Cost Category", self.name, "is_system"))
			)

	def before_rename(self, old, new, merge=False):
		if self.is_system and old != new:
			frappe.throw(_("System cost category {0} cannot be renamed.").format(old))
