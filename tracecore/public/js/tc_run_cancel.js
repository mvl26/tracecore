/* global tracecore */
// Hộp thoại R02 hủy lô rửa / mẻ tiệt khuẩn nhập sai (A-112 D10, D11; FR-M2-03.10, FR-M2-09.10), dùng ở form Wash Batch và
// Sterilization Load. Lý do bắt buộc. Bị từ chối (RUN_CANCEL_BLOCKED, REASON_REQUIRED) thì lỗi đỏ ngay trong hộp thoại theo
// thứ tự kết quả → lý do → hành động, kèm bộ/gói đã đi tiếp; server quyết định mọi điều kiện.
frappe.provide("tracecore.run_cancel");

tracecore.run_cancel.can = function () {
	return ["TC R02", "System Manager"].some((role) => (frappe.user_roles || []).includes(role));
};

tracecore.run_cancel.dialog = function (frm, { method, arg, title, done }) {
	const esc = (text) =>
		frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
	const dialog = new frappe.ui.Dialog({
		title,
		fields: [
			{
				fieldname: "warning",
				fieldtype: "HTML",
				options: `<p>${esc(
					__(
						"The stock issue and cost sheet of this run are cancelled too; sets and packs go back to the step before."
					)
				)}</p>`,
			},
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
			{ fieldname: "error_html", fieldtype: "HTML" },
		],
		primary_action_label: title,
		primary_action(values) {
			const button = dialog.get_primary_btn();
			button.prop("disabled", true);
			tracecore.desk_call({
				method,
				args: { [arg]: frm.doc.name, reason: values.reason },
				on_ok: () => {
					dialog.hide();
					frappe.show_alert({ message: done, indicator: "green" });
					frm.reload_doc();
				},
				on_block: (error) => {
					button.prop("disabled", false);
					const items = (error.items || []).length
						? `<br><span class="tc-mono">${esc(error.items.join(", "))}</span>`
						: "";
					dialog.fields_dict.error_html.$wrapper.html(
						`<div class="alert alert-danger" role="alert"><b>✕ ${esc(
							error.title
						)}</b><br>${esc(error.reason)}${items}<br>${esc(error.action)}</div>`
					);
				},
				on_fail: () => button.prop("disabled", false),
			});
		},
	});
	dialog.show();
};
