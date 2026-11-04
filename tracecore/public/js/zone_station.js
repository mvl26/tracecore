/* global tracecore */
// Desk: form Zone Station — nút "In tờ mã lệnh" (A-119, FEAT-083, FR-M9-23): tờ A4 dán tại trạm, mỗi nút/tab/trạm một QR
// để công nhân quét thay cho bấm chuột. Dựng PDF ở máy chủ (tracecore.v1.station.command_sheet), mở hộp thoại In.

frappe.ui.form.on("Zone Station", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.is_zone || !window.tracecore || !tracecore.codes) return;
		if (!frappe.user.has_role("TC R10") && !frappe.user.has_role("System Manager")) return;
		frm.add_custom_button(__("Print command sheet"), async () => {
			const response = await tracecore.codes.post(
				"tracecore.v1.station.command_sheet",
				{ station: frm.doc.name },
				false
			);
			if (!response.ok) {
				tracecore.codes.show_block(response.error);
				return;
			}
			await window.tcPrintPdfAndTell(response.data);
		});
	},
});
