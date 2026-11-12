// Wastewater Monitoring (FEAT-095; FR-M15-10): chọn điểm và ngày lấy mẫu → nạp thông số theo GPMT hiệu lực tại ngày đó
// (tracecore.v1.wastewater.parameters). Kết quả so giới hạn và bản chụp do server tính khi lưu.
frappe.ui.form.on("Wastewater Monitoring", {
	setup(frm) {
		frm.set_query("supplier", () => ({ filters: { tc_vimcerts_no: ["is", "set"] } }));
		frm.set_query("is_remonitor_of", () => ({
			filters: {
				wastewater_point: frm.doc.wastewater_point,
				overall_result: "Fail",
				docstatus: 1,
			},
		}));
	},
	wastewater_point(frm) {
		frm.trigger("load_parameters");
	},
	sampled_on(frm) {
		frm.trigger("load_parameters");
	},
	load_parameters(frm) {
		if (frm.doc.docstatus !== 0 || !frm.doc.wastewater_point || !frm.doc.sampled_on) return;
		const filled = (frm.doc.results || []).some((row) => row.value || row.below_detection);
		if (filled) return;
		frappe.call({
			method: "tracecore.v1.wastewater.parameters",
			type: "GET",
			args: { point: frm.doc.wastewater_point, sampled_on: frm.doc.sampled_on },
			callback: (r) => {
				const data = r.message || {};
				frm.clear_table("results");
				(data.results || []).forEach((row) =>
					frm.add_child("results", { parameter: row.parameter, unit: row.unit })
				);
				frm.set_value("wastewater_permit", data.permit || null);
				frm.set_value("standard_applied", data.standard || "");
				frm.refresh_field("results");
				if (!data.permit)
					frm.dashboard.set_headline(
						__(
							"No approved environmental permit covers this point on the sampling date."
						)
					);
			},
		});
	},
});
