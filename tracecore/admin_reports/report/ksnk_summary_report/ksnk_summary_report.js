/* global tracecore */
// Báo cáo KSNK tổng hợp theo kỳ (FEAT-007, FR-M9-02, A-57 Q2): mặc định tháng hiện tại.
frappe.query_reports["KSNK Summary Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1,
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
	],
	onload(report) {
		tracecore.report_export.setup(report, "ksnk_summary", { lockable: true });
	},
};
