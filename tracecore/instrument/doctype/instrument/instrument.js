/* global tracecore */
// Desk: form Instrument (SCR-01, FEAT-014 Task 6; UC-01, FR-M1-01/02/09).
// Dữ liệu và quy tắc nằm ở server: tracecore.v1.instrument.form_context (ngưỡng hiệu lực, bộ đếm có trạng thái D5,
// loại bộ dùng dụng cụ, lịch sử phiên bản, quyền của người dùng) và check_code (chuẩn hóa + mã gợi ý). JS không giữ
// danh sách phương pháp hay ngưỡng D5; nhãn phương pháp lấy từ meta (Select của Instrument Compatible Method).
// Thao tác ghi (ngừng sử dụng, khởi tạo bộ đếm, cấp mã GIAI, ghi nhận khắc) gửi bằng tracecore.codes.send của
// tc_codes.js: fetch thay frappe.call vì Frappe bỏ mất body của HTTP 404/409/422; mỗi thao tác một khóa
// X-Idempotency-Key + client_ts có offset, gửi lại sau lỗi mạng dùng đúng request cũ (không làm hai lần).
// Lỗi chặn trong hộp thoại: khối đỏ inline (kết quả → lý do → hành động); ngoài hộp thoại: msgprint đủ ba phần.

const TC_INSTR_CHECK_CODE = "tracecore.v1.instrument.check_code";
const TC_INSTR_CONTEXT = "tracecore.v1.instrument.form_context";
const TC_INSTR_PREVIEW = "tracecore.v1.instrument.giai_preview";
const TC_INSTR_INIT = "tracecore.v1.instrument_admin.init_counters";
const TC_INSTR_RETIRE = "tracecore.v1.instrument_admin.retire";
const TC_INSTR_ASSIGN = "tracecore.v1.instrument_admin.assign_giai";
const TC_INSTR_ETCHING = "tracecore.v1.instrument_admin.record_etching";
// chờ người dùng ngừng gõ rồi mới kiểm mã (ms)
const TC_INSTR_CHECK_DELAY = 300;

function tc_instr_ready() {
	return Boolean(window.tracecore && tracecore.codes);
}

function tc_instr_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

// URL file của chính site (/private/files/, /files/) mới được vào href/src; khác (javascript:, data:, http…, //host)
// → chuỗi rỗng, nơi gọi hiện chữ thay cho link/ảnh
function tc_instr_safe_url(url) {
	if (typeof url !== "string") {
		return "";
	}
	return url.startsWith("/private/files/") || url.startsWith("/files/") ? url : "";
}

function tc_instr_mono(text) {
	return `<span style="font-family: var(--tc-font-mono)">${tc_instr_escape(text)}</span>`;
}

function tc_instr_block(error) {
	if (tc_instr_ready()) {
		return tracecore.codes.block_html(error);
	}
	return `<div class="alert alert-danger" role="alert"><p><strong>${tc_instr_escape(
		error.title
	)}</strong></p><p>${tc_instr_escape(error.reason)}</p><p>${tc_instr_escape(
		error.action
	)}</p></div>`;
}

function tc_instr_show_block(error) {
	frappe.msgprint({
		title: error.title || __("Request refused"),
		indicator: "red",
		message: `<p>${tc_instr_escape(error.reason)}</p><p>${tc_instr_escape(error.action)}</p>`,
	});
}

// dd/mm/yyyy HH:mm (giờ hệ thống do server trả, không đổi múi giờ)
function tc_instr_datetime(value) {
	return value ? moment(value, "YYYY-MM-DD HH:mm:ss").format("DD/MM/YYYY HH:mm") : "";
}

function tc_instr_date(value) {
	return value ? moment(value, "YYYY-MM-DD").format("DD/MM/YYYY") : "";
}

function tc_instr_method_label(method) {
	return __(method, null, "Instrument Compatible Method");
}

function tc_instr_server_message(body) {
	try {
		return JSON.parse(JSON.parse(body._server_messages || "[]")[0] || "{}").message || "";
	} catch (e) {
		return "";
	}
}

