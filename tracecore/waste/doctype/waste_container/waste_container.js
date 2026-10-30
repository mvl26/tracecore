// Desk: túi/thùng chất thải (FEAT-047, FR-M10-02.4, A-60 W12). Túi bị giữ vì phân loại sai: R02 xác nhận đã phân loại lại;
// quy tắc nằm ở server (tracecore.v1.waste.release_held), lỗi chặn hiện kết quả → lý do → hành động trong hộp thoại.

const TC_WASTE_RELEASE = "tracecore.v1.waste.release_held";
const TC_WASTE_RELEASE_ROLES = ["TC R02", "System Manager"];

frappe.ui.form.on("Waste Container", {
	refresh(frm) {
		if (frm.doc.status !== "Held") return;
		if (!TC_WASTE_RELEASE_ROLES.some((role) => frappe.user.has_role(role))) return;
		frm.add_custom_button(__("Confirm sorted again"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Confirm sorted again"),
				fields: [
					{ fieldname: "error", fieldtype: "HTML" },
					{ fieldname: "note", fieldtype: "Small Text", label: __("Note"), reqd: 1 },
				],
				primary_action_label: __("Confirm"),
				primary_action: async ({ note }) => {
					const { message } = await frappe.call({
						method: TC_WASTE_RELEASE,
						args: { container: frm.doc.name, note },
						type: "POST",
					});
					if (message && message.ok) {
						dialog.hide();
						return frm.reload_doc();
					}
					const error = (message && message.error) || {};
					dialog.fields_dict.error.$wrapper.html(
						["title", "reason", "action"]
							.map((key) => `<p>${frappe.utils.escape_html(error[key] || "")}</p>`)
							.join("")
					);
				},
			});
			dialog.show();
		});
	},
});
