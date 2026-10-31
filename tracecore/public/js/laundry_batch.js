// Desk: form Laundry Batch. Nút "Retry consumption" cho R09/R02 khi tiêu hao tự động bị lỗi (thông báo CONSUMPTION_FAILED trỏ về
// đây, A-78). Chỉ trình bày: server (tracecore.v1.stock.retry_consumption) quyết định và không trừ kho hai lần.

frappe.ui.form.on("Laundry Batch", {
	refresh(frm) {
		const roles = frappe.user_roles || [];
		const allowed = ["TC R09", "TC R02", "System Manager"].some((role) =>
			roles.includes(role)
		);
		if (!allowed || frm.doc.docstatus !== 1 || frm.doc.batch_type === "Outsourced") return;
		frm.add_custom_button(__("Retry consumption"), () => {
			frappe.call({
				method: "tracecore.v1.stock.retry_consumption",
				args: { source_doctype: "Laundry Batch", source_name: frm.doc.name },
				freeze: true,
				callback: (r) => {
					const res = r.message || {};
					frappe.show_alert({
						message: res.created
							? __("Supplies were issued: {0}", [res.entry])
							: __("This batch already has an issue: nothing more was deducted."),
						indicator: "green",
					});
				},
			});
		});
	},
});
