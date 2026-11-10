// NKVM theo nhóm phẫu thuật và NNIS (FEAT-064, FR-M13-12, A-147 k): chỉ số liệu tổng hợp; xuất Excel bằng nút Export
// của Desk, xuất theo mẫu cơ quan quản lý ở SCR-58.
frappe.query_reports["SSI by Procedure Group"] = {
	filters: [
		{
			fieldname: "period_from",
			label: __("From month"),
			fieldtype: "Data",
			reqd: 1,
			description: "YYYY-MM",
		},
		{
			fieldname: "period_to",
			label: __("To month"),
			fieldtype: "Data",
			description: "YYYY-MM",
		},
	],
};
