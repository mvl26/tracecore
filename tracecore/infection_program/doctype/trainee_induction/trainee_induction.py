"""Trainee Induction — sinh viên thực tập phải được đào tạo KSNK trước ngày bắt đầu (FEAT-059; FR-M11-11; A-135 c).

Đào tạo muộn hơn ngày bắt đầu không chặn lưu: hệ thống cảnh báo và đặt ``status`` "Muộn hơn ngày bắt đầu"
(FR-M11-11.1, UC-42 E1). ``status`` do hệ thống tính, người dùng không sửa.
"""

from frappe.model.document import Document

from tracecore.infection_program import training


class TraineeInduction(Document):
	def validate(self):
		training.validate_trainee(self)
