/* global tracecore */
// Mẫu theo dõi sau phơi nhiễm (FEAT-071, A-137 Q3; BRU-OCC-004): R01 duyệt phiên bản Nháp; bản đã duyệt không sửa được.
// Lỗi chặn hiện cảnh báo inline đầu form (không msgprint).
frappe.ui.form.on("Exposure Follow-up Template", {
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
			tracecore.desk_call({
				method: "tracecore.v1.exposure.approve_template",
				args: { name: frm.doc.name },
				on_ok: () => frm.reload_doc(),
				on_block: (error) =>
					frm.dashboard.set_headline_alert(
						`<strong>${esc(error.title || "")}</strong> ${esc(
							error.reason || ""
						)} ${esc(error.action || "")}`,
						"red"
					),
			});
		});
	},
});
