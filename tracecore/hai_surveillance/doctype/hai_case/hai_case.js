/* global tracecore */
// HAI Case — Desk form (FEAT-063; FR-M13-05, 05.1, 15; A-144 b, g). Mã định nghĩa chọn từ bản đã duyệt; R11/R01 có
// nút Xác định / Loại trừ (bắt buộc lý do) và Xem mã BN (lý do + Audit Log). R08/R12 chỉ tạo ca Nghi ngờ: không có nút
// Xác định (FR-M13-05.1). Ghi sổ trực tiếp bị chặn: phải qua Xác định hoặc Loại trừ.

const TC_HAI_DECIDERS = ["TC R01", "TC R11"];

function tc_hai_can_decide() {
	return frappe.user.has_role(TC_HAI_DECIDERS) || frappe.session.user === "Administrator";
}

function tc_hai_decide(frm, decision, field) {
	const send = (reason) =>
		tracecore.desk_call({
			method: "tracecore.v1.hai_case.decide",
			args: {
				name: frm.doc.name,
				decision,
				reason: decision === "Excluded" ? reason : "",
				exception_reason: decision === "Confirmed" ? reason || "" : "",
			},
			on_ok: () => frm.reload_doc(),
			on_block: (error) =>
				frappe.msgprint({
					title: error.title || __("Not saved"),
					message: `${frappe.utils.escape_html(
						error.reason || ""
					)}<br>${frappe.utils.escape_html(error.action || "")}`,
					indicator: "red",
				}),
		});
	if (!field) {
		send("");
		return;
	}
	frappe.prompt(
		[{ fieldname: "reason", fieldtype: "Small Text", label: __(field), reqd: 1 }],
		(values) => send(values.reason),
		decision === "Excluded" ? __("Exclude case") : __("Confirm case with an exception"),
		__("Confirm")
	);
}

frappe.ui.form.on("HAI Case", {
	onload(frm) {
		frappe
			.xcall("tracecore.v1.hai_case.definition_codes", {}, "GET")
			.then((result) => {
				const options = (result.definitions || []).map((row) => ({
					value: row.def_code,
					label: `${row.def_code} — ${row.title || ""}`,
				}));
				frm.set_df_property("def_code", "options", options);
			})
			.catch(() => {});
	},

	refresh(frm) {
		frm.set_intro(
			__(
				"The patient name is never recorded; lists and exports show only the masked patient code."
			),
			"blue"
		);
		if (frm.is_new() || !tc_hai_can_decide()) return;
		if (frm.doc.docstatus === 0) {
			frm.page.clear_primary_action();
			frm.add_custom_button(__("Confirm case"), () =>
				tc_hai_decide(
					frm,
					"Confirmed",
					frm.doc.time_check === "Not met" ? "Exception Reason" : null
				)
			);
			frm.add_custom_button(__("Exclude (enter reason)"), () =>
				tc_hai_decide(frm, "Excluded", "Exclusion Reason")
			);
		}
		frm.add_custom_button(__("View full patient code"), () =>
			frappe.prompt(
				[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
				(values) =>
					tracecore.desk_call({
						method: "tracecore.v1.patient_code.reveal",
						args: { doctype: "HAI Case", name: frm.doc.name, reason: values.reason },
						on_ok: (result) =>
							frappe.msgprint({
								title: __("Patient Code"),
								message: frappe.utils.escape_html(result.patient_code || "—"),
							}),
					}),
				__("Why do you need the full patient code?"),
				__("Confirm")
			)
		);
	},
});
