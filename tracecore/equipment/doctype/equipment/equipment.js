/* global tracecore */
// Desk: form Equipment (SCR-21, FEAT-038 Task 5).
// Khu cửa ra (khi còn trống) gợi ý lấy từ tracecore.v1.zone.next_zone (luồng Bẩn → Sạch → Vô khuẩn nằm ở core.zones, JS không giữ bản sao).
// "In nhãn QR": tracecore.codes.add_print_button / print_dialog (tc_codes.js, FEAT-005).
// "Ngừng sử dụng" gọi tracecore.v1.equipment_admin.retire; fetch thay frappe.call vì Frappe bỏ mất body của HTTP 404/409/422.

const EQUIPMENT_NEXT_ZONE = "tracecore.v1.zone.next_zone";
const EQUIPMENT_RETIRE = "tracecore.v1.equipment_admin.retire";
const EQUIPMENT_ADMIN_ROLES = ["TC R10", "TC R02", "System Manager"];

function equipment_uuid() {
	if (window.crypto && window.crypto.randomUUID) {
		return window.crypto.randomUUID();
	}
	return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
		const n = Math.floor(Math.random() * 16);
		return (c === "x" ? n : (n & 0x3) | 0x8).toString(16);
	});
}

// ISO 8601 có offset của máy đang dùng, ví dụ 2026-10-21T08:30:00+07:00
function equipment_client_ts() {
	const now = new Date();
	const pad = (n) => String(Math.abs(n)).padStart(2, "0");
	const offset = -now.getTimezoneOffset();
	const sign = offset >= 0 ? "+" : "-";
	const local = new Date(now.getTime() + offset * 60000).toISOString().slice(0, 19);
	return `${local}${sign}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(
		Math.abs(offset) % 60
	)}`;
}

// Chỉ báo luôn có chữ (không chỉ màu).
function equipment_indicator(frm) {
	if (frm.is_new()) {
		return;
	}
	const map = {
		Ready: ["green", __("Equipment ready")],
		Locked: ["orange", __("Equipment locked")],
		Repair: ["orange", __("Equipment under repair")],
		Retired: ["gray", __("Equipment out of service")],
	};
	const entry = map[frm.doc.status];
	if (entry) {
		frm.page.set_indicator(entry[1], entry[0]);
	}
}

function equipment_show_block(error) {
	frappe.msgprint({
		title: error.title || __("Equipment could not be retired."),
		indicator: "red",
		message: `<p>${frappe.utils.escape_html(
			error.reason || ""
		)}</p><p>${frappe.utils.escape_html(error.action || "")}</p>`,
	});
}

function equipment_server_message(body) {
	try {
		return JSON.parse(JSON.parse(body._server_messages || "[]")[0] || "{}").message || "";
	} catch (e) {
		return "";
	}
}

