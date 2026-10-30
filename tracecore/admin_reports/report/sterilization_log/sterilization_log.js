/* global tracecore */
// Sổ tiệt khuẩn điện tử theo máy (FEAT-007, FR-M9-02, A-57 Q1): mặc định tháng hiện tại.
frappe.query_reports["Sterilization Log"] = {
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
			fieldname: "equipment",
			label: __("Machine"),
			fieldtype: "Link",
			options: "Equipment",
			get_query: () => ({
				filters: { equipment_type: ["in", ["Steam Sterilizer", "Plasma Sterilizer"]] },
			}),
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
	],
	onload(report) {
		tracecore.report_export.setup(report, "sterilization_log", { lockable: true });
	},
};
