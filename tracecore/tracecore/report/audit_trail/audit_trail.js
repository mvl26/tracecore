// Audit Trail (FEAT-004, A-37 c, NFR-SEC-03): lịch sử thao tác theo đối tượng, người, trạm, loại thao tác, khoảng ngày.
frappe.query_reports["Audit Trail"] = {
	filters: [
		{
			fieldname: "ref_doctype",
			label: __("Document Type"),
			fieldtype: "Link",
			options: "DocType",
		},
		{
			fieldname: "ref_name",
			label: __("Document"),
			fieldtype: "Dynamic Link",
			options: "ref_doctype",
		},
		{ fieldname: "user", label: __("User"), fieldtype: "Link", options: "User" },
		{ fieldname: "station", label: __("Station"), fieldtype: "Link", options: "Zone Station" },
		{
			fieldname: "action",
			label: __("Action"),
			fieldtype: "Select",
			options: [
				"",
				"Create",
				"Update",
				"Submit",
				"Cancel",
				"Delete",
				"Login",
				"Reject",
				"Override",
				"View Patient Code",
				"Sync",
			],
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
	],
};
