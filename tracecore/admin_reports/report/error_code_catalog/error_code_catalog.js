frappe.query_reports["Error Code Catalog"] = {
	filters: [
		{
			fieldname: "station",
			label: __("Station"),
			fieldtype: "Link",
			options: "Station Function",
		},
		{
			fieldname: "code",
			label: __("Code"),
			fieldtype: "Link",
			options: "TraceCore Error Code",
		},
	],
};
