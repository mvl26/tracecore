"""RPC tracecore.v1.exports.* — xuất báo cáo theo hồ sơ ánh xạ cột `Report Export Profile` (FEAT-064; FR-M13-12, 12.1;
BRU-RPT-002; A-147 Q1, j).

- ``kinds`` (GET): loại xuất người gọi được dùng + hồ sơ của từng loại.
- ``download`` (GET): file Excel/CSV; quyền theo ``ExportKind.roles``; file chỉ có mã người bệnh che.
"""

import frappe

from tracecore.core import exporter
from tracecore.v1._common import require_any_role

EXPORT_ROLES = ("TC R01", "TC R11", "System Manager")


@frappe.whitelist(methods=["GET"])
def kinds():
	require_any_role(*EXPORT_ROLES)
	roles = set(frappe.get_roles())
	return {
		"ok": True,
		"kinds": [
			{"key": kind.key, "label": frappe._(kind.label), "profiles": exporter.profiles(kind.key)}
			for kind in exporter.kinds().values()
			if roles & set(kind.roles) or frappe.session.user == "Administrator"
		],
	}


@frappe.whitelist(methods=["GET"])
def download(kind, period_from=None, period_to=None, profile=None, department=None):
	require_any_role(*EXPORT_ROLES)
	filters = {"period_from": period_from, "period_to": period_to, "department": department}
	name, content, _type = exporter.build(kind, {k: v for k, v in filters.items() if v}, profile or None)
	frappe.response["type"] = "binary"
	frappe.response["filename"] = name
	frappe.response["filecontent"] = content
