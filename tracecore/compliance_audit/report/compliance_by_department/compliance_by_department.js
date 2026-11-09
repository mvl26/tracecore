// Compliance by Department (FEAT-060, FR-M12-14): phiếu giám sát đã ghi sổ theo mẫu × khoa, nhãn cỡ mẫu (FR-M12-11).
const TC_AUDIT_TYPES = [
	"Hand Hygiene",
	"Standard Precautions - PPE",
	"Prevention Bundle",
	"Environmental Hygiene",
	"Infrastructure",
	"Outsourced Service",
	"Food Safety",
	"Quality Self-Assessment",
	"Other",
];
const TC_PROFESSIONS = ["Doctor", "Nurse", "Midwife", "Technician", "Orderly", "Student", "Other"];

frappe.query_reports["Compliance by Department"] = {
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
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "audit_type",
			label: __("Audit Type"),
			fieldtype: "Select",
			options: [""].concat(TC_AUDIT_TYPES.map((value) => ({ value, label: __(value) }))),
		},
		{ fieldname: "template_code", label: __("Template Code"), fieldtype: "Data" },
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
		{
			fieldname: "profession",
			label: __("Observed Profession"),
			fieldtype: "Select",
			options: [""].concat(TC_PROFESSIONS.map((value) => ({ value, label: __(value) }))),
		},
	],
};
