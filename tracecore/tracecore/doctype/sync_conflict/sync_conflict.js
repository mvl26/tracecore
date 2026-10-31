// Sync Conflict (FEAT-009, FR-M9-06.3): R02/R01 đóng xung đột bằng nút "Resolve" kèm cách xử lý; bản server giữ nguyên.
frappe.ui.form.on("Sync Conflict", {
	refresh(frm) {
		render_readable(frm);
		if (frm.doc.status !== "Open") return;
		const roles = ["TC R02", "TC R01", "System Manager"];
		if (!roles.some((role) => frappe.user.has_role(role))) return;
		frm.add_custom_button(__("Resolve"), () => {
			frappe.prompt(
				{
					fieldname: "note",
					fieldtype: "Small Text",
					label: __("How was it handled?"),
					reqd: 1,
				},
				({ note }) =>
					frappe
						.call("tracecore.v1.sync.resolve", { name: frm.doc.name, note })
						.then(() => frm.reload_doc()),
				__("Resolve sync conflict"),
				__("Resolve")
			);
		});
	},
});

// A-74: bác sĩ, KTV đọc được ngay; JSON và mã kỹ thuật vẫn lưu nhưng không hiện trên trang.
function render_readable(frm) {
	const data = frm.doc.__onload && frm.doc.__onload.readable;
	const field = frm.get_field("readable_html");
	if (!data || !field) return;
	const esc = frappe.utils.escape_html;
	const rows = data.details
		.map((row) => `<tr><th scope="row">${esc(row.label)}</th><td>${esc(row.value)}</td></tr>`)
		.join("");
	field.$wrapper.html(`
		<p><b>${esc(__("What happened"))}:</b> ${esc(data.operation)}</p>
		<p><b>${esc(__("Result"))}:</b> ${esc(data.outcome)}</p>
		<p><b>${esc(__("Reason"))}:</b> ${esc(data.reason)}</p>
		<p><b>${esc(__("What to do"))}:</b> ${esc(data.todo)}</p>
		${rows ? `<table class="table table-bordered"><tbody>${rows}</tbody></table>` : ""}
	`);
}
