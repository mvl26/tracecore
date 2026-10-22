/* global tracecore */
// Desk: form Item (ERPNext).
// - Nút "Cấp mã cuộn" và "In nhãn cuộn" cho Item nhóm Nhãn (SCR-33, FEAT-005, A-05 R3). Hộp thoại và lời gọi
//   tracecore.v1.codes.issue_rolls / list_rolls nằm ở tc_codes.js (tracecore.codes.issue_rolls_dialog,
//   roll_labels_dialog). Server kiểm Item là nhãn có phương pháp và số lượng. "In nhãn cuộn": in lại mã CN- đã cấp
//   (lần in trước lỗi, nhãn hỏng/mất), tối đa 50 mã mỗi lần.
// - Nút "Đặt hạn lưu" cho Item nhóm Packaging (FEAT-015 Task 8, FR-M2-07.8, BRU-REP-009, S7): hộp thoại dùng chung
//   tracecore.shelf_life.dialog (tc_shelf_life.js) gọi tracecore.v1.set_type_admin.set_pack_shelf_life.

frappe.ui.form.on("Item", {
	refresh(frm) {
		if (frm.is_new() || !(window.tracecore && tracecore.codes)) {
			return;
		}
		if (frm.doc.tc_item_group_cssd === "Label" && tracecore.codes.can_print()) {
			frm.add_custom_button(__("Issue roll codes"), () =>
				tracecore.codes.issue_rolls_dialog(frm)
			);
			frm.add_custom_button(__("Print roll labels"), () =>
				tracecore.codes.roll_labels_dialog(frm)
			);
		}
		if (
			frm.doc.tc_item_group_cssd === "Packaging" &&
			tracecore.shelf_life &&
			tracecore.shelf_life.can_set()
		) {
			frm.add_custom_button(__("Set shelf life"), () =>
				tracecore.shelf_life.dialog({
					item: frm.doc.name,
					current_days: frm.doc.tc_shelf_life_days,
					on_saved: () => frm.reload_doc(),
				})
			);
		}
	},
});
