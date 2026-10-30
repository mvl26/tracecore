/* global tracecore */
// Desk: form Employee (HRMS) — nút "Đặt PIN trạm" (FR-M9-09.1, UC-33 A3), gắn qua hook doctype_js.
// R10 đặt thẳng; R02 nhập thêm PIN trạm của chính mình. PIN đặt ở đây là PIN tạm: nhân viên phải đổi ở lần quẹt thẻ kế
// tiếp. Quy tắc nằm ở server (tracecore.core.account.reset_pin_on_desk); script chỉ thu giá trị, gọi RPC và hiện lỗi
// chặn inline trong hộp thoại theo thứ tự kết quả → lý do → hành động.

const TC_SET_PIN = "tracecore.v1.account.set_station_pin";
const TC_PIN_PATTERN = /^\d{6}$/;

function tc_employee_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_employee_error_html(error) {
	const lines = [
		`<b>✕ ${tc_employee_escape(error.title)}</b>`,
		tc_employee_escape(error.reason),
		tc_employee_escape(error.action),
	];
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

function tc_employee_has_pin(frm) {
	return Boolean(frm.doc.__onload && frm.doc.__onload.tc_has_pin);
}

// Nhân viên chỉ quẹt thẻ vào trạm được khi đủ: tài khoản đăng nhập, thẻ đang bật và PIN
function tc_employee_station_intro(frm) {
	const missing = [];
	if (!frm.doc.user_id) missing.push(__("no user account linked"));
	if (!frm.doc.tc_card_id || !frm.doc.tc_card_enabled)
		missing.push(__("no active station card"));
	if (!tc_employee_has_pin(frm)) missing.push(__("no station PIN"));
	if (missing.length && frm.doc.status === "Active") {
		frm.set_intro(__("Cannot sign in at a station yet: {0}.", [missing.join(", ")]), "orange");
	} else if (frm.doc.tc_pin_reset_required) {
		frm.set_intro(
			__("The employee must change the temporary PIN at the next card scan."),
			"blue"
		);
	}
}

function tc_employee_pin_dialog(frm) {
	const r10 = frappe.user.has_role("TC R10");
	const fields = [
		{ fieldname: "error_html", fieldtype: "HTML" },
		{
			fieldname: "new_pin",
			label: __("New PIN (6 digits)"),
			fieldtype: "Password",
			reqd: 1,
		},
		{
			fieldname: "confirm_pin",
			label: __("Enter the new PIN again"),
			fieldtype: "Password",
			reqd: 1,
		},
	];
	if (!r10) {
		fields.push({
			fieldname: "supervisor_pin",
			label: __("Your station PIN"),
			fieldtype: "Password",
			reqd: 1,
			description: __("R02 confirms with their own station PIN."),
		});
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Set station PIN for {0}", [frm.doc.employee_name || frm.doc.name]),
		fields,
		primary_action_label: __("Set PIN"),
		primary_action(values) {
			const show = (error) =>
				dialog.fields_dict.error_html.$wrapper.html(tc_employee_error_html(error));
			if (!TC_PIN_PATTERN.test(values.new_pin || "")) {
				show({
					title: __("PIN is invalid"),
					reason: __("PIN must contain exactly 6 digits."),
					action: __("Enter a 6-digit PIN."),
				});
				return;
			}
			if (values.new_pin !== values.confirm_pin) {
				show({
					title: __("PINs do not match"),
					reason: __("The two PIN entries are different."),
					action: __("Enter the same 6-digit PIN twice."),
				});
				return;
			}
			const button = dialog.get_primary_btn();
			button.prop("disabled", true);
			tracecore.desk_call({
				method: TC_SET_PIN,
				args: {
					employee: frm.doc.name,
					new_pin: values.new_pin,
					supervisor_pin: values.supervisor_pin,
				},
				on_ok: () => {
					dialog.hide();
					frappe.show_alert({
						message: __(
							"Station PIN set. The employee must change it at the next card scan."
						),
						indicator: "green",
					});
					frm.reload_doc();
				},
				on_block: (error) => {
					button.prop("disabled", false);
					show(error);
				},
				on_fail: () => button.prop("disabled", false),
			});
		},
	});
	dialog.show();
}

// FEAT-036 (FR-M4-01/02, SCR-19): chứng chỉ, khám sức khỏe, tiêm chủng và thẻ QR ngay trên form nhân viên.
// Số liệu do server tính (tracecore.v1.staff.certificates); script chỉ trình bày, trạng thái luôn có chữ.
const TC_EXPIRING_DAYS = 60;

function tc_employee_date_indicator(frm, field, label) {
	const value = frm.doc[field];
	if (!value) return;
	const days = frappe.datetime.get_diff(value, frappe.datetime.get_today());
	const text = __("{0} valid until {1}", [label, frappe.datetime.str_to_user(value)]);
	if (days < 0) frm.dashboard.add_indicator(__("{0} (expired)", [text]), "red");
	else if (days <= TC_EXPIRING_DAYS) frm.dashboard.add_indicator(text, "orange");
	else frm.dashboard.add_indicator(text, "green");
}

function tc_employee_certificates(frm) {
	const name = frm.doc.name;
	if (!frappe.model.can_read("Certificate")) return;
	tracecore
		.desk_get("tracecore.v1.staff.certificates", { employee: name })
		.then((data) => {
			if (frm.doc.name !== name) return; // người dùng đã chuyển sang nhân viên khác trong lúc chờ
			const counts = data.counts;
			frm.dashboard.add_indicator(__("{0} valid certificates", [counts.valid]), "green");
			if (counts.expiring)
				frm.dashboard.add_indicator(
					__("{0} expiring within {1} days", [counts.expiring, TC_EXPIRING_DAYS]),
					"orange"
				);
			if (counts.expired)
				frm.dashboard.add_indicator(
					__("{0} expired certificates", [counts.expired]),
					"red"
				);
		})
		.catch(() => {
			// chỉ là thông tin phụ: lỗi mạng không được làm hỏng form
		});
}

function tc_employee_staff_buttons(frm) {
	if (frappe.model.can_create("Certificate"))
		frm.add_custom_button(
			__("Add certificate"),
			() => frappe.new_doc("Certificate", { employee: frm.doc.name }),
			__("Certificates")
		);
	if (frappe.model.can_read("Certificate"))
		frm.add_custom_button(
			__("View certificates"),
			() => frappe.set_route("List", "Certificate", { employee: frm.doc.name }),
			__("Certificates")
		);
	// thẻ QR in từ mã NV- (nhân viên cũ HR-EMP- chưa có mã NV- nên không có nút)
	if (frm.doc.name.startsWith("NV-") && window.tracecore && tracecore.codes)
		tracecore.codes.add_print_button(
			frm,
			"Employee Card",
			frm.doc.employee_name,
			frm.doc.department || ""
		);
}

frappe.ui.form.on("Employee", {
	refresh(frm) {
		if (frm.is_new()) return;
		tc_employee_station_intro(frm);
		tc_employee_date_indicator(frm, "tc_health_check_expiry", __("Health check"));
		tc_employee_date_indicator(frm, "tc_vaccination_expiry", __("Vaccination"));
		tc_employee_certificates(frm);
		tc_employee_staff_buttons(frm);
		if (frappe.user.has_role("TC R10") || frappe.user.has_role("TC R02")) {
			frm.add_custom_button(
				tc_employee_has_pin(frm) ? __("Reset station PIN") : __("Set station PIN"),
				() => tc_employee_pin_dialog(frm)
			);
		}
	},
});
