// Desk: form Printer — nạp cuộn nhãn (SCR-33, FEAT-002 Task 5, ruling P1).
// Gọi tracecore.v1.printer.set_roll kèm `printer` (đường Desk của R10). Desk không phải màn trạm nên kết quả và lỗi
// hiện bằng frappe.msgprint (tiêu đề / lý do / hành động).

const PRINTER_SET_ROLL = "tracecore.v1.printer.set_roll";

function printer_uuid() {
	if (window.crypto && window.crypto.randomUUID) {
		return window.crypto.randomUUID();
	}
	return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
		const n = Math.floor(Math.random() * 16);
		return (c === "x" ? n : (n & 0x3) | 0x8).toString(16);
	});
}

// ISO 8601 có offset của máy đang dùng, ví dụ 2026-10-20T08:30:00+07:00
function printer_client_ts() {
	const now = new Date();
	const pad = (n) => String(Math.abs(n)).padStart(2, "0");
	const offset = -now.getTimezoneOffset();
	const sign = offset >= 0 ? "+" : "-";
	const local = new Date(now.getTime() + offset * 60000).toISOString().slice(0, 19);
	return `${local}${sign}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(
		Math.abs(offset) % 60
	)}`;
}

function printer_show_block(error) {
	frappe.msgprint({
		title: error.title || __("Roll could not be loaded"),
		indicator: "red",
		message: `<p>${frappe.utils.escape_html(
			error.reason || ""
		)}</p><p>${frappe.utils.escape_html(error.action || "")}</p>`,
	});
}

function printer_show_result(frm, roll) {
	const released = (roll.released_jobs || []).length;
	const failed = roll.failed_jobs || [];
	const rows = [
		[__("Printer"), roll.printer],
		[__("Label type"), roll.label_type],
		[__("Waiting labels released"), released],
		[__("Waiting labels with errors"), failed.length],
	];
	const table = rows
		.map(
			([label, value]) =>
				`<tr><td>${frappe.utils.escape_html(label)}</td><td>${frappe.utils.escape_html(
					String(value)
				)}</td></tr>`
		)
		.join("");
	const errors = failed
		.map((job) => `<li>${frappe.utils.escape_html(`${job.print_job}: ${job.error}`)}</li>`)
		.join("");
	frappe.msgprint({
		title: __("Label roll loaded"),
		indicator: failed.length ? "orange" : "green",
		message: `<table class="table table-bordered"><tbody>${table}</tbody></table>${
			errors ? `<ul>${errors}</ul>` : ""
		}`,
	});
	frm.reload_doc();
}

// fetch thay frappe.call: Frappe tự hiện "Không tìm thấy" cho HTTP 404 và bỏ mất body, trong khi ROLL_NOT_FOUND (404),
// ROLL_PRINTER_AMBIGUOUS (409), ROLL_NOT_LABEL (422) đều mang body {message: {ok: false, error}} cần hiện cho người dùng.
async function printer_set_roll(frm, values, dialog) {
	frappe.dom.freeze();
	try {
		const response = await fetch(`/api/method/${PRINTER_SET_ROLL}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
				"X-Frappe-CSRF-Token": frappe.csrf_token,
				"X-Idempotency-Key": printer_uuid(),
			},
			body: JSON.stringify({
				roll_code: values.roll_code,
				station: frm.doc.station,
				printer: frm.doc.name,
				client_ts: printer_client_ts(),
			}),
		});
		const body = await response.json().catch(() => ({}));
		const result = body.message || {};
		dialog.hide();
		if (result.ok) {
			printer_show_result(frm, result.roll);
		} else if (result.error) {
			printer_show_block(result.error);
		} else {
			// lỗi hệ thống (quyền, kiểm tra tham số…): Frappe đã đóng gói thông báo trong _server_messages
			printer_show_server_error(body);
		}
	} catch (e) {
		dialog.hide();
		printer_show_block({
			reason: __("The server could not be reached."),
			action: __("Try again."),
		});
	} finally {
		frappe.dom.unfreeze();
	}
}

function printer_show_server_error(body) {
	let reason = "";
	try {
		reason = JSON.parse(JSON.parse(body._server_messages || "[]")[0] || "{}").message || "";
	} catch (e) {
		reason = "";
	}
	printer_show_block({
		reason: reason || __("The roll could not be loaded."),
		action: __("Check the roll code and your permissions, then try again."),
	});
}

function printer_open_roll_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Load label roll"),
		fields: [
			{
				fieldname: "roll_code",
				fieldtype: "Data",
				label: __("Roll code"),
				description: __("Scan or type the roll code CN-#####."),
				reqd: 1,
			},
			{
				fieldname: "confirmed",
				fieldtype: "Check",
				label: __("I have loaded this roll into the printer"),
			},
		],
		primary_action_label: __("Load roll"),
		primary_action(values) {
			if (!values.confirmed) {
				frappe.msgprint({
					title: __("Confirmation needed"),
					indicator: "orange",
					message: __("Tick the confirmation after the roll is in the printer."),
				});
				return;
			}
			printer_set_roll(frm, values, dialog);
		},
	});
	dialog.show();
}

frappe.ui.form.on("Printer", {
	setup(frm) {
		frm.set_query("station", () => ({ filters: { is_zone: 0 } }));
		frm.set_query("label_type_loaded", () => ({
			filters: { tc_item_group_cssd: "Label", tc_compatible_method: ["is", "set"] },
		}));
	},

	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("Load label roll"), () => printer_open_roll_dialog(frm));
	},
});
