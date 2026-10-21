// Desk: form Label Template — xem trước ZPL bằng dữ liệu mẫu (SCR-33, FEAT-002 Task 5, E7).
// Chỉ dựng trên server (tracecore.v1.label_template.preview); không gọi dịch vụ ngoài, chưa có "In thử".

const LABEL_TEMPLATE_PREVIEW = "tracecore.v1.label_template.preview";

function label_template_show_error(error) {
	frappe.msgprint({
		title: error.title || __("Label template could not be rendered"),
		indicator: "red",
		message: `<p>${frappe.utils.escape_html(
			error.reason || ""
		)}</p><p>${frappe.utils.escape_html(error.action || "")}</p>`,
	});
}

function label_template_show_zpl(zpl, unicode) {
	const variant = unicode ? __("with diacritics") : __("without diacritics");
	const note = __("Sample data, {0}. The saved version of the template is rendered.", [variant]);
	const dialog = new frappe.ui.Dialog({
		title: __("Label preview"),
		fields: [
			{
				fieldname: "note",
				fieldtype: "HTML",
				options: `<p class="text-muted">${frappe.utils.escape_html(note)}</p>`,
			},
			{
				fieldname: "zpl",
				fieldtype: "HTML",
				options: `<pre style="font-family: var(--tc-font-mono); white-space: pre-wrap;" aria-label="${frappe.utils.escape_html(
					__("ZPL code")
				)}">${frappe.utils.escape_html(zpl)}</pre>`,
			},
		],
		primary_action_label: __("Copy"),
		primary_action() {
			frappe.utils.copy_to_clipboard(zpl);
		},
	});
	dialog.show();
}

function label_template_preview(frm, unicode) {
	frappe.call({
		method: LABEL_TEMPLATE_PREVIEW,
		args: { template: frm.doc.name, unicode: unicode ? 1 : 0 },
		freeze: true,
		callback(r) {
			const result = r.message || {};
			if (result.ok) {
				label_template_show_zpl(result.zpl, unicode);
			} else if (result.error) {
				label_template_show_error(result.error);
			}
		},
		error(xhr) {
			const body = xhr && xhr.responseJSON;
			const error = body && body.message && body.message.error;
			if (error) {
				label_template_show_error(error);
			}
		},
	});
}

frappe.ui.form.on("Label Template", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		const group = __("Preview");
		frm.add_custom_button(
			__("Preview with diacritics"),
			() => label_template_preview(frm, true),
			group
		);
		frm.add_custom_button(
			__("Preview without diacritics"),
			() => label_template_preview(frm, false),
			group
		);
	},
});
