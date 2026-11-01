// Desk: form Laundry Batch. Nút "Retry consumption" cho R09/R02 khi tiêu hao tự động bị lỗi (thông báo CONSUMPTION_FAILED trỏ về
// đây, A-78). Chỉ trình bày: server (tracecore.v1.stock.retry_consumption) quyết định và không trừ kho hai lần.

const LAUNDRY_NORM_PREVIEW = "tracecore.v1.laundry.norm_preview";
const LAUNDRY_COMPLETE_DESK = "tracecore.v1.laundry.complete_desk";
const LAUNDRY_ROLES = ["TC R07", "TC R02", "System Manager"];

function laundry_uuid() {
	if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
	return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
		const n = Math.floor(Math.random() * 16);
		return (c === "x" ? n : (n & 0x3) | 0x8).toString(16);
	});
}

// Chi phí định mức của lô đang lập (A-104): server tính, JS chỉ trình bày.
function laundry_show_preview(frm) {
	const field = frm.fields_dict.norm_preview_html;
	if (!field) return;
	if (frm.doc.docstatus !== 0 || !frm.doc.program) {
		field.$wrapper.empty();
		return;
	}
	frappe.call({
		method: LAUNDRY_NORM_PREVIEW,
		args: {
			program: frm.doc.program,
			dry_program: frm.doc.dry_program || null,
			kg: frm.doc.weight_kg || 0,
		},
		callback: (r) => {
			const norm = r.message || {};
			const esc = frappe.utils.escape_html;
			const money = (value) => format_currency(value || 0, "VND", 0);
			const missing = (norm.missing || []).length
				? `<p class="text-danger">${esc(
						__("No rate for: {0}", [norm.missing.join(", ")])
				  )}</p>`
				: "";
			field.$wrapper.html(
				`${missing}<p>${esc(__("Norm cost per batch"))}: <strong>${esc(
					money(norm.total)
				)}</strong> &middot; ${esc(__("Norm cost per kg"))}: <strong>${esc(
					money(norm.per_kg)
				)}</strong></p>`
			);
		},
	});
}

// Chọn máy, chương trình, kg: server điền hóa chất, nước, điện theo định mức vào form chưa lưu (FR-M3-09).
function laundry_refresh_norm(frm) {
	if (frm.doc.docstatus !== 0 || !frm.doc.program) return laundry_show_preview(frm);
	return frm.call({ doc: frm.doc, method: "refresh_norm" }).then(() => {
		frm.refresh_fields();
		laundry_show_preview(frm);
	});
}

function laundry_show_block(error) {
	frappe.msgprint({
		title: error.title || __("The batch cannot be completed yet"),
		indicator: "red",
		message: `<p>${frappe.utils.escape_html(
			error.reason || ""
		)}</p><p>${frappe.utils.escape_html(error.action || "")}</p>`,
	});
}

