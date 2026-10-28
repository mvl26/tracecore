// Báo cáo Shift Schedule (FEAT-037, FR-M4-04.2): mặc định tuần hiện tại; xuất bằng Menu → Export.
frappe.query_reports["Shift Schedule"] = {
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
