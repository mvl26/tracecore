// Set Cost Report (FR-M7-06.1, UC-29): giá thành gói theo loại bộ / khoa / phương pháp / Cycle ID, so với kỳ trước.
frappe.query_reports["Set Cost Report"] = {
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
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: [
				{ value: "Set Type", label: __("Set Type") },
				{ value: "Department", label: __("Department") },
				{ value: "Method", label: __("Method") },
				{ value: "Cycle ID", label: __("Cycle ID") },
			],
			default: "Set Type",
			reqd: 1,
		},
	],
};
