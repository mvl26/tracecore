// Tổng kết KSNK năm (FEAT-058, FR-M11-06): lọc theo kế hoạch năm; xuất Excel bằng nút Export của Desk.
frappe.query_reports["IC Annual Summary"] = {
	filters: [
		{
			fieldname: "plan",
			label: __("Annual Plan"),
			fieldtype: "Link",
			options: "IC Annual Plan",
			reqd: 1,
		},
	],
};