async function equipment_retire(frm, values, dialog) {
	frappe.dom.freeze();
	try {
		const response = await fetch(`/api/method/${EQUIPMENT_RETIRE}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
				"X-Frappe-CSRF-Token": frappe.csrf_token,
				"X-Idempotency-Key": equipment_uuid(),
			},
			body: JSON.stringify({
				equipment: frm.doc.name,
				reason: values.reason,
				client_ts: equipment_client_ts(),
			}),
		});
		const body = await response.json().catch(() => ({}));
		const result = body.message || {};
		dialog.hide();
		if (result.ok) {
			frappe.show_alert({ message: __("Equipment retired."), indicator: "green" });
			frm.reload_doc();
		} else if (result.error) {
			equipment_show_block(result.error);
		} else {
			// lỗi hệ thống (quyền, khóa idempotent…): Frappe đóng gói thông báo trong _server_messages
			equipment_show_block({
				reason: equipment_server_message(body) || __("Equipment could not be retired."),
				action: __("Check your permissions and try again."),
			});
		}
	} catch (e) {
		dialog.hide();
		equipment_show_block({
			reason: __("The server could not be reached."),
			action: __("Try again."),
		});
	} finally {
		frappe.dom.unfreeze();
	}
}

function equipment_open_retire_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Retire equipment {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason for retiring"),
				description: __(
					"Retiring is permanent: the equipment can no longer be used or get new programs."
				),
				reqd: 1,
			},
		],
		primary_action_label: __("Retire equipment"),
		primary_action(values) {
			equipment_retire(frm, values, dialog);
		},
	});
	dialog.show();
}

// Nút "In nhãn QR" (FEAT-005, hàm dùng chung ở tc_codes.js): thiết bị Retired không in được (A-05 R4) → không có nút,
// kèm dòng giải thích; mã Disabled do tracecore.codes.add_print_button tra sổ mã.
function equipment_print_button(frm) {
	if (!(window.tracecore && tracecore.codes)) {
		return; // tc_codes.js (bundle Desk) chưa nạp: form vẫn dùng được, chỉ thiếu nút in
	}
	const retired =
		frm.doc.status === "Retired"
			? __(
					"QR label not available: equipment {0} is retired; its history can still be looked up.",
					[frm.doc.name]
			  )
			: null;
	tracecore.codes.add_print_button(
		frm,
		"Equipment",
		frm.doc.equipment_name,
		__(frm.doc.equipment_type, null, "Equipment"),
		retired
	);
}

const EQUIPMENT_USAGE = "tracecore.v1.laundry.machine_usage";
const EQUIPMENT_LAUNDRY_TYPES = ["Laundry Washer", "Dryer"];

function equipment_number(value, digits) {
	return format_number(value || 0, null, digits);
}

function equipment_table(headers, rows) {
	const esc = frappe.utils.escape_html;
	const head = headers.map((text) => `<th>${esc(text)}</th>`).join("");
	const body = rows
		.map((cells) => `<tr>${cells.map((cell) => `<td>${esc(cell)}</td>`).join("")}</tr>`)
		.join("");
	return `<table class="table table-bordered"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

// Khối Sử dụng của máy giặt, máy sấy (#1847 DV-04): server tổng hợp, JS chỉ trình bày.
function equipment_usage_html(usage) {
	const esc = frappe.utils.escape_html;
	const money = (value) => format_currency(value || 0, "VND", 0);
	if (!(usage.history || []).length) {
		return `<p>${esc(__("No batch in this period."))}</p>`;
	}
	const total = usage.totals;
	const days = equipment_table(
		[
			__("Date"),
			__("Program"),
			__("Batches"),
			__("Weight (kg)"),
			__("Water actual (m3)"),
			__("Power actual (kWh)"),
			__("Actual cost"),
		],
		usage.days
			.map((row) => [
				frappe.datetime.str_to_user(row.date),
				row.program || "-",
				row.batches,
				equipment_number(row.weight_kg, 2),
				equipment_number(row.water_actual_m3, 3),
				equipment_number(row.power_actual, 2),
				money(row.cost_actual),
			])
			.concat([
				[
					__("Total"),
					"",
					total.batches,
					equipment_number(total.weight_kg, 2),
					equipment_number(total.water_actual_m3, 3),
					equipment_number(total.power_actual, 2),
					money(total.cost_actual),
				],
			])
	);
	const chemicals = equipment_table(
		[__("Chemical"), __("Norm Quantity"), __("Actual Quantity"), __("Amount")],
		usage.chemicals.map((row) => [
			row.item,
			`${equipment_number(row.norm, 3)} ${row.uom || ""}`,
			`${equipment_number(row.actual, 3)} ${row.uom || ""}`,
			money(row.amount),
		])
	);
	const history = equipment_table(
		[
			__("Laundry Batch"),
			__("Ended At"),
			__("Program"),
			__("Weight (kg)"),
			__("Total Cost"),
			__("Cost per kg"),
		],
		usage.history.map((row) => [
			row.name,
			frappe.datetime.str_to_user(row.ended_at),
			row.program,
			equipment_number(row.weight_kg, 2),
			money(row.cost_total),
			money(row.cost_per_kg),
		])
	);
	return `<h5>${esc(__("Use per day"))}</h5>${days}
		<h5>${esc(__("Chemicals used"))}</h5>${chemicals}
		<h5>${esc(__("Batch history"))}</h5>${history}`;
}

function equipment_show_usage(frm) {
	const field = frm.fields_dict.laundry_usage_html;
	if (!field) return;
	field.$wrapper.empty();
	if (
		frm.is_new() ||
		!EQUIPMENT_LAUNDRY_TYPES.includes(frm.doc.equipment_type) ||
		!frappe.model.can_read("Laundry Batch")
	) {
		return;
	}
	const filters = $(`<div class="row"></div>`).appendTo(field.$wrapper);
	const result = $("<div></div>").appendTo(field.$wrapper);
	const today = frappe.datetime.get_today();
	const dates = {};
	const load = () =>
		frappe.call({
			method: EQUIPMENT_USAGE,
			args: {
				equipment: frm.doc.name,
				from_date: dates.from.get_value() || today,
				to_date: dates.to.get_value() || today,
			},
			callback: (r) => result.html(equipment_usage_html(r.message || {})),
		});
	for (const [key, label] of [
		["from", __("From Date")],
		["to", __("To Date")],
	]) {
		const parent = $(`<div class="col-sm-4"></div>`).appendTo(filters);
		dates[key] = frappe.ui.form.make_control({
			parent,
			df: { fieldtype: "Date", label, fieldname: `usage_${key}`, onchange: load },
			render_input: true,
		});
		dates[key].set_value(today);
	}
	load();
}

frappe.ui.form.on("Equipment", {
	setup(frm) {
		frm.set_query("default_program", () => ({
			filters: { equipment: frm.doc.name, is_active: 1, program_kind: "Regular" },
		}));
		frm.set_query("zone_in", () => ({ filters: { is_zone: 1 } }));
		frm.set_query("zone_out", () => ({ filters: { is_zone: 1 } }));
	},

	refresh(frm) {
		equipment_indicator(frm);
		equipment_show_usage(frm);
		if (
			!frm.is_new() &&
			frm.doc.status === "Ready" &&
			frappe.user.has_role(EQUIPMENT_ADMIN_ROLES)
		) {
			frm.add_custom_button(__("Retire equipment"), () => equipment_open_retire_dialog(frm));
		}
		// SCR-22 (FEAT-039): ghi sự cố hoặc lập kế hoạch bảo trì cho máy này
		if (
			!frm.is_new() &&
			frm.doc.status !== "Retired" &&
			frappe.user.has_role(EQUIPMENT_ADMIN_ROLES)
		) {
			frm.add_custom_button(
				__("Record incident"),
				() =>
					frappe.new_doc("Maintenance Record", {
						equipment: frm.doc.name,
						record_type: "Incident",
					}),
				__("Maintenance")
			);
			frm.add_custom_button(
				__("Plan maintenance"),
				() =>
					frappe.new_doc("Maintenance Record", {
						equipment: frm.doc.name,
						record_type: "Preventive",
					}),
				__("Maintenance")
			);
		}
		equipment_print_button(frm);
	},

	zone_in(frm) {
		const zone = frm.doc.zone_in;
		// chỉ gợi ý khi khu cửa ra còn trống: không bao giờ ghi đè giá trị người dùng đã đặt
		if (!zone || frm.doc.zone_out) {
			return;
		}
		frappe.call({
			method: EQUIPMENT_NEXT_ZONE,
			args: { zone },
			callback(r) {
				if (frm.doc.zone_in !== zone || frm.doc.zone_out) {
					return; // người dùng đã đổi khu cửa vào hoặc tự đặt khu cửa ra trong lúc chờ
				}
				// khu cuối hoặc không phải khu: không gợi ý, để trống = máy một cửa
				if (r.message) {
					frm.set_value("zone_out", r.message);
				}
			},
		});
	},
});
