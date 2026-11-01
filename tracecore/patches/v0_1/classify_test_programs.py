"""Phân loại chương trình test của máy tiệt khuẩn (A-83, #1821, #1839, #1840).

Tên chương trình không đáng tin nên chỉ gán `Test` cho tên hoặc mã có từ rõ ràng; chương trình còn lại giữ `Regular` và
được ghi vào Error Log cùng chương trình thường chưa có loại gói, mẻ test đang chứa gói để R10 rà. Không sửa mẻ, gói hay bảng
loại gói. Chạy lại an toàn.
"""

import re
import unicodedata

import frappe

from tracecore.reprocessing import load_repair

STERILIZERS = ("Steam Sterilizer", "Plasma Sterilizer")
# so khớp sau khi bỏ dấu, nên từ khóa viết không dấu
TEST_NAME = re.compile(r"bowie|\bro ri\b|leak|vacuum|\bchan khong\b", re.IGNORECASE)


def _plain(text):
	decomposed = unicodedata.normalize("NFD", text or "")
	return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def is_test_name(*texts):
	return any(TEST_NAME.search(_plain(text)) for text in texts)


def execute():
	machines = frappe.get_all(
		"Equipment", filters={"equipment_type": ["in", list(STERILIZERS)]}, pluck="name"
	)
	if not machines:
		return
	marked, regular, no_pack_types = [], [], []
	for row in frappe.get_all(
		"Process Program",
		filters={"equipment": ["in", machines]},
		fields=["name", "program_name", "is_active"],
		order_by="name asc",
	):
		label = f"{row.name} ({row.program_name})"
		if is_test_name(row.name, row.program_name):
			frappe.db.set_value("Process Program", row.name, "program_kind", "Test", update_modified=False)
			marked.append(label)
			continue
		regular.append(label)
		if row.is_active and not frappe.db.exists(
			"Program Compatible Pack Type", {"parent": row.name, "parenttype": "Process Program"}
		):
			no_pack_types.append(label)
	loads = load_repair.test_loads_with_packs()
	frappe.log_error(
		title="A-83 classify_test_programs",
		message=frappe.as_json(
			{
				"marked_test": marked,
				"kept_regular_check_by_hand": regular,
				"regular_without_pack_types": no_pack_types,
				"test_loads_with_packs": loads,
			}
		),
	)
