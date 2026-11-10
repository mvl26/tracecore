// Environmental Hygiene (FEAT-070, FR-M15-07): báo cáo môi trường tháng/quý — xuất Excel bằng Export, PDF bằng In.
frappe.query_reports["Environmental Hygiene"] = {
	filters: [
		{
			fieldname: "period_type",
			label: __("Period"),
			fieldtype: "Select",
			options: [
				{ value: "Month", label: __("Month") },
				{ value: "Quarter", label: __("Quarter") },
			],
			default: "Month",
			reqd: 1,
		},
		{
			fieldname: "date",
			label: __("Any Date in Period"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
	],
};
