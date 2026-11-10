// IC Chemical Consumption by Department (FEAT-066, FR-M12-12): lít hóa chất KSNK theo loại × khoa của một quý (QĐ 38).
frappe.query_reports["IC Chemical Consumption by Department"] = {
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
			options: ["1", "2", "3", "4"],
			default: String(Math.floor(new Date().getMonth() / 3) + 1),
			reqd: 1,
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
	],
};
