"""Instrument Group: nhóm dụng cụ và ngưỡng bảo dưỡng theo nhóm (A-06 I5; FR-M1-09).

Ngưỡng nhóm áp cho dụng cụ của nhóm không có ngưỡng riêng (``thresholds.effective_rules``). Đổi ngưỡng không đụng
bộ đếm; ``on_update`` cảnh báo các bộ sẽ đến hạn/quá hạn (``thresholds.warn_rule_change``). Không xóa (Audit Log).
"""

from frappe.model.document import Document

from tracecore.instrument import thresholds


class InstrumentGroup(Document):
	def before_naming(self):
		# name = tên nhóm: bỏ khoảng trắng đầu/cuối trước khi đặt tên
		self.group_name = (self.group_name or "").strip()

	def validate(self):
		if self.description is not None:
			self.description = self.description.strip()

	def on_update(self):
		thresholds.warn_rule_change(self)