// RPC chỉ đọc (GET): trả {ok: true, data} hoặc {ok: false, error: {title, reason, action}}
async function tc_instr_get(method, args) {
	let response;
	try {
		response = await fetch(`/api/method/${method}?${new URLSearchParams(args).toString()}`, {
			method: "GET",
			headers: { Accept: "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token },
		});
	} catch (e) {
		return {
			ok: false,
			error: {
				title: __("Server not reachable"),
				reason: __("The server could not be reached."),
				action: __("Try again."),
			},
		};
	}
	const body = await response.json().catch(() => null);
	const result = (body && body.message) || {};
	if (result.ok) {
		return { ok: true, data: result };
	}
	if (result.error) {
		return { ok: false, error: result.error };
	}
	return {
		ok: false,
		error: {
			title: __("Request refused"),
			reason:
				tc_instr_server_message(body || {}) ||
				__("The server refused the request (HTTP {0}).", [response.status]),
			action: __("Reload the page and try again."),
		},
	};
}

// RPC ghi từ hộp thoại: cùng nội dung sau lỗi mạng/gateway → gửi lại đúng request cũ (cùng khóa idempotent);
// nội dung khác hoặc server đã trả lời → request mới
async function tc_instr_send(holder, method, args) {
	const signature = JSON.stringify(args);
	if (!holder.tc_pending || holder.tc_pending.signature !== signature) {
		holder.tc_pending = { signature, request: tracecore.codes.new_request(args) };
	}
	const result = await tracecore.codes.send(method, holder.tc_pending.request);
	if (!result.network) {
		holder.tc_pending = null;
	}
	if (!result.ok && result.error && !result.error.code && !result.network) {
		// lỗi hệ thống (quyền, tham số): hành động chung, không nói tới máy in như tc_codes.js
		result.error.action = __("Reload the page and try again.");
	}
	return result;
}

async function tc_instr_dialog_send(dialog, method, args) {
	const box = dialog.fields_dict.tc_error && dialog.fields_dict.tc_error.$wrapper;
	if (box) {
		box.empty();
	}
	dialog.disable_primary_action();
	try {
		const result = await tc_instr_send(dialog, method, args);
		if (!result.ok && box) {
			box.html(tc_instr_block(result.error));
		}
		return result;
	} finally {
		dialog.enable_primary_action();
	}
}

// --- Chỉ báo trạng thái (luôn có chữ) -------------------------------------------------------------------

function tc_instr_indicators(frm) {
	if (!frm.is_new()) {
		const colors = { Active: "blue", Retired: "gray" };
		frm.page.set_indicator(
			__(frm.doc.status, null, "Instrument"),
			colors[frm.doc.status] || "gray"
		);
	}
	if (frm.doc.max_cycles_status === "Defined" && frm.doc.max_cycles > 0) {
		frm.dashboard.add_indicator(__("Max cycles: {0}", [frm.doc.max_cycles]), "blue");
	} else {
		frm.dashboard.add_indicator(
			__("Max cycles: {0}", [__("Undefined", null, "Instrument")]),
			"orange"
		);
	}
}

// --- Kiểm mã khi gõ (form mới) -----------------------------------------------------------------------

function tc_instr_code_box(frm) {
	const field = frm.fields_dict.instrument_code;
	let box = field.$wrapper.find(".tc-instr-code-check");
	if (!box.length) {
		box = $('<div class="tc-instr-code-check" aria-live="polite"></div>').appendTo(
			field.$wrapper.find(".control-input-wrapper")
		);
	}
	return box;
}

async function tc_instr_check_code(frm) {
	const value = frm.doc.instrument_code || "";
	const box = tc_instr_code_box(frm);
	if (!value.trim()) {
		box.empty();
		return;
	}
	const token = (frm.tc_code_token = (frm.tc_code_token || 0) + 1);
	const result = await tc_instr_get(TC_INSTR_CHECK_CODE, { code: value });
	if (token !== frm.tc_code_token || !frm.is_new()) {
		return; // người dùng đã gõ tiếp hoặc đã lưu
	}
	if (!result.ok) {
		box.html(tc_instr_block(result.error));
		return;
	}
	const data = result.data;
	if (!data.valid) {
		box.html(`<p class="text-danger">${tc_instr_escape(data.message)}</p>`);
	} else if (data.available) {
		box.html(
			`<p class="text-success">${tc_instr_escape(
				__("Code {0} is available.", [data.code])
			)}</p>`
		);
	} else {
		box.html(
			`<p class="text-danger">${tc_instr_escape(
				__("Code {0} already exists.", [data.code])
			)} ${
				data.suggestion
					? `${tc_instr_escape(__("Suggestion:"))} ${tc_instr_mono(data.suggestion)}`
					: ""
			}</p>`
		);
		if (data.suggestion) {
			$('<button type="button" class="btn btn-xs btn-default"></button>')
				.text(__("Use suggested code"))
				.on("click", () => frm.set_value("instrument_code", data.suggestion))
				.appendTo(box);
		}
	}
}

// --- Khối dữ liệu của form (ảnh/IFU, phương pháp, bảo dưỡng, GIAI) -------------------------------------

function tc_instr_panel(frm, section, name) {
	const field = frm.fields_dict[section];
	if (!field) {
		return null;
	}
	const body = $(field.wrapper).find(".section-body").first();
	let panel = body.find(`.tc-instr-panel[data-panel="${name}"]`);
	if (!panel.length) {
		panel = $(`<div class="tc-instr-panel col-sm-12" data-panel="${name}"></div>`).appendTo(
			body
		);
	}
	return panel;
}

function tc_instr_panels(frm) {
	return {
		media: tc_instr_panel(frm, "section_media", "media"),
		methods: tc_instr_panel(frm, "section_clinical", "methods"),
		maintenance: tc_instr_panel(frm, "section_maintenance", "maintenance"),
		giai: tc_instr_panel(frm, "section_giai", "giai"),
	};
}

function tc_instr_render_media(panel, frm, ctx) {
	const image = ctx.image || {};
	const photo = tc_instr_safe_url(image.image_url);
	const thumb = tc_instr_safe_url(image.thumbnail_url);
	const ifu = tc_instr_safe_url(frm.doc.ifu);
	let html = "";
	if (thumb || photo) {
		html += `<p><a href="${tc_instr_escape(
			photo || thumb
		)}" target="_blank" rel="noopener"><img src="${tc_instr_escape(
			thumb || photo
		)}" alt="${tc_instr_escape(
			__("Photo of instrument {0}", [frm.doc.name])
		)}" class="img-thumbnail"></a></p>`;
	} else {
		html += `<p class="text-muted">${tc_instr_escape(__("No photo yet."))}</p>`;
	}
	if (ifu) {
		html += `<p><a href="${tc_instr_escape(
			ifu
		)}" target="_blank" rel="noopener">${tc_instr_escape(__("Open IFU"))}</a></p>`;
	} else {
		html += `<p class="text-muted">${tc_instr_escape(__("No IFU attached."))}</p>`;
	}
	panel.html(html);
}

function tc_instr_set_type_link(row) {
	const href = `/app/instrument-set-type/${encodeURIComponent(row.set_type)}`;
	let text = `<a href="${tc_instr_escape(href)}">${tc_instr_mono(
		row.set_type
	)}</a> ${tc_instr_escape(row.set_type_name || "")}`;
	if (!row.compatible) {
		text += ` <span class="indicator-pill orange">${tc_instr_escape(
			__("Not compatible")
		)}</span>`;
	}
	return `<li>${text}</li>`;
}

function tc_instr_render_methods(panel, ctx) {
	let html = `<p>${tc_instr_escape(__("Version {0}", [ctx.version_no]))}</p>`;
	if (ctx.bom_usage.length) {
		html += `<p>${tc_instr_escape(
			__("Used in the current BOM of these set types:")
		)}</p><ul>${ctx.bom_usage.map(tc_instr_set_type_link).join("")}</ul>`;
	} else {
		html += `<p class="text-muted">${tc_instr_escape(__("Not used in any current BOM."))}</p>`;
	}
	panel.html(html);
}

function tc_instr_state(state) {
	const map = {
		no_rule: ["gray", __("No threshold")],
		not_due: ["green", __("Not due")],
		due: ["orange", __("Due")],
		overdue: ["red", __("Overdue")],
	};
	const entry = map[state] || ["gray", state];
	return `<span class="indicator-pill ${entry[0]}">${tc_instr_escape(entry[1])}</span>`;
}

function tc_instr_rule_text(rule) {
	if (!rule) {
		return __("No maintenance threshold (instrument or group): no reminder at packing.");
	}
	const source =
		rule.source === "Group" ? __("Instrument Group", null, "Instrument") : __("Instrument");
	const type = rule.maint_type ? __(rule.maint_type, null, "Instrument") : "-";
	return __("Effective threshold: {0} cycles, {1}. Source: {2}.", [rule.interval, type, source]);
}

function tc_instr_render_maintenance(panel, ctx) {
	let html = `<p><strong>${tc_instr_escape(
		tc_instr_rule_text(ctx.effective_rule)
	)}</strong></p>`;
	if (!ctx.counters.length) {
		html += `<p class="text-muted">${tc_instr_escape(
			__("No set contains this instrument in its current BOM.")
		)}</p>`;
		panel.html(html);
		return;
	}
	const rows = ctx.counters
		.map(
			(row) => `<tr>
				<td><a href="/app/set-unit/${encodeURIComponent(row.set_unit)}">${tc_instr_mono(
				row.set_unit
			)}</a></td>
				<td>${tc_instr_mono(row.set_type || "")}</td>
				<td class="text-right">${tc_instr_escape(row.cycles_since)}</td>
				<td class="text-right">${tc_instr_escape(row.deferred_count)}</td>
				<td>${tc_instr_state(row.state)}</td>
			</tr>`
		)
		.join("");
	html += `<table class="table table-bordered table-sm">
		<thead><tr>
			<th>${tc_instr_escape(__("Set ID"))}</th>
			<th>${tc_instr_escape(__("Set Type"))}</th>
			<th class="text-right">${tc_instr_escape(__("Cycles since maintenance"))}</th>
			<th class="text-right">${tc_instr_escape(__("Times deferred"))}</th>
			<th>${tc_instr_escape(__("Maintenance state"))}</th>
		</tr></thead><tbody>${rows}</tbody></table>`;
	panel.html(html);
}

function tc_instr_render_giai(panel, ctx) {
	const giai = ctx.giai;
	let html = "";
	if (!giai) {
		html = `<p class="text-muted">${tc_instr_escape(__("No GIAI code yet."))}</p>`;
	} else {
		html = `<p>${tc_instr_escape(__("GIAI Code", null, "Instrument"))}: ${tc_instr_mono(
			giai.code
		)}</p><p>${tc_instr_escape(__("Human-readable code"))}: ${tc_instr_mono(giai.hri)}</p>`;
		if (giai.etched_on) {
			html += `<p>${tc_instr_escape(
				__("Etched on {0} at: {1}", [tc_instr_date(giai.etched_on), giai.position || "-"])
			)}</p>`;
		} else {
			html += `<p class="text-muted">${tc_instr_escape(
				__("Etching not recorded yet.")
			)}</p>`;
		}
		if (giai.read_only) {
			html += `<p><span class="indicator-pill gray">${tc_instr_escape(
				__("Feature turned off")
			)}</span> ${tc_instr_escape(
				__("The code is kept and stays unique; it is read-only while the feature is off.")
			)}</p>`;
		}
	}
	panel.html(html);
}

function tc_instr_render(frm, ctx) {
	const panels = tc_instr_panels(frm);
	tc_instr_render_media(panels.media, frm, ctx);
	tc_instr_render_methods(panels.methods, ctx);
	tc_instr_render_maintenance(panels.maintenance, ctx);
	if (panels.giai) {
		tc_instr_render_giai(panels.giai, ctx);
	}
}

function tc_instr_render_state(frm, html) {
	Object.values(tc_instr_panels(frm)).forEach((panel) => panel && panel.html(html));
}

// --- Hộp thoại ----------------------------------------------------------------------------------------

function tc_instr_history_dialog(frm, ctx) {
	const rows = ctx.history
		.map(
			(row) => `<tr>
				<td class="text-right">${tc_instr_escape(row.version_no)}</td>
				<td>${tc_instr_escape(row.methods.map(tc_instr_method_label).join(", ") || "-")}</td>
				<td>${tc_instr_escape(tc_instr_datetime(row.changed_on))}</td>
				<td>${tc_instr_escape(row.changed_by_name || row.changed_by || "")}</td>
			</tr>`
		)
		.join("");
	const dialog = new frappe.ui.Dialog({
		title: __("Version history of {0}", [frm.doc.name]),
		size: "large",
		fields: [
			{
				fieldname: "table",
				fieldtype: "HTML",
				options: `<table class="table table-bordered table-sm">
					<thead><tr>
						<th class="text-right">${tc_instr_escape(__("Version", null, "Instrument"))}</th>
						<th>${tc_instr_escape(__("Compatible Methods", null, "Instrument"))}</th>
						<th>${tc_instr_escape(__("Changed on"))}</th>
						<th>${tc_instr_escape(__("Changed by"))}</th>
					</tr></thead><tbody>${rows}</tbody></table>`,
			},
		],
	});
	dialog.show();
}

function tc_instr_init_dialog(frm, ctx) {
	const rows = ctx.counters.filter((row) => row.can_init);
	if (!rows.length) {
		tc_instr_show_block({
			title: __("Counter cannot be initialized"),
			reason: __(
				"Every set with this instrument already has maintenance history at T4, or no set contains it in its current BOM."
			),
			action: __("Counters now change only at packing and release."),
		});
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Initialize maintenance counters of {0}", [frm.doc.name]),
		size: "large",
		fields: [
			{
				fieldname: "intro",
				fieldtype: "HTML",
				options: `<p>${tc_instr_escape(
					tc_instr_rule_text(ctx.effective_rule)
				)}</p><p>${tc_instr_escape(
					__(
						"Enter the cycles since the last maintenance for the sets you know; leave the others empty. Sets with maintenance history at T4 are not listed."
					)
				)}</p>`,
			},
			{
				fieldname: "rows",
				fieldtype: "Table",
				label: __("Sets"),
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: true,
				data: rows.map((row) => ({ set_unit: row.set_unit })),
				fields: [
					{
						fieldname: "set_unit",
						fieldtype: "Data",
						label: __("Set ID"),
						read_only: 1,
						in_list_view: 1,
					},
					{
						fieldname: "cycles_since",
						fieldtype: "Int",
						label: __("Cycles since maintenance"),
						in_list_view: 1,
					},
					{
						fieldname: "last_maint_on",
						fieldtype: "Date",
						label: __("Last maintenance date"),
						in_list_view: 1,
					},
				],
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason"),
				description: __("Where the cycle count comes from, for example the paper log."),
				reqd: 1,
			},
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Initialize counters"),
		async primary_action(values) {
			const filled = (values.rows || []).filter(
				(row) =>
					row.cycles_since !== undefined &&
					row.cycles_since !== null &&
					row.cycles_since !== ""
			);
			if (!filled.length) {
				dialog.fields_dict.tc_error.$wrapper.html(
					tc_instr_block({
						title: __("Counter cannot be initialized"),
						reason: __("No cycle count was entered."),
						action: __(
							"Enter the cycles since the last maintenance for at least one set."
						),
					})
				);
				return;
			}
			const result = await tc_instr_dialog_send(dialog, TC_INSTR_INIT, {
				instrument: frm.doc.name,
				reason: values.reason,
				rows: filled.map((row) => ({
					set_unit: row.set_unit,
					cycles_since: row.cycles_since,
					last_maint_on: row.last_maint_on || null,
				})),
			});
			if (result.ok) {
				dialog.hide();
				frappe.show_alert({
					message: __("{0} counters initialized.", [result.data.counters.length]),
					indicator: "green",
				});
				tc_instr_load(frm);
			}
		},
	});
	dialog.show();
}

function tc_instr_bom_list(boms) {
	return `<ul>${boms.map(tc_instr_set_type_link).join("")}</ul>`;
}

function tc_instr_confirm_retire_dialog(frm, reason, boms) {
	const dialog = new frappe.ui.Dialog({
		title: __("Instrument is in a current BOM"),
		fields: [
			{
				fieldname: "boms",
				fieldtype: "HTML",
				options: `<p>${tc_instr_escape(
					__("Instrument {0} is in the current BOM of these set types:", [frm.doc.name])
				)}</p>${tc_instr_bom_list(boms)}<p>${tc_instr_escape(
					__(
						"Retiring is permanent. The BOMs are not changed; review them after retiring."
					)
				)}</p>`,
			},
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Retire anyway"),
		async primary_action() {
			const result = await tc_instr_dialog_send(dialog, TC_INSTR_RETIRE, {
				instrument: frm.doc.name,
				reason,
				confirm: 1,
			});
			if (result.ok) {
				dialog.hide();
				tc_instr_retired(frm);
			}
		},
	});
	dialog.show();
}

function tc_instr_retired(frm) {
	frappe.show_alert({ message: __("Instrument retired."), indicator: "green" });
	frm.reload_doc();
}

function tc_instr_retire_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Retire instrument {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason for retiring"),
				description: __(
					"Retiring is permanent: the instrument can no longer be added to a BOM."
				),
				reqd: 1,
			},
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Retire instrument"),
		async primary_action(values) {
			const result = await tc_instr_dialog_send(dialog, TC_INSTR_RETIRE, {
				instrument: frm.doc.name,
				reason: values.reason,
			});
			if (result.ok) {
				dialog.hide();
				tc_instr_retired(frm);
			} else if (result.error && result.error.code === "INSTRUMENT_IN_BOM") {
				dialog.hide();
				tc_instr_confirm_retire_dialog(frm, values.reason, result.error.boms || []);
			}
		},
	});
	dialog.show();
}

