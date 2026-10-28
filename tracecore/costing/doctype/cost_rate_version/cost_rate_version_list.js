// Danh sách bảng định giá (SCR-28, FEAT-045): trạng thái luôn có chữ (Nháp / Đã duyệt / Đã hủy).
frappe.listview_settings["Cost Rate Version"] = {
	add_fields: ["docstatus", "effective_from", "effective_to"],
	get_indicator(doc) {
		if (doc.docstatus === 2) {
			return [__("Cancelled", null, "Cost Rate Version"), "darkgrey", "docstatus,=,2"];
		}
		if (doc.docstatus === 1) {
			return [__("Approved", null, "Cost Rate Version"), "green", "docstatus,=,1"];
		}
		return [__("Draft", null, "Cost Rate Version"), "orange", "docstatus,=,0"];
	},
};
