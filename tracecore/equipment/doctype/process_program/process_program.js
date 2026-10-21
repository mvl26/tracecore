// Desk: form Process Program (SCR-21, FEAT-038 Task 5).
// Chỉ báo định mức luôn có chữ; cảnh báo cam khi ngoài dải an toàn của máy. "Sao chép sang máy khác" gọi
// tracecore.v1.equipment_admin.copy_program; fetch thay frappe.call vì Frappe bỏ mất body của HTTP 404/409/422.

const PROGRAM_COPY = "tracecore.v1.equipment_admin.copy_program";
const PROGRAM_ADMIN_ROLES = ["TC R10", "TC R02", "System Manager"];

function program_uuid() {
	if (window.crypto && window.crypto.randomUUID) {
		return window.crypto.randomUUID();
	}
	return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
		const n = Math.floor(Math.random() * 16);
		return (c === "x" ? n : (n & 0x3) | 0x8).toString(16);
	});
}

// ISO 8601 có offset của máy đang dùng, ví dụ 2026-10-21T08:30:00+07:00
function program_client_ts() {
	const now = new Date();
	const pad = (n) => String(Math.abs(n)).padStart(2, "0");
	const offset = -now.getTimezoneOffset();
	const sign = offset >= 0 ? "+" : "-";
	const local = new Date(now.getTime() + offset * 60000).toISOString().slice(0, 19);
	return `${local}${sign}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(
		Math.abs(offset) % 60
	)}`;
}

function program_indicator(frm) {
	if (frm.is_new()) {
		return;
	}
	const map = {
		Complete: ["green", __("Norms complete")],
		Default: ["orange", __("Default norms")],
		Missing: ["red", __("Norms missing")],
	};
	const entry = map[frm.doc.norm_status];
	if (entry) {
		frm.page.set_indicator(entry[1], entry[0]);
	}
	if (frm.doc.outside_safe_range) {
		frm.set_intro(
			__("This program has settings outside the safe range of the equipment."),
			"orange"
		);
	}
}

function program_show_block(error) {
	frappe.msgprint({
		title: error.title || __("Program could not be copied"),
		indicator: "red",
		message: `<p>${frappe.utils.escape_html(
			error.reason || ""
		)}</p><p>${frappe.utils.escape_html(error.action || "")}</p>`,
	});
}

function program_server_message(body) {
	try {
		return JSON.parse(JSON.parse(body._server_messages || "[]")[0] || "{}").message || "";
	} catch (e) {
		return "";
	}
}

async function program_copy(frm, values, dialog) {
	frappe.dom.freeze();
	try {
		const response = await fetch(`/api/method/${PROGRAM_COPY}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
				"X-Frappe-CSRF-Token": frappe.csrf_token,
				"X-Idempotency-Key": program_uuid(),
			},
			body: JSON.stringify({
				program: frm.doc.name,
				equipment: values.target_equipment,
				new_code: values.new_code,
				client_ts: program_client_ts(),
			}),
		});
		const body = await response.json().catch(() => ({}));
		const result = body.message || {};
		dialog.hide();
		if (result.ok) {
			frappe.show_alert({
				message: __("Program copied to {0}.", [result.program]),
				indicator: "green",
			});
			frappe.set_route("Form", "Process Program", result.program);
		} else if (result.error) {
			program_show_block(result.error);
		} else {
			program_show_block({
				reason: program_server_message(body) || __("Program could not be copied"),
				action: __("Check your permissions and try again."),
			});
		}
	} catch (e) {
		dialog.hide();
		program_show_block({
			reason: __("The server could not be reached."),
			action: __("Try again."),
		});
	} finally {
		frappe.dom.unfreeze();
	}
}

function program_open_copy_dialog(frm, source) {
	const dialog = new frappe.ui.Dialog({
		title: __("Copy program {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "target_equipment",
				fieldtype: "Link",
				options: "Equipment",
				label: __("Target equipment"),
				description: __("Only equipment of the same manufacturer and model that is not retired."),
				reqd: 1,
				get_query: () => ({
					filters: {
						manufacturer: source.manufacturer,
						model: source.model,
						status: ["!=", "Retired"],
						name: ["!=", frm.doc.equipment],
					},
				}),
			},
			{
				fieldname: "new_code",
				fieldtype: "Data",
				label: __("New program code"),
				description: __("Uppercase letters, digits and hyphens only."),
				reqd: 1,
			},
		],
		primary_action_label: __("Copy"),
		primary_action(values) {
			program_copy(frm, values, dialog);
		},
	});
	dialog.show();
}

frappe.ui.form.on("Process Program", {
	setup(frm) {
		frm.set_query("equipment", () => ({ filters: { status: ["!=", "Retired"] } }));
	},

	refresh(frm) {
		program_indicator(frm);
		if (frm.is_new() || !frm.doc.equipment || !frappe.user.has_role(PROGRAM_ADMIN_ROLES)) {
			return;
		}
		frm.add_custom_button(__("Copy to another equipment"), async () => {
			const source = await frappe.db.get_value("Equipment", frm.doc.equipment, [
				"manufacturer",
				"model",
			]);
			program_open_copy_dialog(frm, source.message || {});
		});
	},
});