function tc_instr_assign_giai(frm) {
	frappe.confirm(
		tc_instr_escape(
			__(
				"Assign a GIAI code to instrument {0}? The code is generated by TraceCore and is never reissued or replaced.",
				[frm.doc.name]
			)
		),
		async () => {
			const holder = frm.tc_assign || (frm.tc_assign = {});
			frappe.dom.freeze();
			let result;
			try {
				result = await tc_instr_send(holder, TC_INSTR_ASSIGN, {
					instrument: frm.doc.name,
				});
			} finally {
				frappe.dom.unfreeze();
			}
			if (result.ok) {
				frappe.show_alert({
					message: __("GIAI code {0} assigned.", [result.data.giai]),
					indicator: "green",
				});
				frm.reload_doc();
			} else {
				tc_instr_show_block(result.error);
			}
		}
	);
}

function tc_instr_etching_dialog(frm) {
	const rerecord = Boolean(frm.doc.giai_etched_on);
	const dialog = new frappe.ui.Dialog({
		title: __("Record etching of {0}", [frm.doc.giai_code]),
		fields: [
			{
				fieldname: "etched_on",
				fieldtype: "Date",
				label: __("Etched On", null, "Instrument"),
				default: frm.doc.giai_etched_on || frappe.datetime.get_today(),
				reqd: 1,
			},
			{
				fieldname: "position",
				fieldtype: "Data",
				label: __("Etching Position", null, "Instrument"),
				default: frm.doc.giai_position || "",
				reqd: 1,
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason for correcting"),
				description: __("The etching is already recorded; a correction needs a reason."),
				hidden: rerecord ? 0 : 1,
				reqd: rerecord ? 1 : 0,
			},
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Record etching"),
		async primary_action(values) {
			const args = {
				instrument: frm.doc.name,
				etched_on: values.etched_on,
				position: values.position,
			};
			if (rerecord) {
				args.reason = values.reason;
			}
			const result = await tc_instr_dialog_send(dialog, TC_INSTR_ETCHING, args);
			if (result.ok) {
				dialog.hide();
				frappe.show_alert({ message: __("Etching recorded."), indicator: "green" });
				frm.reload_doc();
			}
		},
	});
	dialog.show();
}

async function tc_instr_preview_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("GIAI DataMatrix of {0}", [frm.doc.name]),
		fields: [{ fieldname: "preview", fieldtype: "HTML" }],
	});
	const wrapper = dialog.fields_dict.preview.$wrapper;
	wrapper.html(`<p class="text-muted">${tc_instr_escape(__("Loading..."))}</p>`);
	dialog.show();
	const result = await tc_instr_get(TC_INSTR_PREVIEW, { instrument: frm.doc.name });
	if (!result.ok) {
		wrapper.html(tc_instr_block(result.error));
		return;
	}
	const data = result.data;
	wrapper.html(`<p><img src="data:image/png;base64,${tc_instr_escape(
		data.png_b64
	)}" alt="${tc_instr_escape(__("DataMatrix of {0}", [data.giai]))}" class="img-fluid"></p>
		<p>${tc_instr_escape(__("GIAI Code", null, "Instrument"))}: ${tc_instr_mono(data.giai)}</p>
		<p>${tc_instr_escape(__("Human-readable code"))}: ${tc_instr_mono(data.hri)}</p>
		<p class="text-muted">${tc_instr_escape(
			__("Check the etched code against this preview before releasing the instrument.")
		)}</p>`);
}

