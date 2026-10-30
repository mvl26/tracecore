// Cost by Target (FR-M7-02.3, UC-27): chi phí đã ghi sổ theo thiết bị/khu/chương trình, chia theo ngày trong kỳ.
frappe.query_reports["Cost by Target"] = {
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
			fieldname: "target_type",
			label: __("Target Type"),
			fieldtype: "Select",
			options: [
				"",
				{ value: "Equipment", label: __("Equipment") },
				{ value: "Zone Station", label: __("Zone Station") },
				{ value: "Process Program", label: __("Process Program") },
			],
			on_change: function () {
				frappe.query_report.set_filter_value("target", "");
			},
		},
		{
			fieldname: "target",
			label: __("Target", null, "Cost Entry"),
			fieldtype: "Dynamic Link",
			options: "target_type",
			// Frappe tìm DocType ở <input data-fieldname="target_type">, nhưng Loại đối tượng là <select>: đọc thẳng bộ lọc
			get_options: () => frappe.query_report.get_filter_value("target_type"),
		},
		{
			fieldname: "category",
			label: __("Category", null, "Cost Entry"),
			fieldtype: "Link",
			options: "Cost Category",
		},
	],
};
