/* global tracecore */
// Desk: danh sách Batch — hành động hàng loạt "In nhãn QR" (FEAT-082, A-118): tối đa MAX_BULK lô mỗi lần, một PDF nhiều trang.

frappe.listview_settings["Batch"] = {
	onload(listview) {
		if (!window.tracecore || !tracecore.codes || !tracecore.codes.can_print_batch_label())
			return;
		listview.page.add_actions_menu_item(
			__("Print QR labels"),
			() => tracecore.codes.print_batch_labels(listview.get_checked_items(true)),
			false
		);
	},
};
