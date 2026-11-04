/* global tracecore */
// Desk: form Batch (lô vật tư/chỉ thị) — nút "In nhãn QR" (FEAT-082, A-118, FR-M6-09): QR chứa tên lô, dán lên hộp
// để quét ở ô lô tại T2, T4, T5b. Server chỉ in lô còn hạn và chưa vô hiệu (tracecore.v1.print.batch_labels_pdf).

frappe.ui.form.on("Batch", {
	refresh(frm) {
		if (frm.is_new() || !window.tracecore || !tracecore.codes) return;
		if (!tracecore.codes.can_print_batch_label()) return;
		frm.add_custom_button(__("Print QR label"), () =>
			tracecore.codes.print_batch_labels([frm.doc.name])
		);
	},
});
