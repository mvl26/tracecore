/* global tracecore */
// Desk: gói (Pack). FEAT-004 (A-37 b, FR-M2-00.3): R02 chuyển trạng thái gói thủ công khi hệ thống lỗi, kèm lý do và
// ticket (tc_admin_actions.js); role chỉ để hiện nút, server (tracecore.reprocessing.manual_transition) kiểm lại.
frappe.ui.form.on("Pack", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frappe.user.has_role("TC R02")) {
			return;
		}
		frm.add_custom_button(
			__("Change status by hand"),
			() => tracecore.admin.force_transition(frm),
			__("Actions")
		);
	},
});
