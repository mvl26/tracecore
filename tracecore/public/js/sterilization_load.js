/* global tracecore */
// Desk: form Sterilization Load. Nút "Retry consumption" cho R09/R02 khi tiêu hao tự động bị lỗi (thông báo CONSUMPTION_FAILED trỏ về
// đây, A-78). Chỉ trình bày: server (tracecore.v1.stock.retry_consumption) quyết định và không trừ kho hai lần.
// A-112 D11: nút "Cancel load" cho R02 khi mẻ chưa Không đạt (hộp thoại tracecore.run_cancel).
const TC_LOAD_CANCELLABLE = ["Running", "Cycle Complete", "Quarantine", "Released"];

frappe.ui.form.on("Sterilization Load", {
	refresh(frm) {
		if (
			frm.doc.docstatus < 2 &&
			TC_LOAD_CANCELLABLE.includes(frm.doc.status) &&
			tracecore.run_cancel.can()
		) {
			frm.add_custom_button(__("Cancel load"), () =>
				tracecore.run_cancel.dialog(frm, {
					method: "tracecore.v1.load.cancel",
					arg: "load",
					title: __("Cancel load"),
					done: __("Sterilization load cancelled"),
				})
			);
		}
		const roles = frappe.user_roles || [];
		const allowed = ["TC R09", "TC R02", "System Manager"].some((role) =>
			roles.includes(role)
		);
		if (!allowed || frm.doc.docstatus !== 1 || frm.doc.status !== "Released") return;
		frm.add_custom_button(__("Retry consumption"), () => {
			frappe.call({
				method: "tracecore.v1.stock.retry_consumption",
				args: { source_doctype: "Sterilization Load", source_name: frm.doc.name },
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
