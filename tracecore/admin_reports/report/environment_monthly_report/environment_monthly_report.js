// Báo cáo tháng môi trường khu (FEAT-008, FR-M9-04): mặc định tháng hiện tại.
frappe.query_reports["Environment Monthly Report"] = {
	filters: [
		{
			fieldname: "month",
			label: __("Month"),
			fieldtype: "Select",
			options: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
			default: String(
				frappe.datetime.str_to_obj(frappe.datetime.get_today()).getMonth() + 1
			),
			reqd: 1,
		},
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: frappe.datetime.str_to_obj(frappe.datetime.get_today()).getFullYear(),
			reqd: 1,
		},
		{
			fieldname: "zone",
			label: __("Zone"),
			fieldtype: "Link",
			options: "Zone Station",
			get_query: () => ({ filters: { is_zone: 1 } }),
		},
	],
};
