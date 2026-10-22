// Instrument Data Gaps (FR-M1-01.2): dụng cụ cần bổ sung cơ số, ảnh, IFU, Spaulding hoặc phương pháp.
frappe.query_reports["Instrument Data Gaps"] = {
	filters: [
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: [
				{ value: "Active", label: __("Active", null, "Instrument") },
				{ value: "Retired", label: __("Retired", null, "Instrument") },
			],
			default: "Active",
			reqd: 1,
		},
		{
			fieldname: "instrument_group",
			label: __("Instrument Group"),
			fieldtype: "Link",
			options: "Instrument Group",
		},
	],
};
