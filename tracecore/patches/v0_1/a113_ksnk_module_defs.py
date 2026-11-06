"""A-113 (FEAT-056): đăng ký 7 Module Def KSNK toàn viện cho site đang chạy.

`bench migrate` không tự tạo Module Def mới trong ``modules.txt`` (chỉ ``install-app`` làm); patch chạy trước khi đồng bộ
DocType để DocType của M11-M17 có module. Idempotent: module đã có thì bỏ qua.
"""

import frappe

MODULES = (
	"Infection Program",
	"Compliance Audit",
	"HAI Surveillance",
	"Microbiology",
	"Environmental Hygiene",
	"Occupational Safety",
	"Food Safety",
)


def execute():
	for module in MODULES:
		if frappe.db.exists("Module Def", module):
			continue
		frappe.get_doc({"doctype": "Module Def", "module_name": module, "app_name": "tracecore"}).insert(
			ignore_permissions=True
		)
