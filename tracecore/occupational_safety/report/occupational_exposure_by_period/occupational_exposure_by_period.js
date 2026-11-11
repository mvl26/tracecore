// Phơi nhiễm theo kỳ (FEAT-071, FR-M16-09): chỉ số liệu tổng hợp, không tên nhân viên, không mã BN.
frappe.query_reports["Occupational Exposure by Period"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.year_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["Exposure Type", "Department", "Occupation", "Device"],
			default: "Exposure Type",
		},
	],
};
