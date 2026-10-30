// Desk: form Station Competency — chứng chỉ bắt buộc chỉ chọn trong các loại đã dùng, như ma trận năng lực (A-58).

frappe.ui.form.on("Station Competency", {
	setup(frm) {
		frm.set_query("certificate_type", "required_certificates", () => ({
			query: "tracecore.v1.staff.certificate_types",
		}));
	},
});