// --- Nút theo quyền do server trả -----------------------------------------------------------------------

// Chỉ gỡ nút do script này thêm: xóa toàn bộ nút của form sẽ xóa cả nút của Client Script khác
function tc_instr_add_button(frm, label, action, group) {
	frm.add_custom_button(label, action, group);
	(frm.tc_instr_buttons || (frm.tc_instr_buttons = [])).push([label, group]);
}

function tc_instr_remove_buttons(frm) {
	(frm.tc_instr_buttons || []).forEach(([label, group]) =>
		frm.remove_custom_button(label, group)
	);
	frm.tc_instr_buttons = [];
}

function tc_instr_buttons(frm, ctx) {
	const perms = ctx.permissions;
	const history = __("Version history");
	tc_instr_add_button(frm, history, () => tc_instr_history_dialog(frm, ctx));
	if (!tc_instr_ready()) {
		return; // tc_codes.js (bundle Desk) chưa nạp: chỉ đọc, không gửi được thao tác ghi
	}
	if (perms.can_init_counters) {
		tc_instr_add_button(
			frm,
			__("Initialize counters"),
			() => tc_instr_init_dialog(frm, ctx),
			__("Maintenance", null, "Instrument")
		);
	}
	if (perms.can_retire) {
		tc_instr_add_button(frm, __("Retire instrument"), () => tc_instr_retire_dialog(frm));
	}
	if (perms.can_assign_giai) {
		tc_instr_add_button(frm, __("Assign GIAI"), () => tc_instr_assign_giai(frm), __("GIAI"));
	}
	if (perms.can_record_etching) {
		tc_instr_add_button(
			frm,
			__("Record etching"),
			() => tc_instr_etching_dialog(frm),
			__("GIAI")
		);
	}
	// server quyết (R10/SM, đã có mã, kể cả khi cờ tắt) như v1.instrument.giai_preview
	if (perms.can_preview_giai) {
		tc_instr_add_button(
			frm,
			__("Preview DataMatrix"),
			() => tc_instr_preview_dialog(frm),
			__("GIAI")
		);
	}
}

