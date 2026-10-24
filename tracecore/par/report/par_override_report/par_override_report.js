// Par Override Report (SCR-31, FR-M8-04.3): ghi đè cơ số theo tháng; mặc định cả tháng trước.
frappe.query_reports["Par Override Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.month_start(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.month_start(), -1),
			reqd: 1,
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [
				"",
				{ value: "Requested", label: __("Requested", null, "Par Override") },
				{ value: "Approved", label: __("Approved", null, "Par Override") },
				{ value: "Rejected", label: __("Rejected", null, "Par Override") },
				{ value: "Expired", label: __("Expired", null, "Par Override") },
				{ value: "Cancelled", label: __("Cancelled", null, "Par Override") },
			],
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "set_type",
			label: __("Set Type"),
			fieldtype: "Link",
			options: "Instrument Set Type",
		},
	],
};
