/* global tracecore */
// Stock Alerts (FR-M6-06, SCR-26): tồn dưới tối thiểu, lô sắp hết hạn, vật tư thiếu cấu hình; tạo đề nghị mua một chạm.
const TC_PURCHASE_RPC = "tracecore.v1.stock.create_purchase_request";

frappe.query_reports["Stock Alerts"] = {
	filters: [
		{
			fieldname: "alert_type",
			label: __("Alert"),
			fieldtype: "Select",
			options: [
				"",
				{ value: "Below minimum", label: __("Below minimum") },
				{ value: "Expiring", label: __("Expiring") },
				{ value: "Not configured", label: __("Not configured") },
			],
		},
		{ fieldname: "days", label: __("Days to expiry"), fieldtype: "Int", default: 30 },
	],
	formatter: function (value, row, column, data, default_formatter) {
		if (column.fieldname === "alert_type") return __(value);
		if (column.fieldname === "action") {
			// chỉ R09, R02 lập được đề nghị mua (RPC kiểm lại ở máy chủ)
			const can_request = frappe.user.has_role(["TC R09", "TC R02", "System Manager"]);
			if (can_request && data && data.alert_type === "Below minimum") {
				return `<button type="button" class="btn btn-xs btn-primary tc-create-pr" data-item="${frappe.utils.escape_html(
					data.item
				)}" data-warehouse="${frappe.utils.escape_html(data.warehouse)}">${__(
					"Create purchase request"
				)}</button>`;
			}
			return "";
		}
		return default_formatter(value, row, column, data);
	},
	onload: function (report) {
		// một chạm = một khóa X-Idempotency-Key + một body; bấm lại sau lỗi mạng gửi nguyên request cũ
		const pending = {};
		report.page.wrapper.on("click", ".tc-create-pr", async function () {
			const button = $(this);
			const item = button.attr("data-item");
			const warehouse = button.attr("data-warehouse");
			const sig = `${item}|${warehouse}`;
			pending[sig] = pending[sig] || tracecore.codes.new_request({ item, warehouse });
			button.prop("disabled", true);
			const outcome = await tracecore.codes.send(TC_PURCHASE_RPC, pending[sig]);
			button.prop("disabled", false);
			if (outcome.ok) {
				delete pending[sig];
				const name = outcome.data.request.name;
				button.replaceWith(
					`<a href="/app/material-request/${encodeURIComponent(
						name
					)}">${frappe.utils.escape_html(name)}</a>`
				);
				return;
			}
			if (!outcome.network) delete pending[sig];
			const error = outcome.error || {};
			// lỗi chặn nghiệp vụ: kết quả, lý do, hành động ngay trên báo cáo (không modal)
			report.page.wrapper.find(".tc-pr-error").remove();
			report.page.wrapper
				.find(".report-wrapper")
				.before(
					`<div class="tc-pr-error alert alert-danger" role="alert"><strong>${frappe.utils.escape_html(
						error.title || ""
					)}</strong> ${frappe.utils.escape_html(
						error.reason || ""
					)} ${frappe.utils.escape_html(error.action || "")}</div>`
				);
		});
	},
};
