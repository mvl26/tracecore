// Linen Reconciliation (FEAT-035, FR-M3-06): bộ lọc khoa, loại đồ vải và kỳ; mặc định từ đầu tháng đến hôm nay.
frappe.query_reports["Linen Reconciliation"] = {
	filters: [
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "linen_type",
			label: __("Linen Type"),
			fieldtype: "Link",
			options: "Linen Type",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
	],
};
