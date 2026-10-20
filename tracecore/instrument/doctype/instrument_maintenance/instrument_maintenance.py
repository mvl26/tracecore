"""Instrument Maintenance: bộ đếm chu trình kể từ lần bảo dưỡng và lịch sử hoãn của một dụng cụ trong một bộ.

Mỗi cặp (Set Unit, Instrument) có đúng một dòng; tên = `{set_unit}-{instrument}` nên trùng cặp bị
DuplicateEntryError (DT-INSTRMAINT, FR-M1-09).
"""

from frappe.model.document import Document


class InstrumentMaintenance(Document):
	pass
