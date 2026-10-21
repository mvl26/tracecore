/* global tracecore */
// Desk: list view Equipment — chỉ báo trạng thái luôn có chữ (FEAT-038 Task 5).
frappe.listview_settings["Equipment"] = {
	add_fields: ["status"],
	onload(listview) {
		// thao tác hàng loạt "In nhãn QR" (FEAT-005, tối đa 50 mã, gửi tuần tự)
		tracecore.codes.add_bulk_print(listview, "Equipment");
	},
	get_indicator(doc) {
		const map = {
			Ready: [__("Equipment ready"), "green"],
			Locked: [__("Equipment locked"), "orange"],
			Repair: [__("Equipment under repair"), "orange"],
			Retired: [__("Equipment out of service"), "gray"],
		};
		const entry = map[doc.status];
		return entry ? [entry[0], entry[1], `status,=,${doc.status}`] : null;
	},
};
