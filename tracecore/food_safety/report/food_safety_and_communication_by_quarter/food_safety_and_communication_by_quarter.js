// ATTP & truyền thông theo quý (FEAT-073, FR-M17-05.1): chỉ số liệu tổng hợp, không tên người.
frappe.query_reports["Food Safety and Communication by Quarter"] = {
	filters: [
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: new Date().getFullYear(),
			reqd: 1,
		},
		{
			fieldname: "quarter",
			label: __("Quarter"),
			fieldtype: "Select",
			options: ["Q1", "Q2", "Q3", "Q4"],
			default: `Q${Math.floor(new Date().getMonth() / 3) + 1}`,
			reqd: 1,
		},
	],
};
