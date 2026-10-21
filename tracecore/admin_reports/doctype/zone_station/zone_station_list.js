/* global tracecore */
// Desk: list view Zone Station — chỉ báo trạng thái luôn có chữ (FEAT-002 Task 5).
frappe.listview_settings["Zone Station"] = {
	add_fields: ["is_zone", "is_active"],
	onload(listview) {
		// thao tác hàng loạt "In nhãn QR" (FEAT-005, tối đa 50 mã, gửi tuần tự)
		tracecore.codes.add_bulk_print(listview, "Station");
	},
	get_indicator(doc) {
		if (doc.is_zone) {
			return [__("Zone"), "blue", "is_zone,=,1"];
		}
		if (doc.is_active) {
			return [__("Active", null, "Zone Station"), "green", "is_zone,=,0|is_active,=,1"];
		}
		return [__("Inactive", null, "Zone Station"), "red", "is_zone,=,0|is_active,=,0"];
	},
};
