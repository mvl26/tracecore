// Danh sách ghi đè cơ số (SCR-31, FEAT-032): trạng thái luôn kèm chữ, màu theo chỉ báo Desk.
frappe.listview_settings["Par Override"] = {
	add_fields: ["status", "extra_cycles", "valid_until"],
	get_indicator(doc) {
		const color = {
			Requested: "orange",
			Approved: "green",
			Rejected: "red",
			Expired: "gray",
			Cancelled: "darkgrey",
		}[doc.status];
		return [__(doc.status, null, "Par Override"), color || "gray", `status,=,${doc.status}`];
	},
};
