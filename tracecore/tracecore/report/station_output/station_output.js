// Báo cáo Station Output (FEAT-037, FR-M4-04): sản lượng theo người và ca; mặc định tuần hiện tại.
frappe.query_reports["Station Output"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.week_start(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.week_end(),
		},
		{ fieldname: "zone", label: __("Work Zone"), fieldtype: "Link", options: "Zone Station" },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
	],
};
