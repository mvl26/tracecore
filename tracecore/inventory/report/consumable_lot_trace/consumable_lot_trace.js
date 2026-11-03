// Consumable Lot Trace (FR-M6-08, A-112 D14): từ một lô vật tư ra các lô rửa, mẻ, test, phiếu xuất đã dùng lô đó.
// Dòng mẻ tiệt khuẩn có liên kết Pack Trace lọc theo mẻ để lấy danh sách gói cần thu hồi.
frappe.query_reports["Consumable Lot Trace"] = {
	filters: [
		{ fieldname: "batch", label: __("Batch"), fieldtype: "Link", options: "Batch", reqd: 1 },
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "source_type" && value) return __(value);
		if (
			column.fieldname === "packs" &&
			data &&
			data.source_type === "Sterilization Load" &&
			value
		) {
			const url = `/app/query-report/Pack Trace?load=${encodeURIComponent(data.source)}`;
			return `<a href="${url}">${frappe.utils.escape_html(String(value))} · ${__(
				"Pack Trace"
			)}</a>`;
		}
		return default_formatter(value, row, column, data);
	},
};
