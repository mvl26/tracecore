// Tồn kho chất thải (FEAT-048, UC-35 A3): trạng thái luôn có chữ, nút chỉnh ngưỡng cho R02/R10 (A-61).
frappe.query_reports["Waste Storage Stock"] = {
	filters: [],
	formatter(value, row, column, data, default_formatter) {
		const text = default_formatter(value, row, column, data);
		if (column.fieldname !== "state" || !data) return text;
		const label = __(data.state, null, "Waste Storage");
		if (data.state === "Overdue") return `<span class="indicator-pill red">${label}</span>`;
		if (data.state === "Due Soon")
			return `<span class="indicator-pill orange">${label}</span>`;
		return `<span class="indicator-pill green">${label}</span>`;
	},
	onload(report) {
		if (!frappe.user.has_role(["TC R02", "TC R10", "System Manager"])) return;
		report.page.add_inner_button(__("Storage Thresholds"), () => {
			frappe.call({ method: "tracecore.v1.waste.thresholds" }).then((r) => {
				const values = r.message;
				frappe.prompt(
					[
						{
							fieldname: "warn_percent",
							fieldtype: "Int",
							label: __("Storage Warning (%)"),
							reqd: 1,
							default: values.warn_percent,
						},
						{
							fieldname: "cold_limit_c",
							fieldtype: "Float",
							label: __("Cold Room Limit (°C)"),
							reqd: 1,
							default: values.cold_limit_c,
						},
						{
							fieldname: "breach_hours",
							fieldtype: "Float",
							label: __("Hours Above the Limit"),
							reqd: 1,
							default: values.breach_hours,
						},
						{
							fieldname: "variance_percent",
							fieldtype: "Float",
							label: __("Handover Weight Difference (%)"),
							reqd: 1,
							default: values.variance_percent,
						},
					],
					(saved) =>
						frappe
							.call({ method: "tracecore.v1.waste.set_thresholds", args: saved })
							.then((res) => {
								if (res.message.ok) {
									frappe.show_alert({
										message: __("Saved"),
										indicator: "green",
									});
									report.refresh();
								} else {
									frappe.msgprint(res.message.error.reason);
								}
							}),
					__("Storage Thresholds"),
					__("Save")
				);
			});
		});
	},
};
