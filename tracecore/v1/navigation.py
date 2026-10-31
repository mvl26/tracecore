"""Read-only navigation. Destination permissions and card authentication remain authoritative."""

import frappe
from frappe import _
from frappe.utils import cint

from tracecore.core import zones

FUNCTION_ROLES = {
	"RECEIVE": {"TC R03"},
	"MANUAL_WASH": {"TC R03"},
	"WASH_LOAD": {"TC R03"},
	"WASH_UNLOAD": {"TC R03", "TC R04"},  # cửa ra máy hai cửa ở khu sạch (FEAT-021 Q20)
	"ASSEMBLE": {"TC R04"},
	"PACK": {"TC R04"},
	"STERI_LOAD": {"TC R05"},
	"STERI_UNLOAD": {"TC R02", "TC R05"},
	"PUTAWAY": {"TC R06"},
	"ISSUE": {"TC R06"},  # cấp phát do KTV kho vô khuẩn (ISSUE_ROLES = STORAGE_ROLES); R07 là đồ vải
	"USE": {"TC R08"},
	"LINEN": {"TC R07"},  # trạm đồ vải (FEAT-033, A-49 L1): thu gom, sau này lô giặt và cấp phát
	"WASTE": {"TC R07"},  # trạm thu gom chất thải (FEAT-047, A-60 W5)
}
# Dashboard vận hành đứng đầu; sau đó nhóm theo thứ tự thiết lập ban đầu: tổ chức và người → khu trạm → máy → dụng cụ → kho và cơ số → chứng từ → dữ liệu
MANAGEMENT_GROUPS = (
	("Overview", ("tc-dashboard",)),  # FEAT-006 SCR-32
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
	(
		"Zones, stations and printing",
		(
			"Zone Station",
			"Zone Type",  # A-64
			"Station Function",
			# FEAT-008: nhật ký môi trường khu và báo cáo tháng
			"Environment Log",
			"report:Environment Monthly Report",
			"Printer",
			"Label Template",
			"Print Job",
		),
	),
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
			"report:Instrument Life Forecast",  # FEAT-007: bộ sắp hết vòng đời kèm giá
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
	# FEAT-047 thu gom chất thải; FEAT-048..050 thêm kho, bàn giao, báo cáo
	(
		"Medical waste",
		(
			"Waste Type",
			"Waste Collection",
			"Waste Container",
			"Waste Storage Location",  # FEAT-048
			"report:Waste Storage Stock",
			"Waste Treatment Vendor",  # FEAT-049
			"Waste Handover",
			"Waste Quota",  # FEAT-050
			"report:Waste Report",
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
	(
		"Quality and traceability",
		(
			"report:Pack Trace",
			"Incident CAPA",
			"Recall Order",
			# FEAT-007: sổ tiệt khuẩn điện tử và báo cáo KSNK (in PDF có chữ ký Trưởng khoa)
			"report:Sterilization Log",
			"report:KSNK Summary Report",
		),
	),
	(
		"Data and audit",
		(
			"tc-import",
			"Archive Export",  # FEAT-012: xuất gói hồ sơ tiệt khuẩn lưu trữ (SCR-43)
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
	"tc-dashboard": "Operations Dashboard",
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
	see_all = admin or bool(roles & {"TC R01", "TC R02", "TC R10"})
	allowed = {function for function, required in FUNCTION_ROLES.items() if see_all or roles & required}
	stations = []
	if allowed:
		rows = frappe.get_list(
			"Zone Station",
			filters={"is_zone": 0, "is_active": 1},
			fields=["name", "zone_station_name", "station_no"],
			limit_page_length=0,
		)
		rows.sort(key=lambda row: (not cint(row.station_no), cint(row.station_no), row.name))
		for row in rows:
			functions = zones.station_functions(row.name)
			# chức năng do R10 tạo không có trong FUNCTION_ROLES: chỉ người quản lý thấy trạm đó
			if set(functions) & allowed or (see_all and functions):
				stations.append(
					{
						"name": row.name,
						"label": row.zone_station_name,
						"station_no": cint(row.station_no),
						"functions": functions,
						"implemented": bool(zones.station_screen_tabs(functions)),
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
