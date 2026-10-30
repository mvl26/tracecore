// Danh sách hồ sơ bảo trì / kiểm định / hiệu chuẩn / sự cố thiết bị (SCR-22, FEAT-039): trạng thái luôn kèm chữ, màu theo chỉ báo Desk.
frappe.listview_settings["Maintenance Record"] = {
	add_fields: ["docstatus", "abandoned", "record_type", "planned_date"],
	get_indicator(doc) {
		let state = [__("Planned"), "orange"];
		if (doc.docstatus === 2) {
			state = [__("Cancelled"), "darkgrey"];
		} else if (doc.docstatus === 1) {
			state = [__("Closed"), "green"];
		} else if (doc.abandoned) {
			state = [__("Abandoned"), "gray"];
		} else if (doc.record_type === "Incident") {
			state = [__("Incident open"), "red"];
		} else if (doc.planned_date && doc.planned_date < frappe.datetime.get_today()) {
			state = [__("Overdue"), "red"];
		}
		return [state[0], state[1], `docstatus,=,${doc.docstatus}`];
	},
};
