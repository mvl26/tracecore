// Desk: duyệt hoặc từ chối đề nghị ghi đè cơ số (SCR-31, FEAT-032; UC-31, FR-M8-04, WF-08).
// Quy tắc nằm ở server (tracecore.par.override): chỉ R01 hoặc R02 được ủy quyền duyệt, lý do bắt buộc, số chu trình
// thêm ≥ 1, thời hạn từ hôm nay, PIN của người duyệt. JS chỉ hiện nút, thu thập giá trị và đưa lỗi chặn về dạng
// kết quả → lý do → hành động ngay trong hộp thoại (không dùng thông báo nổi cho lỗi chặn).

const TC_PAR_OVERRIDE_DECIDERS = ["TC R01", "TC R02"];
const TC_PAR_OVERRIDE_DEFAULT_DAYS = 7;
const TC_PAR_OVERRIDE_APPROVE = "tracecore.v1.par.override.approve";
const TC_PAR_OVERRIDE_REJECT = "tracecore.v1.par.override.reject";

function tc_par_override_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

// chỉ người có role R01/R02 thấy nút; server vẫn kiểm R02 có được ủy quyền hay không
function tc_par_override_can_decide(frm) {
	return (
		frm.doc.docstatus === 0 &&
		frm.doc.status === "Requested" &&
		!frm.is_new() &&
		TC_PAR_OVERRIDE_DECIDERS.some((role) => frappe.user.has_role(role))
	);
}

// lỗi chặn: kết quả (đậm) → lý do → hành động, màu đỏ toàn khối
function tc_par_override_error_html(error) {
	const lines = [
		`<b>✕ ${tc_par_override_escape(error.title)}</b>`,
		tc_par_override_escape(error.reason),
		tc_par_override_escape(error.action),
	];
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

function tc_par_override_decide(frm, approve) {
	const fields = [{ fieldname: "error_html", fieldtype: "HTML" }];
	if (approve) {
		fields.push(
			{
				fieldname: "extra_cycles",
				label: __("Extra Cycles"),
				fieldtype: "Int",
				default: 1,
				reqd: 1,
			},
			{
				fieldname: "valid_until",
				label: __("Valid Until"),
				fieldtype: "Date",
				default: frappe.datetime.add_days(
					frappe.datetime.get_today(),
					TC_PAR_OVERRIDE_DEFAULT_DAYS
				),
				reqd: 1,
			}
		);
	}
	fields.push(
		{
			fieldname: "reason",
			label: __("Reason for Decision"),
			fieldtype: "Small Text",
			reqd: 1,
		},
		{ fieldname: "pin", label: __("PIN"), fieldtype: "Password", reqd: 1 }
	);
	const dialog = new frappe.ui.Dialog({
		title: approve ? __("Approve override") : __("Reject override"),
		fields,
		primary_action_label: approve ? __("Approve") : __("Reject"),
		primary_action(values) {
			const args = approve
				? {
						override: frm.doc.name,
						extra_cycles: values.extra_cycles,
						valid_until: values.valid_until,
						reason: values.reason,
						pin: values.pin,
				  }
				: { override: frm.doc.name, reason: values.reason, pin: values.pin };
			dialog.get_primary_btn().prop("disabled", true);
			frappe.call({
				method: approve ? TC_PAR_OVERRIDE_APPROVE : TC_PAR_OVERRIDE_REJECT,
				args,
				callback: (response) => {
					const result = response.message || {};
					dialog.get_primary_btn().prop("disabled", false);
					dialog.set_value("pin", "");
					if (result.ok === false) {
						dialog.fields_dict.error_html.$wrapper.html(
							tc_par_override_error_html(result.error)
						);
						return;
					}
					dialog.hide();
					frm.reload_doc();
				},
				error: () => dialog.get_primary_btn().prop("disabled", false),
			});
		},
	});
	dialog.show();
}

function tc_par_override_dashboard(frm) {
	frm.dashboard.clear_headline();
	if (frm.is_new()) {
		return;
	}
	const text = {
		Requested: __("Waiting for R01 to decide"),
		Approved: __("Approved: the set may be packed within the extra cycles and date"),
		Rejected: __("Rejected: the set stays at the end of its life"),
		Expired: __("Expired: the set is blocked again"),
		Cancelled: __("Cancelled: the set is blocked again"),
	}[frm.doc.status];
	if (text) {
		const color = { Requested: "orange", Approved: "green" }[frm.doc.status] || "red";
		frm.dashboard.set_headline_alert(tc_par_override_escape(text), color);
	}
}

frappe.ui.form.on("Par Override", {
	refresh(frm) {
		tc_par_override_dashboard(frm);
		if (tc_par_override_can_decide(frm)) {
			frm.add_custom_button(__("Approve"), () => tc_par_override_decide(frm, true));
			frm.add_custom_button(__("Reject"), () => tc_par_override_decide(frm, false));
		}
	},
});