async function laundry_complete(frm, values, dialog) {
	frappe.dom.freeze();
	try {
		const response = await fetch(`/api/method/${LAUNDRY_COMPLETE_DESK}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Accept: "application/json",
				"X-Frappe-CSRF-Token": frappe.csrf_token,
				"X-Idempotency-Key": laundry_uuid(),
			},
			body: JSON.stringify({
				batch: frm.doc.name,
				dryer: values.dryer,
				dry_program: values.dry_program || null,
				dry_temp_c: values.dry_temp_c || null,
				dry_minutes: values.dry_minutes || null,
				clean_ok: values.clean_ok === "Pass" ? 1 : 0,
				dry_ok: values.dry_ok === "Pass" ? 1 : 0,
				note: values.note || null,
				deviation_reason: values.deviation_reason || null,
				client_ts: moment().format(),
			}),
		});
		const body = await response.json().catch(() => ({}));
		const result = body.message || {};
		if (result.ok) {
			dialog.hide();
			frappe.show_alert({
				message: __("Batch {0} completed", [frm.doc.name]),
				indicator: "green",
			});
			frm.reload_doc();
		} else {
			laundry_show_block(
				result.error || { reason: __("Check your permissions and try again.") }
			);
		}
	} catch (e) {
		laundry_show_block({
			reason: __("The server could not be reached."),
			action: __("Try again."),
		});
	} finally {
		frappe.dom.unfreeze();
	}
}

function laundry_open_complete(frm) {
	const results = ["", "Pass", "Fail"].map((value) => ({
		value,
		label: value ? __(value) : __("Choose"),
	}));
	const dialog = new frappe.ui.Dialog({
		title: __("Complete the batch"),
		fields: [
			{
				fieldname: "dryer",
				fieldtype: "Link",
				options: "Equipment",
				label: __("Dryer"),
				reqd: 1,
				default: frm.doc.dryer,
				get_query: () => ({ filters: { equipment_type: "Dryer", status: "Ready" } }),
			},
			{
				fieldname: "dry_program",
				fieldtype: "Link",
				options: "Process Program",
				label: __("Dry Program"),
				default: frm.doc.dry_program,
				get_query: () => ({
					filters: { equipment: dialog.get_value("dryer"), is_active: 1 },
				}),
			},
			{
				fieldname: "dry_temp_c",
				fieldtype: "Int",
				label: __("Dry Temperature (C)"),
				description: __("Empty takes the value of the dry program."),
			},
			{
				fieldname: "dry_minutes",
				fieldtype: "Int",
				label: __("Dry Time (min)"),
				description: __("Empty takes the value of the dry program."),
			},
			{
				fieldname: "clean_ok",
				fieldtype: "Select",
				label: __("Clean"),
				options: results,
				reqd: 1,
			},
			{
				fieldname: "dry_ok",
				fieldtype: "Select",
				label: __("Dry"),
				options: results,
				reqd: 1,
			},
			{
				fieldname: "deviation_reason",
				fieldtype: "Small Text",
				label: __("Deviation Reason"),
				default: frm.doc.deviation_reason,
			},
			{ fieldname: "note", fieldtype: "Small Text", label: __("Note", null, "Station") },
		],
		primary_action_label: __("Complete batch"),
		primary_action(values) {
			laundry_complete(frm, values, dialog);
		},
	});
	dialog.show();
}

frappe.ui.form.on("Laundry Batch", {
	setup(frm) {
		frm.set_query("equipment", () => ({
			filters: { equipment_type: "Laundry Washer", status: "Ready" },
		}));
		frm.set_query("dryer", () => ({ filters: { equipment_type: "Dryer", status: "Ready" } }));
		frm.set_query("program", () => ({
			filters: { equipment: frm.doc.equipment || "", is_active: 1 },
		}));
		frm.set_query("dry_program", () => ({
			filters: { equipment: frm.doc.dryer || "", is_active: 1 },
		}));
	},
	program: laundry_refresh_norm,
	dry_program: laundry_refresh_norm,
	weight_kg: laundry_refresh_norm,
	equipment(frm) {
		frm.set_value("program", null);
	},
	dryer(frm) {
		frm.set_value("dry_program", null);
	},
	refresh(frm) {
		laundry_show_preview(frm);
		if (
			!frm.is_new() &&
			frm.doc.docstatus === 0 &&
			frm.doc.status === "Running" &&
			frappe.user.has_role(LAUNDRY_ROLES)
		) {
			frm.add_custom_button(__("Complete batch"), () => {
				if (frm.is_dirty()) {
					frm.save().then(() => laundry_open_complete(frm));
				} else {
					laundry_open_complete(frm);
				}
			});
		}
		const roles = frappe.user_roles || [];
		const allowed = ["TC R09", "TC R02", "System Manager"].some((role) =>
			roles.includes(role)
		);
		if (!allowed || frm.doc.docstatus !== 1 || frm.doc.batch_type === "Outsourced") return;
		frm.add_custom_button(__("Retry consumption"), () => {
			frappe.call({
				method: "tracecore.v1.stock.retry_consumption",
				args: { source_doctype: "Laundry Batch", source_name: frm.doc.name },
				freeze: true,
				callback: (r) => {
					const res = r.message || {};
					frappe.show_alert({
						message: res.created
							? __("Supplies were issued: {0}", [res.entry])
							: __("This batch already has an issue: nothing more was deducted."),
						indicator: "green",
					});
				},
			});
		});
	},
});
