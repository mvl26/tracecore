// Desk: list view Instrument (SCR-01, FEAT-014 Task 6) — trạng thái và cơ số luôn có chữ, lọc nhanh cơ số Chưa xác định.
frappe.listview_settings["Instrument"] = {
	add_fields: ["status", "max_cycles_status", "max_cycles"],
	get_indicator(doc) {
		const colors = { Active: "blue", Retired: "gray" };
		if (!colors[doc.status]) {
			return null;
		}
		return [__(doc.status, null, "Instrument"), colors[doc.status], `status,=,${doc.status}`];
	},
	formatters: {
		max_cycles_status(value, df, doc) {
			if (value === "Defined") {
				return frappe.utils.escape_html(__("Max cycles: {0}", [doc.max_cycles]));
			}
			return `<span class="indicator-pill orange">${frappe.utils.escape_html(
				__("Max cycles: {0}", [__("Undefined", null, "Instrument")])
			)}</span>`;
		},
	},
	onload(listview) {
		listview.page.add_inner_button(__("Max cycles undefined"), () => {
			listview.filter_area.clear(false).then(() => {
				listview.filter_area.add([["Instrument", "max_cycles_status", "=", "Undefined"]]);
			});
		});
	},
};
