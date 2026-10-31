frappe.query_reports["Error Log Statistics"] = {
	filters: [
		{ fieldname: "from_date", label: __("From date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To date"), fieldtype: "Date" },
		{ fieldname: "error_code", label: __("Code"), fieldtype: "Link", options: "TraceCore Error Code" },
		{ fieldname: "station", label: __("Station"), fieldtype: "Link", options: "Zone Station" },
	],
};
