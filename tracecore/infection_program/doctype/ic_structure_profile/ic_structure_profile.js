// Bộ tiêu chí cơ cấu KSNK (FEAT-094, A-138 a; FR-M11-01.8): R01 duyệt bản Nháp; bản đã duyệt chỉ đọc.
// Lỗi chặn hiện cảnh báo inline đầu form (không hộp thoại).
frappe.ui.form.on("IC Structure Profile", {
	refresh(frm) {
		frm.set_read_only(frm.doc.status !== "Draft" && !frm.is_new());
		if (
			frm.is_new() ||
			frm.doc.status !== "Draft" ||
			!frappe.user.has_role(["TC R01", "System Manager"])
		)
			return;
		frm.add_custom_button(__("Approve"), () => {
			const esc = frappe.utils.escape_html;
			if (frm.is_dirty()) {
				frm.dashboard.set_headline_alert(
					esc(__("Save the record before approving.")),
					"red"
				);
				return;
			}
			frm.call({ method: "approve", doc: frm.doc }).then((r) => {
				const result = (r && r.message) || {};
				if (result.ok === false) {
					const e = result.error || {};
					frm.dashboard.set_headline_alert(
						`<strong>${esc(e.title || "")}</strong> ${esc(e.reason || "")} ${esc(
							e.action || ""
						)}`,
						"red"
					);
					return;
				}
				frm.reload_doc();
			});
		});
	},
});
