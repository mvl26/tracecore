// Laundry Cost per Kg (FR-M3-04.1, FEAT-034): chi phí/kg của lô giặt đã ghi sổ, theo tháng hoàn tất.
frappe.query_reports["Laundry Cost per Kg"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.year_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.year_end(),
			reqd: 1,
		},
	],
};
