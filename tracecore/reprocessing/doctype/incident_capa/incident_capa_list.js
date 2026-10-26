// Danh sách sự cố / NC / CAPA (SCR-15, FEAT-030): trạng thái luôn kèm chữ, màu theo chỉ báo Desk.
frappe.listview_settings["Incident CAPA"] = {
	add_fields: ["status", "severity", "incident_type"],
	get_indicator(doc) {
		const color = {
			New: "red",
			Analysis: "orange",
			CAPA: "orange",
			Verification: "blue",
			Closed: "green",
			Cancelled: "darkgrey",
		}[doc.status];
		return [__(doc.status, null, "Incident CAPA"), color || "gray", `status,=,${doc.status}`];
	},
};
