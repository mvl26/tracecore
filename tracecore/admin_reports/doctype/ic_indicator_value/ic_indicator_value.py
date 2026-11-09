"""IC Indicator Value — giá trị chỉ số KSNK do hệ thống ghi khi khóa kỳ (FEAT-056, FR-M9-27; architecture §5.3.1, §8.5).

Chỉ `admin_reports.indicator` ghi; không ai tạo/sửa tay (ma trận quyền không có W). Mỗi (chỉ số, kỳ, khoa) một dòng.
"""

from frappe.model.document import Document


class ICIndicatorValue(Document):
	pass
