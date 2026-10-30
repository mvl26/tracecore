/* global tracecore */
// Nút "Xuất PDF" và "Khóa kỳ báo cáo" trên Script Report sổ tiệt khuẩn / KSNK / dự báo (FEAT-007, FR-M9-02, A-57).
// PDF sinh nền (RQ long); khi xong server phát realtime tc_report_ready kèm link tải, chuông Desk cũng có thông báo.
frappe.provide("tracecore.report_export");

tracecore.report_export.setup = function (report, kind, { lockable = true } = {}) {
	report.page.add_inner_button(__("Export PDF"), () => {
		frappe
			.call({
				method: "tracecore.v1.report.export",
				args: { kind, filters: JSON.stringify(report.get_filter_values(true) || {}) },
			})
			.then((r) => {
				if (r && r.message && r.message.ok) {
					frappe.show_alert({
						message: __(
							"The PDF is being prepared. You will be notified when it is ready."
						),
						indicator: "blue",
					});
				}
			});
	});
	if (lockable && frappe.user.has_role("TC R01")) {
		report.page.add_inner_button(__("Lock Report Period"), () => {
			// hiện ngày đang khóa, không điền sẵn "đến ngày" của bộ lọc: người dùng phải thấy ngày thật đã lưu
			frappe.call({ method: "tracecore.v1.report.lock_status", type: "GET" }).then((r) => {
				const locked = r.message && r.message.locked_until;
				frappe.prompt(
					{
						fieldname: "until",
						fieldtype: "Date",
						label: __("Reports Locked Until"),
						reqd: 1,
						default: locked || frappe.datetime.get_today(),
						description: locked
							? __("Currently locked until {0}.", [
									frappe.datetime.str_to_user(locked),
							  ])
							: __("No report period is locked yet."),
					},
					(values) =>
						frappe
							.call({
								method: "tracecore.v1.report.lock_period",
								args: { until: values.until },
							})
							.then((saved) => {
								frappe.show_alert({
									message: __("Reports locked until {0}.", [
										frappe.datetime.str_to_user(saved.message.locked_until),
									]),
									indicator: "green",
								});
								report.refresh();
							}),
					__("Lock Report Period"),
					__("Lock")
				);
			});
		});
	}
	if (!tracecore.report_export._listening) {
		tracecore.report_export._listening = true;
		frappe.realtime.on("tc_report_ready", (data) => {
			const link = $("<a>")
				.attr({ href: data.file_url, target: "_blank", rel: "noopener" })
				.text(__("Download"));
			frappe.msgprint({
				title: data.title,
				message: $("<div>").append(link).html(),
				indicator: "green",
			});
		});
	}
};
