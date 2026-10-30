"""RPC tracecore.v1.staff.* — chứng chỉ của nhân viên cho form Employee trên Desk (FEAT-036, SCR-19, API-M4-01).

Chỉ đọc; quyền theo quyền đọc DocType `Certificate` (R01, R02, R10, System Manager). Quy tắc ở `tracecore.hr`.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, today

from tracecore.hr import reminders

EXPIRING_WITHIN_DAYS = max(reminders.THRESHOLDS)
FIELDS = [
	"name",
	"certificate_type",
	"certificate_no",
	"issuer",
	"issued_on",
	"expires_on",
	"no_expiry",
	"status",
	"renews",
	"scan",
]


@frappe.whitelist(methods=["GET"])
def certificates(employee):
	"""Chứng chỉ của `employee`, mới cấp trước. Trả ``{"ok", "rows", "counts"}``; mỗi dòng có ``days_left`` (rỗng khi
	không hết hạn) và ``expiring`` (còn hiệu lực nhưng hết hạn trong 60 ngày). ``counts`` không tính bản đã gia hạn."""
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("Employee {0} does not exist.").format(employee), frappe.DoesNotExistError)
	if not frappe.has_permission("Certificate", "read"):
		frappe.throw(_("Not permitted to read certificates."), frappe.PermissionError)
	rows = frappe.get_all(
		"Certificate", filters={"employee": employee}, fields=FIELDS, order_by="issued_on desc, creation desc"
	)
	counts = {"valid": 0, "expiring": 0, "expired": 0}
	for row in rows:
		row["days_left"] = None if row.no_expiry or not row.expires_on else date_diff(row.expires_on, today())
		row["expiring"] = int(
			row.status == "Valid"
			and row["days_left"] is not None
			and row["days_left"] <= EXPIRING_WITHIN_DAYS
		)
		if row.status == "Valid":
			counts["valid"] += 1
			counts["expiring"] += row["expiring"]
		elif row.status == "Expired":
			counts["expired"] += 1
	return {"ok": True, "rows": rows, "counts": counts}
