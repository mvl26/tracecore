// Desk: sự cố / NC / CAPA (SCR-15, FEAT-030; UC-15, FR-M2-21, FR-M2-22, WF-06).
// Quy tắc nằm ở server (tracecore.reprocessing.incidents): chỉ R01/R02 chuyển bước, đóng, hủy; người phụ trách ghi
// kết quả hành động của mình. JS chỉ hiện nút theo trạng thái, thu thập giá trị và đưa lỗi chặn về dạng
// kết quả → lý do → hành động ngay trong hộp thoại hoặc khối đỏ trên form (không dùng thông báo nổi cho lỗi chặn).

const TC_INCIDENT_SUPERVISORS = ["TC R01", "TC R02"];
const TC_INCIDENT_API = "tracecore.v1.incident.";

function tc_incident_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_incident_is_supervisor() {
	return (
		frappe.session.user === "Administrator" ||
		TC_INCIDENT_SUPERVISORS.some((role) => frappe.user.has_role(role))
	);
}

// lỗi chặn: kết quả (đậm) → lý do → hành động, màu đỏ toàn khối
function tc_incident_error_html(error) {
	const lines = [
		`<b>✕ ${tc_incident_escape(error.title)}</b>`,
		tc_incident_escape(error.reason),
		tc_incident_escape(error.action),
	];
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

// gọi RPC; lỗi chặn hiện trong `show_error` (hộp thoại) hoặc khối đỏ trên form
function tc_incident_call(frm, method, args, show_error, done) {
	frappe.call({
		method: TC_INCIDENT_API + method,
		args: { incident: frm.doc.name, ...args },
		callback: (response) => {
			const result = response.message || {};
			if (result.ok === false) {
				show_error(tc_incident_error_html(result.error));
				return;
			}
			if (done) {
				done();
			}
			frm.reload_doc();
		},
	});
}

function tc_incident_form_error(frm) {
	return (html) => frm.dashboard.set_headline_alert(html);
}

function tc_incident_dialog(frm, title, fields, label, method, to_args) {
	const dialog = new frappe.ui.Dialog({
		title,
		fields: [{ fieldname: "error_html", fieldtype: "HTML" }, ...fields],
		primary_action_label: label,
		primary_action(values) {
			dialog.get_primary_btn().prop("disabled", true);
			tc_incident_call(
				frm,
				method,
				to_args(values),
				(html) => {
					dialog.get_primary_btn().prop("disabled", false);
					dialog.fields_dict.error_html.$wrapper.html(html);
				},
				() => dialog.hide()
			);
		},
	});
	dialog.show();
}

function tc_incident_complete_action(frm) {
	const mine = (frm.doc.actions || []).filter(
		(row) =>
			row.status !== "Done" &&
			(row.responsible === frappe.session.user || tc_incident_is_supervisor())
	);
	tc_incident_dialog(
		frm,
		__("Complete action"),
		[
			{
				fieldname: "action",
				label: __("Action"),
				fieldtype: "Select",
				options: mine.map((row) => ({ value: row.name, label: row.description })),
				reqd: 1,
			},
			{ fieldname: "result", label: __("Result"), fieldtype: "Small Text", reqd: 1 },
		],
		__("Mark as done"),
		"complete_action",
		(values) => ({ action: values.action, result: values.result })
	);
}

function tc_incident_buttons(frm) {
	if (frm.is_new() || frm.doc.docstatus !== 0) {
		return;
	}
	const status = frm.doc.status;
	const supervisor = tc_incident_is_supervisor();
	const form_error = tc_incident_form_error(frm);
	if (supervisor && status === "New") {
		frm.add_custom_button(__("Start analysis"), () =>
			tc_incident_call(frm, "advance", { step: "start_analysis" }, form_error)
		);
	}
	if (supervisor && status === "Analysis") {
		// nguyên nhân gốc và bảng hành động nhập trên form, lưu rồi mới lập CAPA
		frm.add_custom_button(__("Plan CAPA"), () =>
			frm.save().then(() => tc_incident_call(frm, "plan_capa", {}, form_error))
		);
	}
	if (status === "CAPA") {
		const open = (frm.doc.actions || []).some(
			(row) =>
				row.status !== "Done" && (row.responsible === frappe.session.user || supervisor)
		);
		if (open) {
			frm.add_custom_button(__("Complete action"), () => tc_incident_complete_action(frm));
		}
		if (supervisor) {
			frm.add_custom_button(__("Check effectiveness"), () =>
				tc_incident_call(frm, "advance", { step: "submit_verification" }, form_error)
			);
		}
	}
	if (supervisor && status === "Verification") {
		frm.add_custom_button(__("Close incident"), () =>
			tc_incident_dialog(
				frm,
				__("Close incident"),
				[
					{
						fieldname: "verification_result",
						label: __("Effectiveness Check Result"),
						fieldtype: "Small Text",
						reqd: 1,
					},
				],
				__("Close"),
				"close",
				(values) => ({ verification_result: values.verification_result })
			)
		);
	}
	if (supervisor) {
		frm.add_custom_button(
			__("Cancel incident"),
			() =>
				tc_incident_dialog(
					frm,
					__("Cancel incident"),
					[
						{
							fieldname: "reason",
							label: __("Cancellation Reason"),
							fieldtype: "Small Text",
							reqd: 1,
						},
					],
					__("Cancel incident"),
					"cancel",
					(values) => ({ reason: values.reason })
				),
			__("More")
		);
	}
}

function tc_incident_dashboard(frm) {
	frm.dashboard.clear_headline();
	if (frm.is_new()) {
		return;
	}
	const text = {
		New: __("New: waiting for R02 to start the analysis"),
		Analysis: __("Analysis: enter the root cause and the actions, then plan CAPA"),
		CAPA: __("CAPA: each responsible person records the result of their action"),
		Verification: __("Effectiveness check: R01 or R02 closes the incident"),
		Closed: __("Closed"),
		Cancelled: __("Cancelled"),
	}[frm.doc.status];
	if (text) {
		const color = { Closed: "green", Cancelled: "red" }[frm.doc.status] || "orange";
		frm.dashboard.set_headline_alert(tc_incident_escape(text), color);
	}
}

frappe.ui.form.on("Incident CAPA", {
	refresh(frm) {
		tc_incident_dashboard(frm);
		tc_incident_buttons(frm);
		// nguyên nhân gốc và hành động chỉ sửa khi đang phân tích
		const editable = frm.doc.docstatus === 0 && ["New", "Analysis"].includes(frm.doc.status);
		frm.set_df_property("root_cause", "read_only", editable ? 0 : 1);
		frm.set_df_property("actions", "read_only", editable ? 0 : 1);
	},
});
