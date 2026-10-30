/* global tracecore */
// Desk: nút "Lập lệnh thu hồi" trên mẻ tiệt khuẩn (SCR-14, FEAT-029; UC-14 bước 3, FR-M2-20).
// Chỉ R01/R02 thấy nút; server tự gom mọi gói bị ảnh hưởng của mẻ, không nhập tay. Lỗi chặn hiện inline trong hộp thoại.

const TC_LOAD_RECALLERS = ["TC R01", "TC R02"];

function tc_load_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_load_error_html(error) {
	const lines = [
		`<b>✕ ${tc_load_escape(error.title)}</b>`,
		tc_load_escape(error.reason),
		tc_load_escape(error.action),
	];
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

function tc_load_open_recall(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Open recall order"),
		fields: [
			{ fieldname: "error_html", fieldtype: "HTML" },
			{
				fieldname: "reason",
				label: __("Reason for Recall"),
				fieldtype: "Small Text",
				reqd: 1,
			},
		],
		primary_action_label: __("Open recall order"),
		primary_action(values) {
			dialog.get_primary_btn().prop("disabled", true);
			tracecore.desk_call({
				method: "tracecore.v1.recall.create",
				args: { load: frm.doc.name, reason: values.reason },
				on_ok: (result) => {
					dialog.get_primary_btn().prop("disabled", false);
					dialog.hide();
					frappe.set_route("Form", "Recall Order", result.recall.name);
				},
				on_block: (error) => {
					dialog.get_primary_btn().prop("disabled", false);
					dialog.fields_dict.error_html.$wrapper.html(tc_load_error_html(error));
				},
				on_fail: () => dialog.get_primary_btn().prop("disabled", false),
			});
		},
	});
	dialog.show();
}

frappe.ui.form.on("Sterilization Load", {
	refresh(frm) {
		const allowed =
			frappe.session.user === "Administrator" ||
			TC_LOAD_RECALLERS.some((role) => frappe.user.has_role(role));
		if (!frm.is_new() && allowed) {
			frm.add_custom_button(__("Open recall order"), () => tc_load_open_recall(frm));
		}
	},
});
