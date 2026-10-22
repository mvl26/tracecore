"""Một dòng lịch sử thay đổi của Par Level (người, thời điểm, giá trị cũ/mới); append-only, do ``par.config`` ghi."""

from frappe.model.document import Document


class ParLevelHistory(Document):
	pass
