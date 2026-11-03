/* global tracecore */
// Desk: form Wash Batch (lô rửa T2). Nút "Retry consumption" cho R09/R02 khi tiêu hao tự động của lô Đạt bị lỗi
// (thông báo CONSUMPTION_FAILED trỏ về đây). Chỉ trình bày: server (tracecore.v1.stock.retry_consumption) quyết định
// và không trừ kho hai lần.
// A-112 D10: nút "Cancel wash batch" cho R02 khi lô Đang chạy, Chờ kết quả hoặc Đạt (hộp thoại tracecore.run_cancel).
const TC_WASH_CANCELLABLE = ["Running", "Awaiting Result", "Passed"];

frappe.ui.form.on("Wash Batch", {
	refresh(frm) {
		if (
			frm.doc.docstatus < 2 &&
			TC_WASH_CANCELLABLE.includes(frm.doc.status) &&
			tracecore.run_cancel.can()
		) {
			frm.add_custom_button(__("Cancel wash batch"), () =>
				tracecore.run_cancel.dialog(frm, {
					method: "tracecore.v1.wash.cancel",
					arg: "batch",
					title: __("Cancel wash batch"),
					done: __("Wash batch cancelled"),
				})
			);
		}
		const roles = frappe.user_roles || [];
		const allowed = ["TC R09", "TC R02", "System Manager"].some((role) =>
			roles.includes(role)
		);
		if (!allowed || frm.doc.docstatus !== 1 || frm.doc.cycle_result !== "Pass") return;
		frm.add_custom_button(__("Retry consumption"), () => {
			frappe.call({
				method: "tracecore.v1.stock.retry_consumption",
				args: { source_doctype: "Wash Batch", source_name: frm.doc.name },
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
