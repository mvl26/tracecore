// Hand Hygiene Compliance (FEAT-061, FR-M12-05): tỷ lệ vệ sinh tay theo cơ hội, nhóm theo khoa / nghề / thời điểm / tháng.
const TC_HH_GROUPS = ["department", "profession", "moment", "month"];
const TC_HH_GROUP_LABELS = {
	department: "Department",
	profession: "Observed Profession",
	moment: "Moment",
	month: "Month",
};
const TC_HH_PROFESSIONS = [
	"Doctor",
	"Nurse",
	"Midwife",
	"Technician",
	"Orderly",
	"Student",
	"Other",
];

frappe.query_reports["Hand Hygiene Compliance"] = {
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
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: TC_HH_GROUPS.map((value) => ({
				value,
				label: __(TC_HH_GROUP_LABELS[value]),
			})),
			default: "department",
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
			options: [""].concat(TC_HH_PROFESSIONS.map((value) => ({ value, label: __(value) }))),
		},
		{
			fieldname: "moment",
			label: __("Moment"),
			fieldtype: "Select",
			options: ["", "1", "2", "3", "4", "5"],
		},
	],
};
