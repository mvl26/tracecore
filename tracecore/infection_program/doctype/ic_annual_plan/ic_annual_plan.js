// IC Annual Plan (FEAT-058; FR-M11-04; BRU-ICP-004; A-133 Q1).
// R13 duyệt (ghi sổ) bằng nút riêng gọi RPC — ma trận cho R13 ghi sổ mà không sửa nội dung; R01 lập bản sửa đổi khi
// bản gốc còn hiệu lực (Frappe chuẩn chỉ Amend bản đã Hủy).
frappe.ui.form.on("IC Annual Plan", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.docstatus === 0 && frappe.user.has_role("TC R13")) {
			frm.add_custom_button(__("Approve (submit)"), () => {
				frappe
					.xcall("tracecore.v1.ksnk_plan.approve_plan", { name: frm.doc.name })
					.then((result) => {
						if (result && result.ok === false) {
							// lỗi chặn hiện inline đầu form: kết quả → lý do → hành động (design.md §6)
							const esc = frappe.utils.escape_html;
							frm.dashboard.set_headline_alert(
								`<b>${esc(result.error.title)}</b> ${esc(
									result.error.reason
								)} ${esc(result.error.action)}`,
								"red"
							);
							return;
						}
						frm.reload_doc();
					});
			}).addClass("btn-primary");
		}
		if (frm.doc.docstatus === 1 && frappe.user.has_role("TC R01")) {
			frm.add_custom_button(__("Create amendment (Amend)"), () => {
				frappe
					.xcall("tracecore.v1.ksnk_plan.make_amendment", { name: frm.doc.name })
					.then((result) => {
						if (result && result.ok)
							frappe.set_route("Form", "IC Annual Plan", result.name);
					});
			});
		}
		if (frm.doc.docstatus === 1) {
			frm.set_intro(
				__(
					"An approved plan is not edited directly; changes go through an amendment (Amend) approved again by the committee chair."
				),
				"blue"
			);
		}
	},
});
