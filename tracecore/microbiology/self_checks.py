"""Dòng tự động của tự đánh giá QĐ 38 thuộc M14 (FEAT-065; FR-M9-29; hook ``tracecore_ic_self_checks``; A-145 D8).

``amr_surveillance``: có chủng phân lập nhập trong năm (WHONET/CSV, FR-M14-01) → Cần R01 xác nhận đã gửi số liệu giám
sát kháng thuốc quốc gia; không có → Chưa đạt. Chỉ đếm.
"""

import frappe
from frappe import _
from frappe.utils import cint

DOCTYPE = "Microbiology Isolate"


def amr_surveillance(year):
	year = cint(year)
	count = frappe.db.count(
		DOCTYPE, {"collected_on": ("between", [f"{year:04d}-01-01", f"{year:04d}-12-31"])}
	)
	ref = _("{0} isolates imported").format(count)
	return {"status": "Needs confirmation" if count else "Not met", "source_ref": ref}


def register():
	return {"amr_surveillance": amr_surveillance}
