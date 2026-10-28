// Desk: danh sách Certificate (FEAT-036, SCR-19): trạng thái bằng chữ + màu, sắp theo hạn gần nhất.
frappe.listview_settings["Certificate"] = {
	add_fields: ["status", "expires_on", "no_expiry"],
	get_indicator(doc) {
		const color = { Valid: "green", Expired: "red", Superseded: "gray" }[doc.status] || "gray";
		return [__(doc.status, null, "Certificate"), color, `status,=,${doc.status}`];
	},
};
