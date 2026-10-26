// Danh sách lệnh thu hồi (SCR-14, FEAT-029): trạng thái luôn kèm chữ, màu theo chỉ báo Desk.
frappe.listview_settings["Recall Order"] = {
	add_fields: ["status", "pack_count", "confirmed_count"],
	get_indicator(doc) {
		const color = { Open: "red", Closed: "green" }[doc.status];
		return [__(doc.status, null, "Recall Order"), color || "gray", `status,=,${doc.status}`];
	},
};
