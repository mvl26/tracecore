// Program Consumable Gaps (A-111 D7, FR-M5-02.8): chương trình đang dùng còn thiếu vật tư.
frappe.query_reports["Program Consumable Gaps"] = {
	filters: [
		{
			fieldname: "equipment",
			label: __("Machine"),
			fieldtype: "Link",
			options: "Equipment",
		},
	],
};
