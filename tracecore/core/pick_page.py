"""Tiện ích tìm kiếm và phân trang cho danh sách gợi ý chọn tay (A-68), dùng chung M2 và M5."""

from frappe.utils import cint

MAX_PAGE = 50
DEFAULT_PAGE = 20
BACKSLASH = "\\"


def like(text):
	"""Mẫu LIKE chứa `text`: thoát dấu gạch chéo ngược, phần trăm và gạch dưới."""
	escaped = text.replace(BACKSLASH, BACKSLASH * 2)
	escaped = escaped.replace("%", BACKSLASH + "%").replace("_", BACKSLASH + "_")
	return f"%{escaped}%"


def page_of(start, page_length):
	"""``(offset, limit)`` đã chặn: offset >= 0, 1 <= limit <= MAX_PAGE."""
	return max(cint(start), 0), min(max(cint(page_length) or DEFAULT_PAGE, 1), MAX_PAGE)


def join_label(*parts):
	"""Nhãn gợi ý "Mã - Tên - ...": bỏ phần rỗng, ngăn cách bằng gạch ngang dài (en dash) như ticket."""
	return f" {chr(0x2013)} ".join(str(part) for part in parts if part)
