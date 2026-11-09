// Trainee Induction (FEAT-059; FR-M11-11): trạng thái do server tính; đào tạo muộn chỉ cảnh báo, vẫn lưu.
frappe.ui.form.on("Trainee Induction", {
	refresh(frm) {
		if (frm.doc.status === "Trained After Start") {
			frm.dashboard.set_headline_alert(
				__(
					"Infection control training is later than the internship start date. Move the training date or the start date."
				),
				"orange"
			);
		}
	},
});
