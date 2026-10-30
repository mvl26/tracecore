"""Sự cố thiết bị phía M2 (FEAT-039, FR-M5-04.2): đánh dấu mẻ/lô đang mở trên máy là Cần xem xét.

`flag_open_on` là hàm của hook ``tracecore_equipment_incident`` (M5 gọi khi lưu hồ sơ sự cố; M5 và M2 không import nhau).
Mẻ/lô chỉ đổi bằng cờ của dịch vụ (``tc_sterilizing`` / ``tc_washing``), nên cũng ghi Audit Log Update như mọi lần lưu.
"""

import frappe
from frappe.utils import cint

LOAD = "Sterilization Load"
WASH = "Wash Batch"
# (DocType, trạng thái còn mở chưa dỡ, cờ dịch vụ); mẻ đã Quarantine/Released/Failed và lô đã Passed/Failed không đổi
OPEN = (
	(LOAD, ("Running", "Cycle Complete"), "tc_sterilizing"),
	(WASH, ("Running",), "tc_washing"),
)


def flag_open_on(equipment, record=None):
	"""Đánh dấu ``needs_review = 1`` cho mọi mẻ/lô chưa dỡ trên máy; trả ``[{"load_doctype", "load"}]`` (kể cả đã có cờ)."""
	flagged = []
	for doctype, statuses, service_flag in OPEN:
		names = frappe.get_all(
			doctype,
			filters={"equipment": equipment, "status": ["in", list(statuses)], "docstatus": 0},
			pluck="name",
			order_by="creation asc, name asc",
		)
		for name in names:
			doc = frappe.get_doc(doctype, name, for_update=True)
			if not cint(doc.needs_review):
				doc.needs_review = 1
				doc.flags[service_flag] = True
				# chỉ đổi cờ: link hỏng ở trường khác (nhân viên nghỉ việc…) không được chặn việc ghi sự cố máy
				doc.flags.ignore_links = True
				doc.save(ignore_permissions=True)
			flagged.append({"load_doctype": doctype, "load": name})
	return flagged
