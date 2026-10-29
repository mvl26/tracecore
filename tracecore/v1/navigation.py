"""Read-only navigation. Destination permissions and card authentication remain authoritative."""

import frappe
from frappe import _

STEP_ROLES = {
	"T1": {"TC R03"},
	"T2": {"TC R03"},
	"T3": {"TC R04"},
	"T4": {"TC R04"},
	"T5": {"TC R05"},
	"T5b": {"TC R02", "TC R05"},
	"T6": {"TC R06"},
	"T7": {"TC R06"},  # cấp phát do KTV kho vô khuẩn (ISSUE_ROLES = STORAGE_ROLES); R07 là đồ vải
	"T8": {"TC R08"},
	"LIN": {"TC R07"},  # trạm đồ vải (FEAT-033, A-49 L1): thu gom, sau này lô giặt và cấp phát
}
# Bước có màn trên Page station; T5b là chế độ "Dỡ mẻ" của màn T5 nên không có trạm riêng
IMPLEMENTED_STEPS = {"T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "LIN"}
# Nhóm theo thứ tự thiết lập ban đầu: tổ chức và người → khu trạm → máy → dụng cụ → kho và cơ số → chứng từ → dữ liệu
MANAGEMENT_GROUPS = (
	(
		"Organization and staff",
		(
			"Department",
			"Employee",
			"Certificate",
			"competency-matrix",
			"Station Competency",
			"User",
			"Shift Assignment",
			"report:Shift Schedule",
			"report:Station Output",
		),
	),
	("Zones, stations and printing", ("Zone Station", "Printer", "Label Template", "Print Job")),
	(
		"Equipment",
		("Equipment", "Process Program", "Equipment Type Norm", "Daily Test", "Maintenance Record"),
	),
	(
		"Instruments",
		(
			"Instrument",
			"Instrument Group",
			"Instrument Set Type",
			"Set Unit",
			"Loaner Set",
			"Instrument Maintenance",
			"report:Instrument Data Gaps",
		),
	),
	(
		"Stock and par levels",
		(
			"Item",
			"Batch",
			"Stock Entry",
			"Stock Reconciliation",  # FEAT-043: kiểm kê
			"Material Request",
			"Sterile Location",
			"Par Level",
			"Par Override",
			"report:Par Override Report",
			"report:Stock Alerts",
		),
	),
	(
		"Costs",
		(
			"Cost Entry",
			"Cost Rate Version",
			"Cost Category",
			"Cost Settings",
			"report:Cost by Target",
			# FEAT-046 SCR-29: giá thành mẻ và bộ
			"Cost Sheet",
			"report:Set Cost Report",
		),
	),
	# FEAT-033 thu gom; FEAT-034 lô giặt và báo cáo chi phí/kg; FEAT-035 thêm cấp phát
	(
		"Linen",
		(
			"Linen Type",
			"Linen Collection",
			"Laundry Batch",
			"report:Laundry Cost per Kg",
			"Linen Issue",
			"report:Linen Reconciliation",
		),
	),
	(
		"Processing records",
		(
			"Dirty Receipt",
			"Wash Batch",
			"Assembly Record",
			"Pack",
			"Sterilization Load",
			"Sterile Putaway",
			"Issue Note",
			"Usage Record",
		),
	),
	("Quality and traceability", ("report:Pack Trace", "Incident CAPA", "Recall Order")),
	(
		"Data and audit",
		(
			"tc-import",
			"notifications",
			"Notification Rule",
			"Audit Log",
			"report:Audit Trail",
			"Sync Conflict",
			"Code Range",
			"TraceCore Settings",
		),
	),
)
# Page Desk (không phải DocType) trong menu: quyền theo role của Page
MANAGEMENT_PAGES = {
	"tc-import": "Catalog Import",
	"notifications": "Notification Center",
	"competency-matrix": "Competency Matrix",
}
# Báo cáo (Script Report) trong menu, khóa ``report:<tên>``: quyền theo role của Report
REPORT_PREFIX = "report:"


@frappe.whitelist(methods=["GET"])
def context():
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to open TraceCore."), frappe.PermissionError)
	roles = set(frappe.get_roles())
	admin = frappe.session.user == "Administrator" or "System Manager" in roles
	manager = admin or bool(roles & {"TC R01", "TC R02", "TC R09", "TC R10"})
	allowed = (
		set(STEP_ROLES)
		if admin or roles & {"TC R01", "TC R02", "TC R10"}
		else {step for step, required in STEP_ROLES.items() if roles & required}
	)
	stations = []
	if allowed:
		for row in frappe.get_list(
			"Zone Station",
			filters={"is_zone": 0, "is_active": 1},
			fields=["name", "zone_station_name", "station_step"],
			order_by="station_step asc, name asc",
			limit_page_length=0,
		):
			if row.station_step in allowed:
				stations.append(
					{
						"name": row.name,
						"label": row.zone_station_name,
						"step": row.station_step,
						"implemented": row.station_step in IMPLEMENTED_STEPS,
					}
				)
	return {
		"stations": stations,
		"management": _management_links() if manager else [],
		"department": admin or "TC R08" in roles,
	}


def _management_links():
	"""Link quản lý theo nhóm; `label` là chuỗi gốc tiếng Anh, client dịch bằng ``__()``."""
	links = []
	for group, targets in MANAGEMENT_GROUPS:
		for target in targets:
			if target.startswith(REPORT_PREFIX):
				report = target[len(REPORT_PREFIX) :]
				if _roles_permit("Report", report):
					links.append(
						{
							"group": group,
							"label": report,
							"doctype": None,
							"route": "/app/query-report/" + report,
						}
					)
			elif target in MANAGEMENT_PAGES:
				if _roles_permit("Page", target):
					links.append(
						{
							"group": group,
							"label": MANAGEMENT_PAGES[target],
							"doctype": None,
							"route": "/app/" + target,
						}
					)
			elif frappe.has_permission(target, ptype="read"):
				links.append(
					{
						"group": group,
						"label": target,
						"doctype": target,
						"route": "/app/" + frappe.scrub(target).replace("_", "-"),
					}
				)
	return links


def _roles_permit(doctype, name):
	# như Page/Report.is_permitted: không gán role thì ai cũng mở được
	if not frappe.db.exists(doctype, name):
		return False
	roles = frappe.db.get_values("Has Role", {"parent": name, "parenttype": doctype}, "role", pluck=True)
	return not roles or bool(set(roles) & set(frappe.get_roles()))
