// Desk: danh sách dòng BOM (FEAT-015 Task 8, S12). Chỉ đọc: dòng chỉ tạo qua "Sửa BOM" trên form loại bộ và không sửa
// được sau khi lưu; nút trên mỗi dòng mở loại bộ để xem/sửa BOM theo phiên bản.

frappe.listview_settings["Set BOM Item"] = {
	add_fields: ["set_type", "bom_version"],
	button: {
		show: (doc) => Boolean(doc.set_type),
		get_label: () => __("Open set type"),
		get_description: (doc) =>
			frappe.utils.escape_html(__("Open set type {0}", [doc.set_type])),
		action: (doc) => frappe.set_route("Form", "Instrument Set Type", doc.set_type),
	},
	onload(listview) {
		listview.page.set_indicator(__("Read only: edit the BOM on the set type"), "gray");
	},
};
