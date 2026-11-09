"""IC Training by Department — "Đào tạo KSNK theo khoa" (FEAT-059; FR-M11-09; UC-42 bước 2, E2, E3; A-135).

Mỗi dòng một khoa: nhân viên đang làm việc, đã đào tạo KSNK cơ bản trong năm, tỷ lệ, trạng thái bằng chữ so với mục
tiêu của danh mục IC Indicator ("Đạt" / "Dưới mục tiêu" / "Không tính" / "Chưa có mục tiêu"), số người chưa học; dòng
cuối là toàn viện. ``status_code`` là mã cố định. Xuất Excel bằng nút chuẩn của Script Report.
"""

import frappe
from frappe import _
from frappe.utils import nowdate

from tracecore.infection_program import training


def _columns():
	return [
		{"fieldname": "department", "label": _("Department"), "fieldtype": "Data", "width": 240},
		{"fieldname": "employees", "label": _("Employees"), "fieldtype": "Int", "width": 110},
		{
			"fieldname": "trained",
			"label": _("Trained", context="IC Training"),
			"fieldtype": "Int",
			"width": 110,
		},
		{"fieldname": "rate", "label": _("Rate (%)"), "fieldtype": "Float", "precision": 1, "width": 100},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 160},
		{"fieldname": "untrained", "label": _("Not Trained Yet"), "fieldtype": "Int", "width": 130},
		{"fieldname": "status_code", "label": _("Status Code"), "fieldtype": "Data", "hidden": 1},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	year = filters.get("year") or nowdate()[:4]
	data = training.basic_rows(year, filters.get("department") or None)
	rows = [
		{
			"department": row["department_name"],
			"employees": row["employees"],
			"trained": row["trained"],
			"rate": row["rate"],
			"status": row["status_label"],
			"untrained": len(row["untrained"]),
			"status_code": row["status"],
		}
		for row in data["departments"]
	]
	if not rows:
		return _columns(), []
	total = data["total"]
	rows.append(
		{
			"department": _("Whole hospital"),
			"employees": total["employees"],
			"trained": total["trained"],
			"rate": total["rate"],
			"status": total["status_label"],
			"untrained": total["employees"] - total["trained"],
			"status_code": total["status"],
		}
	)
	message = None
	if data["untagged_events"]:
		message = _("{0} training events have no IC category and are not counted.").format(
			data["untagged_events"]
		)
	return _columns(), rows, message
