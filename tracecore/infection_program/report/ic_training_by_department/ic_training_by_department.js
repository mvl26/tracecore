// IC Training by Department (FEAT-059; FR-M11-09): tỷ lệ đào tạo KSNK cơ bản trong năm theo khoa; nút nhắc người
// chưa học (UC-42 A2) cho R01/R02/R10.
frappe.query_reports["IC Training by Department"] = {
	filters: [
		{
			fieldname: "year",
			label: __("Year"),
			fieldtype: "Int",
			default: new Date().getFullYear(),
			reqd: 1,
		},
		{
			fieldname: "department",
			label: __("Department"),
			fieldtype: "Link",
			options: "Department",
		},
	],
	onload(report) {
		report.page.add_inner_button(__("Remind staff not trained"), () => {
			const department = report.get_filter_value("department");
			if (!department) {
				frappe.show_alert({
					message: __("Choose a department first."),
					indicator: "orange",
				});
				return;
			}
			frappe
				.xcall("tracecore.v1.ksnk_training.remind", {
					department,
					year: report.get_filter_value("year"),
				})
				.then((result) => {
					if (!result.ok) {
						frappe.show_alert({ message: result.error.reason, indicator: "red" });
						return;
					}
					frappe.show_alert({
						message: __("Reminder sent to {0} people; {1} have no user account.", [
							result.sent,
							result.without_account,
						]),
						indicator: "green",
					});
				});
		});
	},
};
