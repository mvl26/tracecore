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
}
# Bước có màn trên Page station; T5b là chế độ "Dỡ mẻ" của màn T5 nên không có trạm riêng
IMPLEMENTED_STEPS = {"T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"}
# Nhóm theo thứ tự thiết lập ban đầu: tổ chức và người → khu trạm → máy → dụng cụ → kho và cơ số → chứng từ → dữ liệu
MANAGEMENT_GROUPS = (
	("Organization and staff", ("Department", "Employee", "User", "Station Competency")),
	("Zones, stations and printing", ("Zone Station", "Printer", "Label Template", "Print Job")),
	("Equipment", ("Equipment", "Process Program")),
	("Instruments", ("Instrument", "Instrument Set Type", "Set Unit")),
	("Stock and par levels", ("Item", "Batch", "Stock Entry", "Sterile Location", "Par Level")),
	("Processing records", ("Pack", "Wash Batch", "Sterile Putaway")),
	("Data and audit", ("tc-import", "Audit Log")),
)
# Page Desk (không phải DocType) trong menu: quyền theo role của Page
MANAGEMENT_PAGES = {"tc-import": "Catalog Import"}


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
			if target in MANAGEMENT_PAGES:
				if _page_permitted(target):
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


def _page_permitted(page):
	# như Page.is_permitted: Page không gán role thì ai cũng mở được
	if not frappe.db.exists("Page", page):
		return False
	page_roles = frappe.db.get_values("Has Role", {"parent": page, "parenttype": "Page"}, "role", pluck=True)
	return not page_roles or bool(set(page_roles) & set(frappe.get_roles()))
