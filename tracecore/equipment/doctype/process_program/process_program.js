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

const PROGRAM_NORM = "tracecore.v1.laundry.program_norm";
const PROGRAM_LAUNDRY_TYPES = ["Laundry Washer", "Dryer"];

function program_money(value) {
	return format_currency(value || 0, "VND", 0);
}

// Chi phí định mức của chương trình giặt/sấy theo mẻ và theo kg (#1847 DV-02, A-104); server tính, JS chỉ trình bày.
function program_norm_html(norm) {
	const esc = frappe.utils.escape_html;
	const row = (label, value) =>
		`<tr><th scope="row">${esc(label)}</th><td>${esc(value)}</td></tr>`;
	const sources = {
		"Price list": __("Approved price list"),
		Program: __("Program price"),
		"Stock valuation": __("Stock valuation"),
	};
	const chemicals = (norm.lines || [])
		.map(
			(line) => `<tr>
				<td>${esc(line.item)}</td>
				<td>${esc(format_number(line.qty, null, 3))} ${esc(line.uom || "")}</td>
				<td>${esc(program_money(line.unit_price))}</td>
				<td>${esc(program_money(line.amount))}</td>
				<td>${esc(line.price_source ? sources[line.price_source] : __("No price"))}</td>
			</tr>`
		)
		.join("");
	const missing = (norm.missing || []).length
		? `<p class="text-danger">${esc(__("No rate for: {0}", [norm.missing.join(", ")]))}</p>`
		: "";
	return `${missing}
		<p>${esc(__("Reference load: {0} kg", [format_number(norm.kg || 0, null, 3)]))}</p>
		<table class="table table-bordered">
			<thead><tr>
				<th>${esc(__("Chemical"))}</th><th>${esc(__("Quantity"))}</th><th>${esc(__("Unit Price"))}</th>
				<th>${esc(__("Amount"))}</th><th>${esc(__("Price source"))}</th>
			</tr></thead>
			<tbody>${chemicals}</tbody>
		</table>
		<table class="table table-bordered"><tbody>
			${row(__("Chemicals"), program_money(norm.chemical))}
			${row(
				__("Water ({0} L, {1} per m3)", [
					format_number(norm.water_l || 0, null, 1),
					program_money(norm.water_rate_m3),
				]),
				program_money(norm.water)
			)}
			${row(
				__("Electricity ({0} kWh)", [format_number(norm.kwh || 0, null, 2)]),
				program_money(norm.electricity)
			)}
			${row(__("Labor"), program_money(norm.labor))}
			${row(__("Norm cost per batch"), program_money(norm.total))}
			${row(__("Norm cost per kg"), program_money(norm.per_kg))}
		</tbody></table>`;
}

function program_show_norm_cost(frm) {
	const field = frm.fields_dict.norm_cost_html;
	if (!field) return;
	if (frm.is_new() || !PROGRAM_LAUNDRY_TYPES.includes(frm.doc.equipment_type)) {
		field.$wrapper.empty();
		return;
	}
	frappe.call({
		method: PROGRAM_NORM,
		args: { program: frm.doc.name },
		callback: (r) => field.$wrapper.html(program_norm_html(r.message || {})),
	});
}

