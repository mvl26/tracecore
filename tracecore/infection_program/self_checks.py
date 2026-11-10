"""Dòng tự động của tự đánh giá QĐ 38 thuộc M11 (FEAT-065; FR-M9-29; hook ``tracecore_ic_self_checks``; A-145 D8).

``ic_plan_approved``: năm có kế hoạch KSNK đã ghi sổ (R13 duyệt, FR-M11-04) → Đạt, tham chiếu số kế hoạch.
"""

import frappe
from frappe.utils import cint


def plan_approved(year):
	name = frappe.db.get_value("IC Annual Plan", {"year": cint(year), "docstatus": 1}, "name")
	return {"status": "Met", "source_ref": name} if name else {"status": "Not met", "source_ref": ""}


def register():
	return {"ic_plan_approved": plan_approved}
