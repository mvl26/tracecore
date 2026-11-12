// Script Report "Wastewater Monitoring Summary" (FEAT-095; FR-M15-12): mặc định cả năm hiện tại
frappe.query_reports["Wastewater Monitoring Summary"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: `${new Date().getFullYear()}-01-01`,
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: `${new Date().getFullYear()}-12-31`,
			reqd: 1,
		},
		{
			fieldname: "wastewater_point",
			label: __("Point"),
			fieldtype: "Link",
			options: "Wastewater Point",
		},
	],
};
