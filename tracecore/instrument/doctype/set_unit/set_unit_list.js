/* global tracecore */
// Desk: list Set Unit (SCR-03, FEAT-016 Task 7). Trạng thái luôn có chữ. Không ai tạo Set Unit bằng nút "Mới" (G4): nút
// chính là "Cấp Set ID" (R02/R10/System Manager theo form_context.permissions, server kiểm lại); thao tác hàng loạt
// "In thẻ" (in gốc/in bù) và "Tải CSV khắc", tối đa form_context.limits.max_batch bộ một lần.
// Frappe tự xóa nút chính khi vẽ lại list (user không có quyền tạo) → đặt lại nút ở mỗi lần refresh.

function tc_su_list_primary(listview) {
	const ctx = listview.tc_su_ctx;
	if (ctx && ctx.permissions.can_issue) {
		listview.page.set_primary_action(
			__("Issue Set IDs"),
			() => tracecore.set_unit.issue_dialog({ on_done: () => listview.refresh() }),
			"add"
		);
	}
}

frappe.listview_settings["Set Unit"] = {
	add_fields: ["status", "set_type", "cycles_used", "max_cycles"],
	get_indicator(doc) {
		const color =
			window.tracecore && tracecore.set_unit
				? tracecore.set_unit.status_color(doc.status)
				: "gray";
		return [__(doc.status, null, "Set Unit"), color, `status,=,${doc.status}`];
	},
	onload(listview) {
		if (!(window.tracecore && tracecore.set_unit)) {
			return;
		}
		tracecore.set_unit.context().then((result) => {
			if (!result.ok) {
				return;
			}
			listview.tc_su_ctx = result.data;
			tc_su_list_primary(listview);
			tracecore.set_unit.add_bulk_actions(listview, result.data);
		});
	},
	refresh(listview) {
		tc_su_list_primary(listview);
	},
};