// A-110 D9, FR-M5-02.5: loại bộ dùng chương trình (chỉ xem), dòng lệch phương pháp có chữ, không chỉ màu
function program_show_set_types(frm) {
	const field = frm.fields_dict.set_types_html;
	if (!field) return;
	const rows = (frm.doc.__onload && frm.doc.__onload.set_types) || [];
	if (frm.is_new() || !rows.length) {
		field.$wrapper.html(
			`<p class="text-muted">${frappe.utils.escape_html(
				__(
					"No set type uses this program yet. Add it on the set type, tab Programs by Machine."
				)
			)}</p>`
		);
		return;
	}
	const esc = frappe.utils.escape_html;
	const body = rows
		.map(
			(row) => `<tr>
				<td><a href="/app/instrument-set-type/${encodeURIComponent(row.set_type)}">${esc(
				row.set_type
			)}</a></td>
				<td>${esc(row.set_type_name || "")}</td>
				<td>${esc(__(row.method || ""))}</td>
				<td>${esc(row.is_default ? __("Default program") : __("Allowed program"))}</td>
				<td>${
					row.mismatch
						? `<span class="indicator-pill orange">${esc(
								__("Method does not match")
						  )}</span>`
						: ""
				}</td>
			</tr>`
		)
		.join("");
	field.$wrapper.html(`<table class="table table-bordered table-sm">
		<thead><tr><th>${esc(__("Set Type"))}</th><th>${esc(__("Set Type Name"))}</th><th>${esc(
		__("Method")
	)}</th><th>${esc(__("Use"))}</th><th></th></tr></thead>
		<tbody>${body}</tbody></table>`);
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
	// intro rỗng xóa cảnh báo cũ khi chương trình không còn ngoài dải
	frm.set_intro(
		frm.doc.outside_safe_range
			? __("This program has settings outside the safe range of the equipment.")
			: "",
		"orange"
	);
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

// A-111 D4, FR-M5-02.7: áp bảng vật tư sang chương trình đang dùng cùng loại chương trình, cùng loại máy
const PROGRAM_CONSUMABLE_TARGETS = "tracecore.v1.equipment_admin.consumable_targets";
const PROGRAM_COPY_CONSUMABLES = "tracecore.v1.equipment_admin.copy_consumables";

async function program_apply_consumables(frm, targets, dialog) {
	frappe.dom.freeze();
	try {
		const response = await fetch(`/api/method/${PROGRAM_COPY_CONSUMABLES}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
				"X-Frappe-CSRF-Token": frappe.csrf_token,
				"X-Idempotency-Key": program_uuid(),
			},
			body: JSON.stringify({
				program: frm.doc.name,
				targets,
				client_ts: program_client_ts(),
			}),
		});
		const body = await response.json().catch(() => ({}));
		const result = body.message || {};
		dialog.hide();
		if (result.ok) {
			frappe.show_alert({
				message: __("Consumables applied to {0} program(s).", [result.programs.length]),
				indicator: "green",
			});
		} else {
			program_show_block(
				result.error || {
					title: __("Consumables could not be applied"),
					reason: program_server_message(body),
					action: __("Check your permissions and try again."),
				}
			);
		}
	} catch (e) {
		dialog.hide();
		program_show_block({
			title: __("Consumables could not be applied"),
			reason: __("The server could not be reached."),
			action: __("Try again."),
		});
	} finally {
		frappe.dom.unfreeze();
	}
}

async function program_open_consumables_dialog(frm) {
	const r = await frappe.call({
		method: PROGRAM_CONSUMABLE_TARGETS,
		args: { program: frm.doc.name, client_ts: program_client_ts() },
	});
	const rows = (r.message && r.message.programs) || [];
	if (!rows.length) {
		frappe.msgprint(
			__("No other active program of the same kind runs on this type of machine.")
		);
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Apply consumables of {0}", [frm.doc.name]),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p>${frappe.utils.escape_html(
					__(
						"The consumables of the chosen programs are replaced by this list. Later changes here are not copied again."
					)
				)}</p>`,
			},
			{
				fieldname: "targets",
				fieldtype: "MultiCheck",
				label: __("Programs"),
				reqd: 1,
				options: rows.map((row) => ({
					label: `${row.program_name} (${row.program}) · ${
						row.equipment_name || row.equipment
					}`,
					value: row.program,
					checked: Boolean(row.suggested),
				})),
			},
		],
		primary_action_label: __("Apply"),
		primary_action(values) {
			if (!(values.targets || []).length) return;
			program_apply_consumables(frm, values.targets, dialog);
		},
	});
	dialog.show();
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
				description: __(
					"Only equipment of the same manufacturer and model that is not retired."
				),
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
		program_show_norm_cost(frm);
		program_show_set_types(frm);
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
		if ((frm.doc.consumables || []).length) {
			frm.add_custom_button(__("Apply consumables to similar programs"), () =>
				program_open_consumables_dialog(frm)
			);
		}
	},
});
