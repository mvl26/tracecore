/* global tracecore */
// Desk FEAT-004 (A-37 a, b): hộp thoại thanh lý bộ (R02 đề nghị, R01 duyệt/từ chối bằng PIN) và chuyển trạng thái thủ
// công khi hệ thống lỗi (R02, lý do + ticket), dùng ở form Set Unit và form Pack. Quy tắc nằm ở server
// (tracecore.instrument.disposal, tracecore.reprocessing.manual_transition): JS chỉ thu thập giá trị, gọi RPC và hiện
// lỗi chặn inline trong hộp thoại theo thứ tự kết quả → lý do → hành động. Danh sách trạng thái lấy từ options của
// trường status, server kiểm đích hợp lệ.

frappe.provide("tracecore.admin");

const TC_ADMIN_DISPOSAL = "tracecore.v1.set_unit.disposal_";
const TC_ADMIN_FORCE = "tracecore.v1.admin.force_transition";

function tc_admin_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_admin_error_html(error) {
	const lines = [
		`<b>✕ ${tc_admin_escape(error.title)}</b>`,
		tc_admin_escape(error.reason),
		tc_admin_escape(error.action),
	];
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

// gọi RPC từ hộp thoại: lỗi chặn hiện trong hộp thoại, thành công đóng hộp thoại và tải lại form
function tc_admin_submit(dialog, frm, method, args) {
	const button = dialog.get_primary_btn();
	button.prop("disabled", true);
	frappe.call({
		method,
		args,
		callback: (response) => {
			const result = response.message || {};
			button.prop("disabled", false);
			if (result.ok === false) {
				dialog.fields_dict.error_html.$wrapper.html(tc_admin_error_html(result.error));
				return;
			}
			dialog.hide();
			frm.reload_doc();
		},
		error: () => button.prop("disabled", false),
	});
}

tracecore.admin.request_disposal = function (frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Request disposal"),
		fields: [
			{ fieldname: "error_html", fieldtype: "HTML" },
			{
				fieldname: "reason",
				label: __("Disposal Reason"),
				fieldtype: "Small Text",
				reqd: 1,
			},
		],
		primary_action_label: __("Request disposal"),
		primary_action(values) {
			tc_admin_submit(dialog, frm, TC_ADMIN_DISPOSAL + "request", {
				set_unit: frm.doc.name,
				reason: values.reason,
			});
		},
	});
	dialog.show();
};

tracecore.admin.decide_disposal = function (frm, approve) {
	const dialog = new frappe.ui.Dialog({
		title: approve ? __("Approve disposal") : __("Reject disposal"),
		fields: [
			{ fieldname: "error_html", fieldtype: "HTML" },
			{
				fieldname: "request_html",
				fieldtype: "HTML",
				options: `<p>${tc_admin_escape(__("Disposal Reason"))}: ${tc_admin_escape(
					frm.doc.disposal_reason
				)}</p>`,
			},
			{
				fieldname: "note",
				label: __("Disposal Decision Note"),
				fieldtype: "Small Text",
				reqd: 1,
			},
			{ fieldname: "pin", label: __("PIN"), fieldtype: "Password", reqd: 1 },
		],
		primary_action_label: approve ? __("Approve disposal") : __("Reject disposal"),
		primary_action(values) {
			tc_admin_submit(dialog, frm, TC_ADMIN_DISPOSAL + (approve ? "approve" : "reject"), {
				set_unit: frm.doc.name,
				note: values.note,
				pin: values.pin,
			});
		},
	});
	dialog.show();
};

tracecore.admin.force_transition = function (frm) {
	const statuses = String(frm.fields_dict.status.df.options || "")
		.split("\n")
		.filter((status) => status && status !== frm.doc.status);
	const fields = [
		{ fieldname: "error_html", fieldtype: "HTML" },
		{
			fieldname: "status",
			label: __("Status after change"),
			fieldtype: "Select",
			options: statuses.map((status) => ({
				value: status,
				label: __(status, null, frm.doctype),
			})),
			reqd: 1,
		},
	];
	if (frm.fields_dict.void_reason) {
		const reasons = String(frm.fields_dict.void_reason.df.options || "")
			.split("\n")
			.filter(Boolean);
		fields.push({
			fieldname: "void_reason",
			label: __("Void Reason"),
			fieldtype: "Select",
			options: [
				"",
				...reasons.map((reason) => ({ value: reason, label: __(reason, null, "Pack") })),
			],
			depends_on: "eval:doc.status === 'Void'",
		});
	}
	fields.push(
		{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 },
		{ fieldname: "ticket", label: __("Incident Ticket"), fieldtype: "Data", reqd: 1 }
	);
	const dialog = new frappe.ui.Dialog({
		title: __("Change status by hand"),
		fields,
		primary_action_label: __("Change status by hand"),
		primary_action(values) {
			tc_admin_submit(dialog, frm, TC_ADMIN_FORCE, {
				doctype: frm.doctype,
				name: frm.doc.name,
				status: values.status,
				reason: values.reason,
				ticket: values.ticket,
				void_reason: values.void_reason || null,
			});
		},
	});
	dialog.show();
};
