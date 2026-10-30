// Sync Conflict (FEAT-009, FR-M9-06.3): R02/R01 đóng xung đột bằng nút "Resolve" kèm cách xử lý; bản server giữ nguyên.
frappe.ui.form.on("Sync Conflict", {
	refresh(frm) {
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
