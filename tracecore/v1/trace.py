"""RPC tracecore.v1.trace.query — truy xuất hai chiều (FEAT-028, UC-14, SCR-14, API-M2-14, FR-M2-19).

Chỉ đọc. Quyền và giới hạn khoa do ``reprocessing.trace`` kiểm; mã bệnh nhân chỉ trả ở dạng che.
"""

import frappe

from tracecore.reprocessing import trace


@frappe.whitelist(methods=["GET"])
def query(
	patient_code=None,
	set_id=None,
	cycle_id=None,
	load=None,
	equipment=None,
	user=None,
	from_date=None,
	to_date=None,
):
	"""Chuỗi sự kiện T1→T8 theo tiêu chí; trả ``{"chains": [...], "suggestion"}``."""
	return trace.query(
		patient_code=patient_code,
		set_id=set_id,
		cycle_id=cycle_id,
		load=load,
		equipment=equipment,
		user=user,
		from_date=from_date,
		to_date=to_date,
	)
