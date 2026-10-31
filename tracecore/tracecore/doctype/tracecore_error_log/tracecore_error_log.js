/* global tracecore */
// Duyệt cho phép tạm NS-001 từ dòng Nhật ký lỗi (FEAT-052, A-71).
frappe.ui.form.on("TraceCore Error Log", {
	refresh(frm) {
		if (frm.doc.error_code !== "NS-001" || frm.doc.status !== "Open") return;
		frm.add_custom_button(__("Allow temporary access"), () => {
			frappe.prompt(
				[
					{
						fieldname: "hours",
						fieldtype: "Int",
						label: __("Hours (1 to 24)"),
						reqd: 1,
					},
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				],
				(values) => {
					tracecore.desk_call({
						method: "tracecore.v1.error_code.grant_permit",
						args: {
							error_log: frm.doc.name,
							hours: values.hours,
							reason: values.reason,
						},
						on_ok: () => frm.reload_doc(),
						on_block: (error) =>
							frappe.msgprint({
								title: error.title,
								message: `${frappe.utils.escape_html(
									error.reason
								)}<br>${frappe.utils.escape_html(error.action)}`,
								indicator: "red",
							}),
					});
				},
				__("Allow temporary access")
			);
		});
	},
});
