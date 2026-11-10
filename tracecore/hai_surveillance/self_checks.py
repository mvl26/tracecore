"""Dòng tự động của tự đánh giá QĐ 38 thuộc M13 (FEAT-065; FR-M9-29; hook ``tracecore_ic_self_checks``; A-145 D8).

``hai_surveillance_active``: có mẫu số ngày và đợt thiết bị trong năm → Cần R01 xác nhận (dữ liệu giám sát có, R01 xác
nhận đã báo cáo NKVM/NK hồi sức); không có → Chưa đạt. Chỉ đếm, không đọc mã người bệnh.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.hai_surveillance import census, episodes


def surveillance_active(year):
	year = cint(year)
	span = ("between", [f"{year:04d}-01-01", f"{year:04d}-12-31"])
	days = frappe.db.count(census.DOCTYPE, {"census_date": span})
	device = frappe.db.count(episodes.DOCTYPE, {"inserted_on": span})
	ref = _("{0} census days, {1} device episodes").format(days, device)
	if days and device:
		return {"status": "Needs confirmation", "source_ref": ref}
	return {"status": "Not met", "source_ref": ref}


def register():
	return {"hai_surveillance_active": surveillance_active}