async function tc_instr_load(frm) {
	const token = (frm.tc_ctx_token = (frm.tc_ctx_token || 0) + 1);
	tc_instr_render_state(frm, `<p class="text-muted">${tc_instr_escape(__("Loading..."))}</p>`);
	const result = await tc_instr_get(TC_INSTR_CONTEXT, { instrument: frm.doc.name });
	if (token !== frm.tc_ctx_token || frm.is_new()) {
		return; // form đã chuyển bản ghi hoặc đã tải lại
	}
	if (!result.ok) {
		tc_instr_render_state(frm, tc_instr_block(result.error));
		return;
	}
	frm.tc_ctx = result.data;
	tc_instr_render(frm, result.data);
	tc_instr_remove_buttons(frm);
	tc_instr_buttons(frm, result.data);
}

// Frappe hiện giá trị Select bằng __(value) không context: trạng thái lấy bản dịch chung của frappe, phương pháp không
// dịch. Formatter dịch theo context DocType (dòng vi.csv có cột context) để form và bảng con khớp chỉ báo trạng thái.
const TC_INSTR_SELECT_FIELDS = ["status", "spaulding_class", "maint_type", "max_cycles_status"];

function tc_instr_select_formatter(context) {
	return (value) => (value ? tc_instr_escape(__(value, null, context)) : "");
}

