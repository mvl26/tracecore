// Desk: danh sách loại bộ (SCR-02, FEAT-015 Task 8). Chỉ báo luôn có chữ: phiên bản BOM đang hiệu lực (server giữ
// current_bom_version) và cờ cấy ghép. Tạo mới mở form; nút lưu của form mới là "Lưu và tạo BOM v1".

frappe.listview_settings["Instrument Set Type"] = {
	add_fields: ["current_bom_version", "is_implant"],
	get_indicator(doc) {
		const version = doc.current_bom_version || 0;
		if (doc.is_implant) {
			return [
				__("Implant set · BOM v{0}", [version]),
				"purple",
				`is_implant,=,1|current_bom_version,=,${version}`,
			];
		}
		return [__("BOM v{0}", [version]), "blue", `current_bom_version,=,${version}`];
	},
};
