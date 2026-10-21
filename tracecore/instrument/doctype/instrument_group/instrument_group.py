"""Instrument Group: nhóm dụng cụ (A-06 I5). Task 1 chỉ có tên nhóm; ngưỡng bảo dưỡng theo nhóm thêm ở Task 4."""

from frappe.model.document import Document


class InstrumentGroup(Document):
	def before_naming(self):
		# name = tên nhóm: bỏ khoảng trắng đầu/cuối trước khi đặt tên
		self.group_name = (self.group_name or "").strip()
