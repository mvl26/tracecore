"""Bỏ nút "Xác nhận tất cả" ở T3 (A-79, #1820): dòng Đủ của bản nháp có thể do nút đó ghi, không phải đếm thật.

Nút cũ không để lại dấu vết nên không phân biệt được: mọi dòng Đủ không có hỏng, ghi chú, ảnh của bản nháp về Chưa đếm.
Dòng lệch định mức và dòng có hỏng là thao tác có chủ ý nên giữ nguyên. Chứng từ đã ghi sổ không đụng tới. Chạy lại an toàn.
"""

import frappe

from tracecore.core import audit


def execute():
	rows = frappe.get_all(
		"Assembly Line",
		filters={"parenttype": "Assembly Record", "counted": 1, "line_status": "Enough", "damaged_qty": 0},
		fields=["name", "parent", "instrument", "note", "photo"],
	)
	drafts = set(
		frappe.get_all(
			"Assembly Record",
			filters={"docstatus": 0, "name": ["in", list({r.parent for r in rows}) or [""]]},
			pluck="name",
		)
	)
	reset = {}
	for row in rows:
		if row.parent not in drafts or (row.note or "").strip() or row.photo:
			continue
		frappe.db.set_value(
			"Assembly Line",
			row.name,
			{"counted": 0, "actual_qty": 0, "line_status": None},
			update_modified=False,
		)
		reset.setdefault(row.parent, []).append(row.instrument)
	for name, instruments in reset.items():
		audit.log(
			"Update",
			"Assembly Record",
			name,
			new={"event": "AssemblyCountsReset", "items": instruments},
			reason="AssemblyCountsReset",
		)
