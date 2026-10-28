// Desk: khoản chi phí theo kỳ và phân bổ đối tượng (SCR-27, FEAT-044; UC-27, FR-M7-01, FR-M7-02).
// Luật nằm ở server (tracecore.costing.entry): JS chỉ hiện chỉ báo, tổng tỷ lệ phân bổ, lượng tiêu thụ của đồng hồ và báo
// trước các điều kiện chặn ghi sổ bằng khối đỏ kết quả → lý do → hành động ngay trên form (không dùng thông báo nổi cho
// lỗi chặn). Server vẫn chặn nếu form bị vượt qua.

const TC_COST_TOTAL = 100;

function tc_cost_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

// tổng tỷ lệ phân bổ hiện trên form, làm tròn như server (3 chữ số)
function tc_cost_allocation_total(doc) {
	const sum = (doc.allocations || []).reduce((total, row) => total + flt(row.percent), 0);
	return flt(sum, 3);
}

// lỗi chặn: kết quả (đậm) → lý do → hành động, màu đỏ toàn khối
function tc_cost_error_html(error) {
	const lines = [
		`<b>✕ ${tc_cost_escape(error.title)}</b>`,
		tc_cost_escape(error.reason),
		tc_cost_escape(error.action),
	];
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

// điều kiện ghi sổ, cùng luật server (FR-M7-02.1); trả null khi đủ
function tc_cost_submit_problem(doc) {
	if (!(doc.allocations || []).length) {
		return {
			title: __("Allocation is missing"),
			reason: __(
				"A cost entry needs at least one allocation target before it is submitted."
			),
			action: __("Add a machine, zone or process program, then submit again."),
		};
	}
	const total = tc_cost_allocation_total(doc);
	if (total !== TC_COST_TOTAL) {
		return {
			title: __("Allocation does not total 100 %"),
			reason: __("The allocation percentages total {0} %.", [total]),
			action: __("Adjust the percentages to total 100 %, then submit again."),
		};
	}
	return null;
}

function tc_cost_indicator(frm) {
	if (frm.is_new()) {
		return;
	}
	let state = [__("Draft", null, "Cost Entry"), "orange"];
	if (frm.doc.docstatus === 2) {
		state = [__("Cancelled", null, "Cost Entry"), "darkgrey"];
	} else if (frm.doc.docstatus === 1) {
		state = [__("Submitted", null, "Cost Entry"), "green"];
	}
	frm.page.set_indicator(state[0], state[1]);
}

// tổng tỷ lệ luôn có chữ: đủ 100 % hay thiếu/thừa bao nhiêu
function tc_cost_allocation_headline(frm) {
	frm.dashboard.clear_headline();
	if (frm.doc.docstatus !== 0 || !(frm.doc.allocations || []).length) {
		return;
	}
	const total = tc_cost_allocation_total(frm.doc);
	if (total === TC_COST_TOTAL) {
		frm.dashboard.set_headline_alert(
			tc_cost_escape(__("Allocation total: {0} %", [total])),
			"alert-success"
		);
	} else {
		frm.dashboard.set_headline_alert(
			tc_cost_escape(__("Allocation total: {0} % - it must total 100 %.", [total])),
			"alert-warning"
		);
	}
}

function tc_cost_update_quantity(frm) {
	if (frm.doc.source === "Meter") {
		frm.set_value("quantity", flt(frm.doc.closing_reading) - flt(frm.doc.opening_reading));
	}
}

frappe.ui.form.on("Cost Entry", {
	setup(frm) {
		frm.set_query("category", () => ({ filters: { is_active: 1 } }));
	},

	refresh(frm) {
		tc_cost_indicator(frm);
		tc_cost_allocation_headline(frm);
	},

	before_submit(frm) {
		const error = tc_cost_submit_problem(frm.doc);
		if (error) {
			frappe.validated = false;
			frm.dashboard.set_headline_alert(tc_cost_error_html(error));
		}
	},

	opening_reading: tc_cost_update_quantity,
	closing_reading: tc_cost_update_quantity,
	source: tc_cost_update_quantity,
});

frappe.ui.form.on("Cost Allocation", {
	percent(frm) {
		tc_cost_allocation_headline(frm);
	},

	allocations_remove(frm) {
		tc_cost_allocation_headline(frm);
	},

	// đổi loại đối tượng thì bỏ đối tượng cũ (không thuộc loại mới)
	target_type(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "target", "");
	},
});
