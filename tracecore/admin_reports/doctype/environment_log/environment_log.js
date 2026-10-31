// Nhật ký môi trường khu (FEAT-008, SCR-33): chỉ chọn khu đang bật theo dõi môi trường.
frappe.ui.form.on("Environment Log", {
	setup(frm) {
		frm.set_query("zone", () => ({ filters: { is_zone: 1, env_monitored: 1 } }));
	},
});
