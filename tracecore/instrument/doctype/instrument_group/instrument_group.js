// Desk: form Instrument Group (SCR-01, FEAT-014 Task 6; A-06 I5).
// Ngưỡng nhóm áp cho dụng cụ trong nhóm không có ngưỡng riêng; đổi ngưỡng không đặt lại bộ đếm (server cảnh báo các
// bộ sẽ đến hạn sau khi lưu, thresholds.warn_rule_change).
frappe.ui.form.on("Instrument Group", {
	refresh(frm) {
		frm.set_intro(
			__(
				"Instruments of this group without their own maintenance threshold use this threshold. Changing it never resets cycle counters."
			),
			"blue"
		);
		if (!frm.is_new()) {
			frm.add_custom_button(__("Instruments in this group"), () =>
				frappe.set_route("List", "Instrument", { instrument_group: frm.doc.name })
			);
		}
	},
});
