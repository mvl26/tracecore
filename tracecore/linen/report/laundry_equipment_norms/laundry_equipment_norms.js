// Laundry Equipment Norms (FR-M3-10, #1847 DV-05): định mức và thực tế theo ngày, máy, chương trình.
frappe.query_reports["Laundry Equipment Norms"] = {
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
			fieldname: "equipment",
			label: __("Machine"),
			fieldtype: "Link",
			options: "Equipment",
			get_query: () => ({
				filters: { equipment_type: ["in", ["Laundry Washer", "Dryer"]] },
			}),
		},
		{
			fieldname: "program",
			label: __("Program"),
			fieldtype: "Link",
			options: "Process Program",
			get_query: () => {
				const equipment = frappe.query_report.get_filter_value("equipment");
				return equipment ? { filters: { equipment } } : {};
			},
		},
	],
};
