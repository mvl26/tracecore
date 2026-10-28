// Desk: bảng định giá có phiên bản (SCR-28, FEAT-045; UC-28, FR-M7-03, FR-M7-04, A-48).
// Luật nằm ở server (tracecore.costing.rates): JS chỉ hiện chỉ báo trạng thái và nút lấy giá bình quân tồn kho (A1) cho
// bản Nháp. Lỗi chặn (chồng lấn hiệu lực, dòng trùng, số âm) do server báo.

function tc_rate_indicator(frm) {
	if (frm.is_new()) {
		return;
	}
	let state = [__("Draft", null, "Cost Rate Version"), "orange"];
	if (frm.doc.docstatus === 2) {
		state = [__("Cancelled", null, "Cost Rate Version"), "darkgrey"];
	} else if (frm.doc.docstatus === 1) {
		state = [__("Approved", null, "Cost Rate Version"), "green"];
	}
	frm.page.set_indicator(state[0], state[1]);
}

function tc_rate_fill_from_stock(frm) {
	frm.call({
		doc: frm.doc,
		method: "fill_from_stock",
		freeze: true,
		callback(r) {
			frm.refresh();
			const skipped = (r.message && r.message.skipped) || [];
			if (skipped.length) {
				frappe.msgprint({
					title: __("Some prices were kept"),
					indicator: "orange",
					message: __(
						"These items have no stock, so their prices were not changed: {0}",
						[frappe.utils.escape_html(skipped.join(", "))]
					),
				});
			}
		},
	});
}

frappe.ui.form.on("Cost Rate Version", {
	refresh(frm) {
		tc_rate_indicator(frm);
		if (!frm.is_new() && frm.doc.docstatus === 0 && frm.has_perm("write")) {
			frm.add_custom_button(__("Take Prices from Stock"), () =>
				tc_rate_fill_from_stock(frm)
			);
		}
	},
});

frappe.ui.form.on("Cost Rate Line", {
	// đổi loại đơn giá thì bỏ vật tư cũ (chỉ loại Vật tư có vật tư)
	rate_type(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "item", "");
	},
});
