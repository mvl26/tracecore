// Consumable Usage (FR-M6-07, A-112 D12): định mức so với thực dùng theo kỳ, máy, công đoạn, loại test, vật tư.
const TC_USAGE_STAGES = ["Washing", "Disinfection", "Sterilization", "Test"];
const TC_USAGE_TEST_TYPES = ["bowie_dick", "leak", "plasma_daily"];

frappe.query_reports["Consumable Usage"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: [
				{ value: "Month", label: __("Month") },
				{ value: "Day", label: __("Day") },
			],
			default: "Month",
		},
		{ fieldname: "equipment", label: __("Machine"), fieldtype: "Link", options: "Equipment" },
		{
			fieldname: "stage",
			label: __("Stage"),
			fieldtype: "Select",
			options: [""].concat(
				TC_USAGE_STAGES.map((value) => ({
					value,
					label: __(value, null, "Consumable Usage"),
				}))
			),
		},
		{
			fieldname: "test_type",
			label: __("Test Type"),
			fieldtype: "Select",
			options: [""].concat(
				TC_USAGE_TEST_TYPES.map((value) => ({ value, label: __(value) }))
			),
		},
		{ fieldname: "item", label: __("Item"), fieldtype: "Link", options: "Item" },
		{
			fieldname: "role",
			label: __("Role"),
			fieldtype: "Select",
			options: [
				"",
				"Chemical",
				"Test Pack",
				"Chemical Indicator",
				"Biological Indicator",
				"Packaging",
				"Label",
				"Other",
			].map((value) =>
				value ? { value, label: __(value, null, "Program Consumable") } : ""
			),
		},
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "stage" && value) return __(value, null, "Consumable Usage");
		if (column.fieldname === "role" && value) return __(value, null, "Program Consumable");
		if (column.fieldname === "test_type" && value) return __(value);
		return default_formatter(value, row, column, data);
	},
};
