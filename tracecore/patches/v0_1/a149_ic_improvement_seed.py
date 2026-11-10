"""A-149 (FEAT-072): mẫu Nháp tự đánh giá / điều tra cắt ngang và chỉ tiêu QĐ 38 ``QD38-QI`` tự chấm cho site đang chạy.

Mẫu chỉ chèn mã còn thiếu; ``check_method`` của ``QD38-QI`` chỉ điền khi bệnh viện chưa đặt (NFR-MAINT-04).
"""

import frappe

from tracecore.compliance_audit import seed
from tracecore.infection_program import improvement

CRITERION = "IC QD38 Criterion"
CODE = "QD38-QI"


def execute():
	if frappe.db.table_exists("Audit Template"):
		seed.ensure_seed()
	if not frappe.db.table_exists(CRITERION) or not frappe.db.exists(CRITERION, CODE):
		return
	if not frappe.db.get_value(CRITERION, CODE, "check_method"):
		frappe.db.set_value(
			CRITERION, CODE, "check_method", improvement.SELF_CHECK_KEY, update_modified=False
		)
