// Danh sách khoản chi phí (SCR-27, FEAT-044): trạng thái luôn kèm chữ, màu theo chỉ báo Desk.
frappe.listview_settings["Cost Entry"] = {
	add_fields: ["docstatus", "amount", "period_from", "period_to"],
	get_indicator(doc) {
		let state = [__("Draft", null, "Cost Entry"), "orange"];
		if (doc.docstatus === 2) {
			state = [__("Cancelled", null, "Cost Entry"), "darkgrey"];
		} else if (doc.docstatus === 1) {
			state = [__("Submitted", null, "Cost Entry"), "green"];
		}
		return [state[0], state[1], `docstatus,=,${doc.docstatus}`];
	},
};
