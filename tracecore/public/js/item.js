/* global tracecore */
// Desk: form Item (ERPNext) — nút "Cấp mã cuộn" cho Item nhóm Nhãn (SCR-33, FEAT-005 Task 5, A-05 R3).
// Gắn qua hook doctype_js; hộp thoại và lời gọi tracecore.v1.codes.issue_rolls nằm ở tc_codes.js
// (tracecore.codes.issue_rolls_dialog). Server kiểm Item là nhãn có phương pháp và số lượng cho phép.

frappe.ui.form.on("Item", {
	refresh(frm) {
		if (
			!frm.is_new() &&
			frm.doc.tc_item_group_cssd === "Label" &&
			window.tracecore &&
			tracecore.codes &&
			tracecore.codes.can_print()
		) {
			frm.add_custom_button(__("Issue roll codes"), () =>
				tracecore.codes.issue_rolls_dialog(frm)
			);
		}
	},
});
