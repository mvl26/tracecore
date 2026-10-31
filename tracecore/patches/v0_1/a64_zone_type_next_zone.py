"""A-64: ``Zone Type`` đổi ô số thứ tự sang vùng kế tiếp và tên màu; site đã chạy bản đầu của A-64 chuyển giá trị cũ."""

import frappe

OLD_COLORS = {
	"web": "Default color",
	"dirty": "Dirty zone",
	"clean": "Clean zone",
	"sterile": "Sterile zone",
	"dept": "Department zone",
	"waste": "Waste zone",
}


def execute():
	for old, new in OLD_COLORS.items():
		frappe.db.set_value("Zone Type", {"zone_color": old}, "zone_color", new, update_modified=False)
	if not frappe.db.has_column("Zone Type", "flow_order"):
		return
	flow = frappe.db.sql(
		"select name from `tabZone Type` where flow_order > 0 order by flow_order asc", pluck=True
	)
	for current, following in zip(flow, flow[1:], strict=False):
		if not frappe.db.get_value("Zone Type", current, "next_zone_type"):
			frappe.db.set_value("Zone Type", current, "next_zone_type", following, update_modified=False)
