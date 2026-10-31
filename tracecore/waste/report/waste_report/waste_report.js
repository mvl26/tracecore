// Báo cáo chất thải (FEAT-050, UC-37): lọc kỳ, khoa, loại; kỳ chưa khóa hiện chữ Tạm ở cột Trạng thái kỳ.
frappe.query_reports["Waste Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "waste_type",
			label: __("Waste Type"),
			fieldtype: "Link",
			options: "Waste Type",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "report_status" && data)
			return __(data.report_status, null, "Waste Report");
		return default_formatter(value, row, column, data);
	},
};
