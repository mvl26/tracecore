// Desk: cấu hình cơ số tái xử lý và cơ số tồn khoa (SCR-30, FEAT-031; UC-30, FR-M8-01, FR-M8-02).
// Quy tắc nằm ở server (tracecore.par.config): hợp lệ của đối tượng, min ≤ max, tối đa 20 % cho khoa cấp cứu, lý do
// khi đổi cơ số, lịch sử bất biến. JS chỉ hiện trạng thái "Đã xác định / Chưa xác định", số chu trình đã dùng của
// loại bộ (FR-M8-01.4) và gợi ý đối tượng theo loại cơ số.

const TC_PAR_STOCK_TARGETS = ["Instrument Set Type"];

function tc_par_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_par_status_html(frm) {
	if (frm.doc.par_kind !== "Reprocessing") {
		return "";
	}
	const defined = (frm.doc.max_cycles || 0) > 0;
	const label = defined ? __("Defined") : __("Undefined");
	const cls = defined ? "green" : "orange";
	return `<span class="indicator-pill ${cls}">${tc_par_escape(label)}</span>`;
}

function tc_par_show_used(frm) {
	const wrapper = frm.fields_dict.used_html;
	if (!wrapper) {
		return;
	}
	const status = tc_par_status_html(frm);
	wrapper.$wrapper.html(status);
	if (
		frm.doc.par_kind !== "Reprocessing" ||
		frm.doc.target_doctype !== "Instrument Set Type" ||
		!frm.doc.target
	) {
		return;
	}
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Set Unit",
			filters: { set_type: frm.doc.target },
			fields: ["max(cycles_used) as used"],
		},
		callback: (response) => {
			const used = ((response.message || [])[0] || {}).used || 0;
			const text = __("Highest cycles already used by a set of this type: {0}", [used]);
			wrapper.$wrapper.html(`${status} <p class="text-muted">${tc_par_escape(text)}</p>`);
		},
	});
}

frappe.ui.form.on("Par Level", {
	refresh(frm) {
		tc_par_show_used(frm);
	},
	max_cycles(frm) {
		tc_par_show_used(frm);
	},
	target(frm) {
		tc_par_show_used(frm);
	},
	par_kind(frm) {
		if (
			frm.doc.par_kind === "Department Stock" &&
			!TC_PAR_STOCK_TARGETS.includes(frm.doc.target_doctype)
		) {
			frm.set_value("target_doctype", TC_PAR_STOCK_TARGETS[0]);
		}
		tc_par_show_used(frm);
	},
});
