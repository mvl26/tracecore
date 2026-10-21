/* global tracecore */
// Desk: form Item (ERPNext) — nút "Cấp mã cuộn" và "In nhãn cuộn" cho Item nhóm Nhãn (SCR-33, FEAT-005, A-05 R3).
// Gắn qua hook doctype_js; hộp thoại và lời gọi tracecore.v1.codes.issue_rolls / list_rolls nằm ở tc_codes.js
// (tracecore.codes.issue_rolls_dialog, roll_labels_dialog). Server kiểm Item là nhãn có phương pháp và số lượng.
// "In nhãn cuộn": in lại mã CN- đã cấp (lần in trước lỗi, nhãn hỏng/mất), tối đa 50 mã mỗi lần.

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
			frm.add_custom_button(__("Print roll labels"), () =>
				tracecore.codes.roll_labels_dialog(frm)
			);
		}
	},
});
