"""Điền mặc định danh mục cho Instrument có từ trước FEAT-014 (A-06 I4, I13); chạy lại không đổi gì thêm.

``status`` trống → ``Active``; ``version_no`` trống/0 → 1; ``max_cycles_status`` tính lại từ ``max_cycles``. Ghi
thẳng DB (không qua validate) vì dòng cũ chưa có Spaulding/phương pháp; **không** tự điền hai trường lâm sàng
đó: dụng cụ cũ hiện trong báo cáo Instrument Data Gaps để R02 bổ sung. Mỗi dòng đổi có một Audit Log Update.
"""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import audit

FIELDS = ("status", "version_no", "max_cycles_status")


def execute():
	rows = frappe.get_all("Instrument", fields=["name", "max_cycles", *FIELDS], order_by="name asc")
	for row in rows:
		values = {}
		if not row.status:
			values["status"] = "Active"
		if cint(row.version_no) <= 0:
			values["version_no"] = 1
		expected = "Defined" if cint(row.max_cycles) > 0 else "Undefined"
		if row.max_cycles_status != expected:
			values["max_cycles_status"] = expected
		if not values:
			continue
		frappe.db.set_value("Instrument", row.name, values, update_modified=False)
		audit.log(
			"Update",
			"Instrument",
			row.name,
			old={field: row.get(field) for field in values},
			new=values,
			reason=_("Instrument master defaults filled in by the FEAT-014 data patch"),
		)
