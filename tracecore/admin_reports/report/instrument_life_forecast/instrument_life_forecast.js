/* global tracecore */
// Dự báo bộ dụng cụ hết vòng đời 12 tháng tới kèm giá (FEAT-007, FR-M9-02, A-57 Q4).
frappe.query_reports["Instrument Life Forecast"] = {
	filters: [
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
	],
	onload(report) {
		tracecore.report_export.setup(report, "life_forecast", { lockable: false });
	},
};
