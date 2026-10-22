// Desk: cấu hình cơ số tái xử lý và cơ số tồn khoa (SCR-30, FEAT-031; UC-30, FR-M8-01, FR-M8-02).
// Quy tắc nằm ở server (tracecore.par.config): hợp lệ của đối tượng, min ≤ max, tối đa 20 % cho khoa cấp cứu, lý do
// khi đổi cơ số, lịch sử bất biến, cơ số ≤ đã dùng. JS chỉ hiện trạng thái "Đã xác định / Chưa xác định",
// "Đã dùng N / Cơ số M" của loại bộ, hỏi xác nhận trước khi lưu cơ số ≤ đã dùng (FR-M8-01.4), đánh dấu lý do bắt buộc
// khi đổi cơ số (FR-M8-01.3) và gợi ý đối tượng theo loại cơ số.

const TC_PAR_STOCK_TARGETS = ["Instrument Set Type"];
const TC_PAR_REASON_FIELDS = ["max_cycles", "min_qty", "max_qty"];

function tc_par_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

// true khi phải hỏi xác nhận: cơ số tái xử lý > 0, đã biết số chu trình đã dùng và cơ số không cao hơn số đó
function tc_par_needs_confirm(doc, used) {
	const cap = Number(doc.max_cycles) || 0;
	return (
		doc.par_kind === "Reprocessing" &&
		cap > 0 &&
		used !== null &&
		used !== undefined &&
		cap <= Number(used) &&
		!Number(doc.confirm_below_used)
	);
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

function tc_par_render(frm) {
	const wrapper = frm.fields_dict.used_html;
	if (!wrapper) {
		return;
	}
	let html = tc_par_status_html(frm);
	if (
		frm.doc.par_kind === "Reprocessing" &&
		frm.tc_par_used !== null &&
		frm.tc_par_used !== undefined
	) {
		const cap = (frm.doc.max_cycles || 0) > 0 ? frm.doc.max_cycles : __("Undefined");
		const text = __("Used {0} / Limit {1}", [frm.tc_par_used, cap]);
		html += ` <p class="text-muted">${tc_par_escape(text)}</p>`;
	}
	wrapper.$wrapper.html(html);
}

function tc_par_load_used(frm) {
	frm.tc_par_used = null;
	tc_par_render(frm);
	if (
		frm.doc.par_kind !== "Reprocessing" ||
		frm.doc.target_doctype !== "Instrument Set Type" ||
		!frm.doc.target
	) {
		return;
	}
	const target = frm.doc.target;
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Set Unit",
			filters: { set_type: target },
			fields: ["max(cycles_used) as used"],
		},
		callback: (response) => {
			if (frm.doc.target !== target) {
				return;
			}
			frm.tc_par_used = ((response.message || [])[0] || {}).used || 0;
			tc_par_render(frm);
		},
	});
}

function tc_par_toggle_reason(frm) {
	const before = frm.tc_par_saved || {};
	const changed =
		!frm.is_new() &&
		TC_PAR_REASON_FIELDS.some((field) => (frm.doc[field] || 0) !== (before[field] || 0));
	frm.toggle_reqd("reason", changed);
}

function tc_par_on_value_change(frm) {
	tc_par_render(frm);
	tc_par_toggle_reason(frm);
}

frappe.ui.form.on("Par Level", {
	refresh(frm) {
		frm.tc_par_saved = {};
		TC_PAR_REASON_FIELDS.forEach((field) => {
			frm.tc_par_saved[field] = frm.doc[field] || 0;
		});
		tc_par_toggle_reason(frm);
		tc_par_load_used(frm);
	},
	max_cycles: tc_par_on_value_change,
	min_qty: tc_par_on_value_change,
	max_qty: tc_par_on_value_change,
	target(frm) {
		tc_par_load_used(frm);
	},
	par_kind(frm) {
		if (
			frm.doc.par_kind === "Department Stock" &&
			!TC_PAR_STOCK_TARGETS.includes(frm.doc.target_doctype)
		) {
			frm.set_value("target_doctype", TC_PAR_STOCK_TARGETS[0]);
		}
		tc_par_load_used(frm);
	},
	validate(frm) {
		// FR-M8-01.4: hỏi trước khi lưu; đồng ý → tick confirm_below_used và lưu lại (server vẫn kiểm)
		if (!tc_par_needs_confirm(frm.doc, frm.tc_par_used)) {
			return;
		}
		frappe.validated = false;
		const message = __(
			"Cycle limit {0} is not above the {1} cycles already used. Save it anyway?",
			[frm.doc.max_cycles, frm.tc_par_used]
		);
		frappe.confirm(tc_par_escape(message), () => {
			frm.set_value("confirm_below_used", 1).then(() => frm.save());
		});
	},
});
