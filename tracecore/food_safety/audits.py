"""Kết quả giám sát bếp ăn / đơn vị suất ăn và mẫu thực phẩm (FEAT-073; FR-M17-01, FR-M17-03; UC-56 bước 1, 3, A1).

Phiếu ATTP là `Audit Session` loại "Food Safety" của engine M12 (ADR-015); mẫu thực phẩm là `Environmental Sample`
``sample_type`` = Food của M15. M17 chỉ đọc qua ``frappe.get_all`` (Link), không import M12/M15. Kết quả gắn đơn vị cung
cấp (``supplier``); bếp ăn bệnh viện tự vận hành gắn khoa (UC-56 A1).
"""

import frappe
from frappe.utils import flt

FOOD_AUDIT_TYPE = "Food Safety"
FOOD_SAMPLE_TYPE = "Food"
PASSED, FAILED = "Pass", "Fail"


def unit_results(from_date, to_date):
	"""Mỗi đơn vị (NCC suất ăn hoặc khoa bếp ăn): phiếu gần nhất, số phiếu Đạt / tổng trong khoảng."""
	rows = frappe.get_all(
		"Audit Session",
		filters={
			"docstatus": 1,
			"audit_type": FOOD_AUDIT_TYPE,
			"audit_date": ["between", [from_date, to_date]],
		},
		fields=["name", "supplier", "department", "department_name", "audit_date", "result", "score_pct"],
		order_by="audit_date desc, creation desc",
	)
	suppliers = dict(
		frappe.get_all(
			"Supplier",
			filters={"name": ["in", [row.supplier for row in rows if row.supplier] or [""]]},
			fields=["name", "supplier_name"],
			as_list=True,
		)
	)
	units = {}
	for row in rows:
		key = f"S:{row.supplier}" if row.supplier else f"D:{row.department}"
		unit = units.get(key)
		if not unit:
			unit = units[key] = {
				"unit_key": key,
				"unit": suppliers.get(row.supplier, row.supplier)
				if row.supplier
				else (row.department_name or row.department),
				"is_vendor": bool(row.supplier),
				"last_session": row.name,
				"last_date": row.audit_date,
				"last_result": row.result,
				"last_score": flt(row.score_pct, 1),
				"passed": 0,
				"total": 0,
			}
		unit["total"] += 1
		unit["passed"] += 1 if row.result == PASSED else 0
	return sorted(units.values(), key=lambda unit: unit["unit"] or "")


def recent_samples(limit=10):
	return frappe.get_all(
		"Environmental Sample",
		filters={"docstatus": 1, "sample_type": FOOD_SAMPLE_TYPE},
		fields=[
			"name",
			"environment_zone_name",
			"sampled_on",
			"result_value",
			"unit",
			"limit_applied",
			"result",
			"nc_status",
		],
		order_by="sampled_on desc, creation desc",
		limit=limit,
	)
