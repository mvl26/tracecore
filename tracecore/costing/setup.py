"""Dữ liệu nền của M7 Chi phí: 12 khoản mục hệ thống (FEAT-044, FR-M7-01.1; architecture A-47 C3).

Tạo NẾU CHƯA CÓ (`after_install` và patch cho site đã cài), không bao giờ ghi đè khoản mục R09 đã chỉnh.
"""

import frappe

# 12 khoản mục cố định theo BRD (FR-M7-01): khấu hao, bảo trì, sửa chữa, phụ tùng, điện, nước máy, nước RO, hơi,
# khí nén, nhân công, đồ bảo hộ, thuê ngoài. Tên gốc tiếng Anh, chọn để không trùng bản dịch sẵn có của ERPNext
# ("Steam", "Maintenance"... đã có nghĩa khác); bản dịch chung ở vi.csv, DocType bật `translated_doctype`.
SYSTEM_CATEGORIES = (
	"Depreciation Cost",
	"Maintenance Cost",
	"Repair Expense",
	"Spare Parts Cost",
	"Electricity Expense",
	"Tap Water Cost",
	"RO Water Cost",
	"Steam Cost",
	"Compressed Air Cost",
	"Labor Cost",
	"Protective Gear Cost",
	"Outsourcing Cost",
)


def ensure_categories() -> list[str]:
	"""Tạo khoản mục hệ thống còn thiếu; trả tên các khoản mục vừa tạo."""
	created = []
	for name in SYSTEM_CATEGORIES:
		if frappe.db.exists("Cost Category", name):
			continue
		doc = frappe.get_doc(
			{"doctype": "Cost Category", "category_name": name, "is_system": 1, "is_active": 1}
		)
		doc.flags.tc_system_category = True
		doc.insert(ignore_permissions=True)
		created.append(name)
	return created
