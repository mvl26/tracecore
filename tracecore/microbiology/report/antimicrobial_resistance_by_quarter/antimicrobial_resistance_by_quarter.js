// Kháng thuốc theo quý (FEAT-067; FR-M14-08): S/I/R % theo vi khuẩn–kháng sinh trên chủng đầu tiên của quý.
const TC_AMR_NOW = new Date();

frappe.query_reports["Antimicrobial Resistance by Quarter"] = {
	filters: [
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: TC_AMR_NOW.getFullYear(),
			reqd: 1,
		},
		{
			fieldname: "quarter",
			label: __("Quarter"),
			fieldtype: "Select",
			options: ["1", "2", "3", "4"],
			default: String(Math.floor(TC_AMR_NOW.getMonth() / 3) + 1),
			reqd: 1,
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "organism",
			label: __("Organism", null, "Microbiology Isolate"),
			fieldtype: "Link",
			options: "Organism",
		},
		{ fieldname: "by_department", label: __("By Department"), fieldtype: "Check" },
	],
};
