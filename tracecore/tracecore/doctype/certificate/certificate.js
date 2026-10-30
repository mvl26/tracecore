// Desk: form Certificate (FEAT-036, FR-M4-02.3): nút "Gia hạn" tạo bản ghi mới trỏ về bản cũ; bản cũ thành Đã thay thế.
// Quy tắc nằm ở server (tracecore.hr.certificates); script chỉ điền sẵn và hiện trạng thái bằng chữ.

const TC_CERT_COLOR = { Valid: "green", Expired: "red", Superseded: "gray" };

frappe.ui.form.on("Certificate", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.page.set_indicator(
			__(frm.doc.status, null, "Certificate"),
			TC_CERT_COLOR[frm.doc.status] || "gray"
		);
		if (frm.doc.status === "Superseded") {
			frm.set_intro(__("This certificate was renewed; it is kept as history."), "grey");
			return;
		}
		if (frappe.model.can_create("Certificate"))
			frm.add_custom_button(__("Renew"), () =>
				frappe.new_doc("Certificate", {
					employee: frm.doc.employee,
					certificate_type: frm.doc.certificate_type,
					issuer: frm.doc.issuer,
					renews: frm.doc.name,
				})
			);
	},
});