function tc_instr_translate_selects(frm) {
	TC_INSTR_SELECT_FIELDS.forEach((fieldname) => {
		const field = frm.fields_dict[fieldname];
		if (field) {
			field.df.formatter = tc_instr_select_formatter("Instrument");
			frm.refresh_field(fieldname);
		}
	});
	const grid = frm.fields_dict.compatible_methods && frm.fields_dict.compatible_methods.grid;
	if (grid) {
		grid.update_docfield_property(
			"method",
			"formatter",
			tc_instr_select_formatter("Instrument Compatible Method")
		);
		// dòng đã vẽ giữ docfield cũ: vẽ lại để dùng formatter mới
		(grid.grid_rows || []).forEach((row) => {
			row.docfields = grid.docfields;
			row.refresh();
		});
	}
}

frappe.ui.form.on("Instrument", {
	refresh(frm) {
		tc_instr_translate_selects(frm);
		tc_instr_indicators(frm);
		if (frm.is_new()) {
			tc_instr_render_state(frm, "");
			if (frm.doc.instrument_code) {
				tc_instr_check_code(frm);
			}
			return;
		}
		tc_instr_code_box(frm).empty();
		tc_instr_load(frm);
	},

	instrument_code(frm) {
		if (!frm.is_new()) {
			return;
		}
		clearTimeout(frm.tc_code_timer);
		frm.tc_code_timer = setTimeout(() => tc_instr_check_code(frm), TC_INSTR_CHECK_DELAY);
	},
});
