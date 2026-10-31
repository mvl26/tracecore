/* global tracecore */
// Desk: form loại bộ dụng cụ và BOM theo phiên bản (SCR-02, FEAT-015 Task 8; UC-02, FR-M1-03, FR-M1-04).
// Ba tab Master Form: Thông tin (phần đầu, hạn lưu áp dụng, ảnh bộ đã xếp), Chi tiết (BOM của phiên bản đang xem, danh
// sách phiên bản), Lịch sử (bảng phiên bản). Dữ liệu và quy tắc ở server: tracecore.v1.set_type.form_context (phiên bản,
// trạng thái, hạn lưu áp dụng, cơ số suy ra, ảnh, cảnh báo thiếu, quyền), bom, compare, count_sheet, pack_type_query
// (gợi ý loại gói dùng được), department_query (gợi ý khoa). JS không giữ giới hạn dòng/số lượng, danh sách phương pháp hay quy tắc ngày hiệu lực.
// Ghi (tạo loại bộ cùng BOM v1, lưu phiên bản mới, sao chép) gửi bằng tracecore.codes.send của tc_codes.js: fetch thay
// frappe.call vì Frappe bỏ mất body của HTTP 404/409/422; mỗi thao tác một khóa X-Idempotency-Key + client_ts có
// offset, gửi lại sau lỗi mạng dùng đúng request cũ. Lỗi chặn trong hộp thoại: khối đỏ inline (kết quả → lý do → hành
// động), lỗi từng dòng BOM hiện ngay dưới dòng đó.

const TC_ST_CONTEXT = "tracecore.v1.set_type.form_context";
const TC_ST_BOM = "tracecore.v1.set_type.bom";
const TC_ST_COMPARE = "tracecore.v1.set_type.compare";
const TC_ST_COUNT_SHEET = "tracecore.v1.set_type.count_sheet";
const TC_ST_PACK_QUERY = "tracecore.v1.set_type.pack_type_query";
const TC_ST_DEPARTMENT_QUERY = "tracecore.v1.set_type.department_query";
const TC_ST_CREATE = "tracecore.v1.set_type_admin.create";
const TC_ST_SAVE_BOM = "tracecore.v1.set_type_admin.save_bom";
const TC_ST_COPY = "tracecore.v1.set_type_admin.copy";
const TC_ST_GTIN_STATUS = "tracecore.v1.gtin.status";
const TC_ST_GTIN_CHANGE = "tracecore.v1.gtin.change_locked";
// phần đầu gửi khi tạo loại bộ (khớp bom_versions.HEADER_FIELDS); ảnh khay tải lên sau khi loại bộ đã có
const TC_ST_HEADER_FIELDS = [
	"type_code",
	"set_type_name",
	"method",
	"department",
	"default_pack_type",
	"shelf_life_days",
	"is_implant",
	"assembly_minutes",
	"gtin",
];
const TC_ST_PHOTO_FIELDS = ["tray_image", "tray_image_2", "tray_image_3"];

function tc_st_ready() {
	return Boolean(window.tracecore && tracecore.codes);
}

function tc_st_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

// URL file của chính site (/private/files/, /files/) mới được vào href/src; khác (javascript:, data:, http…, //host)
// → chuỗi rỗng, nơi gọi hiện chữ thay cho ảnh
function tc_st_safe_url(url) {
	if (typeof url !== "string") {
		return "";
	}
	return url.startsWith("/private/files/") || url.startsWith("/files/") ? url : "";
}

function tc_st_mono(text) {
	return `<span style="font-family: var(--tc-font-mono)">${tc_st_escape(text)}</span>`;
}

function tc_st_block(error) {
	if (tc_st_ready()) {
		return tracecore.codes.block_html(error);
	}
	return `<div class="alert alert-danger" role="alert"><p><strong>${tc_st_escape(
		error.title
	)}</strong></p><p>${tc_st_escape(error.reason)}</p><p>${tc_st_escape(error.action)}</p></div>`;
}

function tc_st_muted(text) {
	return `<p class="text-muted">${tc_st_escape(text)}</p>`;
}

// dd/mm/yyyy và dd/mm/yyyy HH:mm (giờ hệ thống do server trả, không đổi múi giờ)
function tc_st_date(value) {
	return value ? moment(value, "YYYY-MM-DD").format("DD/MM/YYYY") : "";
}

function tc_st_datetime(value) {
	return value ? moment(value, "YYYY-MM-DD HH:mm:ss").format("DD/MM/YYYY HH:mm") : "";
}

function tc_st_server_message(body) {
	try {
		return JSON.parse(JSON.parse(body._server_messages || "[]")[0] || "{}").message || "";
	} catch (e) {
		return "";
	}
}

// Trạng thái phiên bản luôn có chữ (nhãn dùng chung với phiếu kiểm đếm)
function tc_st_status_text(status) {
	const labels = {
		Effective: __("BOM in effect"),
		Scheduled: __("BOM scheduled"),
		Superseded: __("BOM superseded"),
		Skipped: __("BOM replaced before taking effect"),
	};
	return labels[status] || status || "-";
}

function tc_st_status(status) {
	const colors = { Effective: "green", Scheduled: "blue" };
	return `<span class="indicator-pill ${colors[status] || "gray"}">${tc_st_escape(
		tc_st_status_text(status)
	)}</span>`;
}

function tc_st_user(user) {
	// tên đầy đủ (frappe.user.full_name trả "Bạn" cho chính người xem, không hợp với bảng lịch sử)
	return user ? (frappe.user_info(user) || {}).fullname || user : "";
}

// --- Gọi server -------------------------------------------------------------------------------------------

// RPC chỉ đọc (GET): trả {ok: true, data} hoặc {ok: false, error: {title, reason, action}}
async function tc_st_get(method, args) {
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
				tc_st_server_message(body || {}) ||
				__("The server refused the request (HTTP {0}).", [response.status]),
			action: __("Reload the page and try again."),
		},
	};
}

// RPC ghi từ hộp thoại: cùng nội dung sau lỗi mạng/gateway → gửi lại đúng request cũ (cùng khóa idempotent);
// nội dung khác hoặc server đã trả lời → request mới
async function tc_st_send(holder, method, args) {
	if (!tc_st_ready()) {
		return {
			ok: false,
			error: {
				title: __("Not saved"),
				reason: __("The TraceCore Desk script is not loaded."),
				action: __("Reload the page and try again."),
			},
		};
	}
	const signature = JSON.stringify(args);
	if (!holder.tc_pending || holder.tc_pending.signature !== signature) {
		holder.tc_pending = { signature, request: tracecore.codes.new_request(args) };
	}
	const result = await tracecore.codes.send(method, holder.tc_pending.request);
	if (!result.network) {
		holder.tc_pending = null;
	}
	if (!result.ok && result.error && !result.error.code && !result.network) {
		// lỗi kiểm tra của Frappe (phần đầu loại bộ, quyền): hành động chung, không nói tới máy in như tc_codes.js
		result.error.action = __("Correct the data shown in the message, then try again.");
	}
	return result;
}

async function tc_st_dialog_send(dialog, method, args) {
	const box = dialog.fields_dict.tc_error.$wrapper;
	box.empty();
	dialog.disable_primary_action();
	try {
		const result = await tc_st_send(dialog, method, args);
		if (!result.ok) {
			box.html(tc_st_block(result.error));
		}
		return result;
	} finally {
		dialog.enable_primary_action();
	}
}

// Lỗi từng dòng (BOM_LINE_INVALID của sao chép): danh sách dưới khối đỏ
function tc_st_items_html(items) {
	if (!items || !items.length) {
		return "";
	}
	return `<ul class="text-danger">${items
		.map(
			(item) =>
				`<li>${tc_st_escape(__("Row {0}", [item.row]))}: ${tc_st_mono(
					item.instrument
				)} — ${tc_st_escape(item.message)}</li>`
		)
		.join("")}</ul>`;
}

// --- Bảng nhập dòng BOM (tạo loại bộ, sửa BOM) -------------------------------------------------------------

// Thứ tự xếp = thứ tự dòng (nút Lên/Xuống). Dòng không có mã dụng cụ bị bỏ qua khi gửi; số lượng và mọi luật dòng do
// server kiểm và trả lỗi theo số dòng đã gửi (row 1..n) → hiện ngay dưới dòng tương ứng.
function tc_st_editor(wrapper, lines) {
	const rows = [];
	wrapper.html(`<table class="table table-bordered table-sm">
		<thead><tr>
			<th class="text-right">${tc_st_escape(__("Packing order"))}</th>
			<th>${tc_st_escape(__("Instrument"))}</th>
			<th>${tc_st_escape(__("Instrument code"))}</th>
			<th class="text-right">${tc_st_escape(__("BOM quantity"))}</th>
			<th>${tc_st_escape(__("Arrange"))}</th>
		</tr></thead>
	</table>
	<p><button type="button" class="btn btn-default btn-sm tc-st-add">${tc_st_escape(
		__("Add line")
	)}</button></p>`);
	const table = wrapper.find("table");

	function refresh_numbers() {
		rows.forEach((row, index) => {
			row.$body.find(".tc-st-no").text(index + 1);
			row.$body.find(".tc-st-up").prop("disabled", index === 0);
			row.$body.find(".tc-st-down").prop("disabled", index === rows.length - 1);
		});
	}

	function show_code(row) {
		row.$body.find(".tc-st-code").text(row.control.get_input_value() || "");
	}

	function move(row, step) {
		const index = rows.indexOf(row);
		const other = rows[index + step];
		if (!other) {
			return;
		}
		rows[index] = other;
		rows[index + step] = row;
		if (step < 0) {
			row.$body.insertBefore(other.$body);
		} else {
			row.$body.insertAfter(other.$body);
		}
		refresh_numbers();
	}

	function add(line) {
		const $body = $(`<tbody>
			<tr class="tc-st-line">
				<td class="text-right tc-st-no"></td>
				<td class="tc-st-instrument"></td>
				<td class="tc-st-code" style="font-family: var(--tc-font-mono)"></td>
				<td><input type="number" class="form-control tc-st-qty" min="1" step="1"
					aria-label="${tc_st_escape(__("BOM quantity"))}"></td>
				<td>
					<button type="button" class="btn btn-default btn-xs tc-st-up">${tc_st_escape(
						__("Move up")
					)}</button>
					<button type="button" class="btn btn-default btn-xs tc-st-down">${tc_st_escape(
						__("Move down")
					)}</button>
					<button type="button" class="btn btn-default btn-xs tc-st-remove">${tc_st_escape(
						__("Remove line")
					)}</button>
				</td>
			</tr>
			<tr class="tc-st-errors hidden"><td></td><td colspan="4" class="text-danger"></td></tr>
		</tbody>`).appendTo(table);
		const row = { $body };
		row.control = frappe.ui.form.make_control({
			parent: $body.find(".tc-st-instrument"),
			df: {
				fieldtype: "Link",
				options: "Instrument",
				fieldname: "instrument",
				label: __("Instrument"),
				placeholder: __("Type or scan the instrument code"),
				// gợi ý chỉ dụng cụ còn dùng (FR-M1-03.6); server vẫn kiểm từng dòng khi lưu
				get_query: () => ({ filters: { status: "Active" } }),
				onchange: () => show_code(row),
			},
			only_input: true,
			render_input: true,
		});
		if (line.instrument) {
			if (line.instrument_name) {
				frappe.utils.add_link_title("Instrument", line.instrument, line.instrument_name);
			}
			row.control.set_formatted_input(line.instrument);
			row.$body.find(".tc-st-code").text(line.instrument);
		}
		$body.find(".tc-st-qty").val(line.qty === undefined || line.qty === null ? 1 : line.qty);
		$body.find(".tc-st-up").on("click", () => move(row, -1));
		$body.find(".tc-st-down").on("click", () => move(row, 1));
		$body.find(".tc-st-remove").on("click", () => {
			rows.splice(rows.indexOf(row), 1);
			$body.remove();
			refresh_numbers();
		});
		rows.push(row);
		refresh_numbers();
		return row;
	}

	function clear_errors() {
		rows.forEach((row) => {
			row.$body.find(".tc-st-line").removeClass("table-danger");
			row.$body.find(".tc-st-errors").addClass("hidden").find("td").last().empty();
		});
	}

	// {lines: [{instrument, qty, position}], sent: [dòng của bảng tương ứng row 1..n]}
	function collect() {
		const sent = [];
		const payload = [];
		rows.forEach((row) => {
			const instrument = String(row.control.get_input_value() || "").trim();
			if (!instrument) {
				return;
			}
			sent.push(row);
			payload.push({
				instrument,
				qty: String(row.$body.find(".tc-st-qty").val() || "").trim(),
				position: payload.length + 1,
			});
		});
		return { lines: payload, sent };
	}

	function show_errors(error, sent) {
		if (!error || error.code !== "BOM_LINE_INVALID" || !error.items) {
			return;
		}
		error.items.forEach((item) => {
			const row = sent[item.row - 1];
			if (!row) {
				return;
			}
			row.$body.find(".tc-st-line").addClass("table-danger");
			const cell = row.$body.find(".tc-st-errors").removeClass("hidden").find("td").last();
			cell.append(`<div>${tc_st_escape(item.message)}</div>`);
		});
	}

	wrapper.find(".tc-st-add").on("click", () => add({}));
	(lines.length ? lines : [{}]).forEach((line) => add(line));
	return { collect, clear_errors, show_errors };
}

// --- Tạo loại bộ cùng BOM v1 (form mới) ----------------------------------------------------------------------

function tc_st_missing_header(frm) {
	return frm.meta.fields
		.filter(
			(df) =>
				df.reqd &&
				TC_ST_HEADER_FIELDS.includes(df.fieldname) &&
				[undefined, null, ""].includes(frm.doc[df.fieldname])
		)
		.map((df) => __(df.label, null, frm.doctype));
}

function tc_st_header(frm) {
	const header = {};
	TC_ST_HEADER_FIELDS.forEach((fieldname) => {
		const value = frm.doc[fieldname];
		if (![undefined, null, ""].includes(value)) {
			header[fieldname] = value;
		}
	});
	return header;
}

function tc_st_create_dialog(frm) {
	let editor;
	const dialog = new frappe.ui.Dialog({
		title: __("Save and create BOM v1"),
		size: "extra-large",
		fields: [
			{
				fieldname: "intro",
				fieldtype: "HTML",
				options: tc_st_muted(
					__(
						"List the instruments of the set in packing order. The set type and BOM version 1 are saved together; nothing is saved while a line has an error."
					)
				),
			},
			{ fieldname: "lines", fieldtype: "HTML" },
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Create set type"),
		async primary_action() {
			editor.clear_errors();
			const missing = tc_st_missing_header(frm);
			if (missing.length) {
				dialog.fields_dict.tc_error.$wrapper.html(
					tc_st_block({
						title: __("Set type not created"),
						reason: __("Required fields are empty: {0}.", [missing.join(", ")]),
						action: __(
							"Close this dialog, fill them in on the form, then save again."
						),
					})
				);
				return;
			}
			const sent = editor.collect();
			const result = await tc_st_dialog_send(dialog, TC_ST_CREATE, {
				header: tc_st_header(frm),
				lines: sent.lines,
			});
			if (result.ok) {
				dialog.hide();
				frappe.show_alert({
					message: __("Set type {0} created with BOM version 1.", [
						result.data.set_type,
					]),
					indicator: "green",
				});
				const draft = frm.docname;
				Promise.resolve(frappe.set_route("Form", frm.doctype, result.data.set_type)).then(
					() => frappe.model.remove_from_locals(frm.doctype, draft)
				);
				return;
			}
			editor.show_errors(result.error, sent.sent);
		},
	});
	editor = tc_st_editor(dialog.fields_dict.lines.$wrapper, []);
	dialog.show();
}

// --- Thông tin: hạn lưu áp dụng, cơ số suy ra, cảnh báo, ảnh bộ đã xếp --------------------------------------

function tc_st_render_shelf_life(frm, ctx) {
	const field = frm.fields_dict.shelf_life_html;
	if (!field) {
		return;
	}
	const life = ctx.shelf_life || {};
	if (life.pack_type_days === null || life.pack_type_days === undefined) {
		field.$wrapper.html(
			`<p class="text-danger">${tc_st_escape(
				__(
					"The default pack type has no usable shelf life. Choose a pack type from the suggestions."
				)
			)}</p>`
		);
		return;
	}
	const source =
		life.source === "Set Type" ? __("override of this set type") : __("default pack type");
	field.$wrapper.html(
		`<p>${tc_st_escape(
			__("Default from pack type: {0} days · Applied: {1} days ({2})", [
				life.pack_type_days,
				life.days,
				source,
			])
		)}</p>`
	);
}

function tc_st_render_indicators(frm, ctx) {
	if (ctx.effective_version) {
		frm.dashboard.add_indicator(__("BOM in effect: v{0}", [ctx.effective_version]), "green");
	} else {
		frm.dashboard.add_indicator(__("No BOM version in effect"), "orange");
	}
	const cycles = ctx.derived_max_cycles || {};
	const undefined_count = (cycles.undefined || []).length;
	const value =
		cycles.value === null || cycles.value === undefined
			? __("Undefined", null, "Instrument")
			: cycles.value;
	let label = __("Set max cycles (derived): {0}", [value]);
	if (undefined_count) {
		label += ` — ${__("{0} instruments Undefined", [undefined_count])}`;
	}
	frm.dashboard.add_indicator(
		label,
		undefined_count || cycles.value === null || cycles.value === undefined ? "orange" : "blue"
	);
}

function tc_st_prefix_missing_text() {
	return __("GS1 company prefix not declared. Ask R10 to enter it in TraceCore Settings.");
}

function tc_st_render_warnings(frm, ctx) {
	const gtin = ctx.gtin || {};
	const messages = (ctx.missing || []).map((item) => item.message);
	if (!gtin.prefix) {
		messages.push(tc_st_prefix_missing_text());
	}
	if (gtin.foreign_prefix) {
		messages.push(
			__("GTIN-14 {0} does not start with the declared GS1 company prefix {1}.", [
				frm.doc.gtin,
				gtin.prefix,
			])
		);
	}
	if (!messages.length) {
		return;
	}
	frm.set_intro(
		`<div>${messages.map((message) => tc_st_escape(message)).join("<br>")}</div>`,
		"orange"
	);
}

// GTIN đã in lên nhãn: khóa ô nhập; R10 đổi qua hộp thoại, có lý do (A-76). Server kiểm lại quyền và GTIN.
function tc_st_render_gtin(frm, ctx) {
	const gtin = ctx.gtin || {};
	frm.set_df_property("gtin", "read_only", gtin.locked ? 1 : 0);
	frm.tc_st_gtin_help = frm.tc_st_gtin_help || frm.get_docfield("gtin").description;
	frm.set_df_property(
		"gtin",
		"description",
		gtin.locked
			? __(
					"Locked: {0} packs are labelled with this GTIN-14. Only R10 can unlock it, with a reason.",
					[gtin.pack_count]
			  )
			: frm.tc_st_gtin_help
	);
	if (gtin.can_unlock && tc_st_ready()) {
		tc_st_add_button(frm, __("Unlock GTIN"), () => tc_st_unlock_dialog(frm, gtin));
	}
}

function tc_st_unlock_dialog(frm, gtin) {
	const dialog = new frappe.ui.Dialog({
		title: __("Unlock GTIN of {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "intro",
				fieldtype: "HTML",
				options: tc_st_muted(
					__(
						"Packs already labelled keep the old GTIN, and the old GTIN is never issued again. This is written to the Audit Log."
					)
				),
			},
			{
				fieldname: "gtin",
				fieldtype: "Data",
				label: __("New GTIN-14"),
				default: gtin.suggested || "",
			},
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason (required)") },
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Change GTIN"),
		async primary_action(values) {
			const result = await tc_st_dialog_send(dialog, TC_ST_GTIN_CHANGE, {
				set_type: frm.doc.name,
				gtin: values.gtin || "",
				reason: values.reason || "",
			});
			if (result.ok) {
				dialog.hide();
				frappe.show_alert({
					message: __("GTIN-14 of {0} changed to {1}.", [
						frm.doc.name,
						result.data.gtin,
					]),
					indicator: "green",
				});
				frm.reload_doc();
			}
		},
	});
	dialog.show();
}

function tc_st_render_photos(frm, ctx) {
	const field = frm.fields_dict.tray_html;
	if (!field) {
		return;
	}
	const photos = ctx.photos || [];
	const cells = TC_ST_PHOTO_FIELDS.map((fieldname, index) => {
		const photo = photos.find((item) => item.position === index + 1);
		const image = photo ? tc_st_safe_url(photo.image_url) : "";
		const thumb = photo ? tc_st_safe_url(photo.thumbnail_url) : "";
		const label = `<p><strong>${tc_st_escape(__("Photo {0}", [index + 1]))}</strong></p>`;
		const body =
			image || thumb
				? `<a href="${tc_st_escape(
						image || thumb
				  )}" target="_blank" rel="noopener"><img src="${tc_st_escape(
						thumb || image
				  )}" alt="${tc_st_escape(
						__("Photo {0} of set type {1}", [index + 1, frm.doc.name])
				  )}" class="img-thumbnail" style="max-width: var(--tc-photo-sm-w)"></a>`
				: tc_st_muted(__("No photo"));
		return `<div class="col-sm-4">${label}${body}</div>`;
	}).join("");
	let html = `<div class="row">${cells}</div>`;
	if (ctx.permissions.can_edit && photos.length > 1) {
		html += `<p><button type="button" class="btn btn-default btn-sm tc-st-reorder">${tc_st_escape(
			__("Reorder photos")
		)}</button></p>`;
	}
	field.$wrapper.html(html);
	field.$wrapper.find(".tc-st-reorder").on("click", () => tc_st_reorder_dialog(frm, photos));
}

// Đổi thứ tự = đổi chỗ giá trị ba trường ảnh rồi lưu form như thường (server làm lại thumbnail, ghi Audit)
function tc_st_reorder_dialog(frm, photos) {
	if (frm.is_dirty()) {
		frappe.show_alert({
			message: __("Save or discard your other changes before reordering photos."),
			indicator: "orange",
		});
		return;
	}
	const choices = TC_ST_PHOTO_FIELDS.map((fieldname, index) => String(index + 1)).join("\n");
	const fields = [];
	photos.forEach((photo) => {
		const thumb = tc_st_safe_url(photo.thumbnail_url) || tc_st_safe_url(photo.image_url);
		fields.push({
			fieldname: `preview_${photo.position}`,
			fieldtype: "HTML",
			options: thumb
				? `<img src="${tc_st_escape(thumb)}" alt="${tc_st_escape(
						__("Photo {0}", [photo.position])
				  )}" class="img-thumbnail" style="max-width: var(--tc-photo-sm-w)">`
				: tc_st_muted(__("Photo {0}", [photo.position])),
		});
		fields.push({
			fieldname: `position_${photo.position}`,
			fieldtype: "Select",
			label: __("New position of photo {0}", [photo.position]),
			options: choices,
			default: String(photo.position),
		});
	});
	fields.push({ fieldname: "tc_error", fieldtype: "HTML" });
	const dialog = new frappe.ui.Dialog({
		title: __("Reorder photos"),
		fields,
		primary_action_label: __("Save order"),
		async primary_action(values) {
			const wanted = photos.map((photo) => Number(values[`position_${photo.position}`]));
			if (new Set(wanted).size !== wanted.length) {
				dialog.fields_dict.tc_error.$wrapper.html(
					tc_st_block({
						title: __("Order not saved"),
						reason: __("Two photos have the same position."),
						action: __("Give each photo a different position."),
					})
				);
				return;
			}
			const values_by_field = {};
			TC_ST_PHOTO_FIELDS.forEach((fieldname) => (values_by_field[fieldname] = null));
			photos.forEach((photo, index) => {
				values_by_field[TC_ST_PHOTO_FIELDS[wanted[index] - 1]] =
					frm.doc[TC_ST_PHOTO_FIELDS[photo.position - 1]];
			});
			dialog.hide();
			await frm.set_value(values_by_field);
			await frm.save();
		},
	});
	dialog.show();
}

// --- Chi tiết: BOM của phiên bản đang xem và danh sách phiên bản ---------------------------------------------

function tc_st_version_row(ctx, version) {
	return (ctx.versions || []).find((row) => row.bom_version === version);
}

function tc_st_render_bom(frm, ctx, data) {
	const field = frm.fields_dict.bom_html;
	const row = tc_st_version_row(ctx, data.bom_version) || {};
	const lines = (data.lines || [])
		.map((line) => {
			const thumb = tc_st_safe_url(line.thumbnail);
			return `<tr>
				<td class="text-right">${tc_st_escape(line.position)}</td>
				<td>${tc_st_mono(line.instrument)}</td>
				<td>${tc_st_escape(line.instrument_name)}</td>
				<td class="text-right">${tc_st_escape(line.qty)}</td>
				<td>${
					thumb
						? `<img src="${tc_st_escape(thumb)}" alt="${tc_st_escape(
								__("Photo of instrument {0}", [line.instrument])
						  )}" class="img-thumbnail" style="max-width: var(--tc-photo-sm-w)">`
						: `<span class="text-muted">${tc_st_escape(__("No photo"))}</span>`
				}</td>
			</tr>`;
		})
		.join("");
	let html = `<p><strong>${tc_st_escape(
		__("BOM version {0}", [data.bom_version])
	)}</strong> ${tc_st_status(data.status)} ${tc_st_escape(
		__("effective from {0}", [tc_st_date(data.effective_from) || "-"])
	)}</p>`;
	if (row.reason) {
		html += `<p>${tc_st_escape(__("Reason: {0}", [row.reason]))}</p>`;
	}
	html += `<table class="table table-bordered table-sm">
		<thead><tr>
			<th class="text-right">${tc_st_escape(__("Packing order"))}</th>
			<th>${tc_st_escape(__("Instrument code"))}</th>
			<th>${tc_st_escape(__("Instrument name"))}</th>
			<th class="text-right">${tc_st_escape(__("BOM quantity"))}</th>
			<th>${tc_st_escape(__("Instrument photo"))}</th>
		</tr></thead>
		<tbody>${lines}</tbody>
		<tfoot><tr><td colspan="5"><strong>${tc_st_escape(
			__("Total: {0} lines, {1} instruments", [data.total_lines, data.total_qty])
		)}</strong></td></tr></tfoot>
	</table>`;
	html += tc_st_versions_table(ctx, data.bom_version);
	field.$wrapper.html(html);
	field.$wrapper.find(".tc-st-view").on("click", (event) => {
		tc_st_show_version(frm, Number($(event.currentTarget).attr("data-version")));
	});
}

function tc_st_versions_table(ctx, viewing) {
	const rows = (ctx.versions || [])
		.map(
			(row) => `<tr>
				<td class="text-right">${tc_st_escape(row.bom_version)}</td>
				<td>${tc_st_escape(tc_st_date(row.effective_from))}</td>
				<td>${tc_st_status(row.status)}</td>
				<td class="text-right">${tc_st_escape(row.line_count)}</td>
				<td class="text-right">${tc_st_escape(row.total_qty)}</td>
				<td>${
					row.bom_version === viewing
						? `<span class="text-muted">${tc_st_escape(__("Shown above"))}</span>`
						: `<button type="button" class="btn btn-default btn-xs tc-st-view" data-version="${tc_st_escape(
								row.bom_version
						  )}">${tc_st_escape(__("View version"))}</button>`
				}</td>
			</tr>`
		)
		.join("");
	return `<p><strong>${tc_st_escape(__("BOM versions"))}</strong></p>
		<table class="table table-bordered table-sm">
			<thead><tr>
				<th class="text-right">${tc_st_escape(__("BOM version"))}</th>
				<th>${tc_st_escape(__("Effective from"))}</th>
				<th>${tc_st_escape(__("Version status"))}</th>
				<th class="text-right">${tc_st_escape(__("Line count"))}</th>
				<th class="text-right">${tc_st_escape(__("Instrument count"))}</th>
				<th></th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>`;
}

async function tc_st_show_version(frm, version) {
	const field = frm.fields_dict.bom_html;
	const ctx = frm.tc_ctx;
	if (!version) {
		frm.tc_view = null;
		field.$wrapper.html(
			tc_st_muted(__("No BOM version yet.")) + tc_st_versions_table(ctx, null)
		);
		return;
	}
	const token = (frm.tc_view_token = (frm.tc_view_token || 0) + 1);
	field.$wrapper.html(tc_st_muted(__("Loading...")));
	const result = await tc_st_get(TC_ST_BOM, { set_type: frm.doc.name, version });
	if (token !== frm.tc_view_token || frm.tc_ctx !== ctx) {
		return;
	}
	if (!result.ok) {
		field.$wrapper.html(tc_st_block(result.error));
		return;
	}
	frm.tc_view = result.data;
	frm.tc_view_version = result.data.bom_version;
	tc_st_render_bom(frm, ctx, result.data);
}

// --- Sửa BOM: phiên bản mới (copy-on-edit) -------------------------------------------------------------------

function tc_st_latest(ctx) {
	return ctx.versions && ctx.versions.length ? ctx.versions[0].bom_version : 0;
}

function tc_st_edit_dialog(frm) {
	const ctx = frm.tc_ctx;
	const view = frm.tc_view;
	const latest = tc_st_latest(ctx);
	const from = view ? view.bom_version : 0;
	let intro = from
		? __("Lines copied from BOM version {0}.", [from])
		: __("This set type has no BOM line yet.");
	if (from && from !== latest) {
		intro += ` ${__("The latest version is {0}.", [latest])}`;
	}
	intro += ` ${__("Saving creates BOM version {0}; saved versions are never changed.", [
		latest + 1,
	])}`;
	let editor;
	const dialog = new frappe.ui.Dialog({
		title: __("Edit BOM of {0}", [frm.doc.name]),
		size: "extra-large",
		fields: [
			{ fieldname: "intro", fieldtype: "HTML", options: tc_st_muted(intro) },
			{ fieldname: "lines", fieldtype: "HTML" },
			{ fieldname: "section_meta", fieldtype: "Section Break" },
			{
				fieldname: "effective_from",
				fieldtype: "Date",
				label: __("Effective from"),
				default: frappe.datetime.get_today(),
				// ngày quá khứ không chọn được trên lịch; server vẫn kiểm (BOM_EFFECTIVE_DATE_INVALID)
				min_date: frappe.datetime.str_to_obj(frappe.datetime.get_today()),
				description: __("Today applies at once; a later date schedules the version."),
			},
			{ fieldname: "column_meta", fieldtype: "Column Break" },
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason for the change"),
				description: __("Required. Shown in the version history and on the count sheet."),
			},
			{ fieldname: "section_error", fieldtype: "Section Break" },
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Save new version"),
		async primary_action(values) {
			editor.clear_errors();
			const sent = editor.collect();
			const result = await tc_st_dialog_send(dialog, TC_ST_SAVE_BOM, {
				set_type: frm.doc.name,
				lines: sent.lines,
				effective_from: values.effective_from || "",
				reason: values.reason || "",
				base_version: latest,
			});
			if (result.ok) {
				dialog.hide();
				const saved = result.data.bom_version;
				frappe.show_alert({
					message: __("BOM version {0} saved: {1}.", [
						saved,
						tc_st_status_text(result.data.status),
					]),
					indicator: "green",
				});
				frm.tc_view_version = saved;
				frm.reload_doc();
				// UC-02 A1: lưu xong mở so sánh với phiên bản đã chép
				if (from) {
					tc_st_compare_dialog(frm, from, saved);
				}
				return;
			}
			if (result.error && result.error.code === "BOM_VERSION_CONFLICT") {
				tc_st_conflict(frm, dialog, result.error);
				return;
			}
			editor.show_errors(result.error, sent.sent);
		},
	});
	editor = tc_st_editor(dialog.fields_dict.lines.$wrapper, view ? view.lines : []);
	dialog.show();
}

function tc_st_conflict(frm, dialog, error) {
	const latest = (error.items && error.items[0] && error.items[0].latest) || "?";
	const box = dialog.fields_dict.tc_error.$wrapper;
	box.html(
		tc_st_block({
			title: error.title,
			reason: __("A newer BOM version exists (v{0}). Reload, then make your change again.", [
				latest,
			]),
			action: error.action,
		}) +
			`<p><button type="button" class="btn btn-primary btn-sm tc-st-reload">${tc_st_escape(
				__("Reload BOM")
			)}</button></p>`
	);
	box.find(".tc-st-reload").on("click", () => {
		dialog.hide();
		frm.tc_view_version = null;
		frm.reload_doc();
	});
}

// --- So sánh hai phiên bản -----------------------------------------------------------------------------------

function tc_st_version_options(ctx, extra) {
	const numbers = new Set((ctx.versions || []).map((row) => row.bom_version));
	extra.filter(Boolean).forEach((number) => numbers.add(number));
	return Array.from(numbers)
		.sort((a, b) => b - a)
		.map((number) => {
			const row = tc_st_version_row(ctx, number);
			return {
				value: String(number),
				label: row
					? __("Version {0} · {1} · {2}", [
							number,
							tc_st_status_text(row.status),
							tc_st_date(row.effective_from),
					  ])
					: __("Version {0}", [number]),
			};
		});
}

function tc_st_compare_html(data) {
	const labels = data.labels || {};
	const rows = [];
	const add = (kind, item, detail) =>
		rows.push(`<tr>
			<td><strong>${tc_st_escape(labels[kind] || kind)}</strong></td>
			<td>${tc_st_mono(item.instrument)}</td>
			<td>${tc_st_escape(item.instrument_name)}</td>
			<td>${tc_st_escape(detail)}</td>
		</tr>`);
	(data.added || []).forEach((item) =>
		add("added", item, __("Position {0}, quantity {1}", [item.position, item.qty]))
	);
	(data.removed || []).forEach((item) =>
		add("removed", item, __("Position {0}, quantity {1}", [item.position, item.qty]))
	);
	(data.qty_changed || []).forEach((item) =>
		add("qty_changed", item, __("Quantity {0} → {1}", [item.from_qty, item.to_qty]))
	);
	(data.moved || []).forEach((item) =>
		add("moved", item, __("Position {0} → {1}", [item.from_position, item.to_position]))
	);
	const side = (row) =>
		__("version {0} ({1}, effective from {2})", [
			row.bom_version,
			tc_st_status_text(row.status),
			tc_st_date(row.effective_from) || "-",
		]);
	let html = `<p>${tc_st_escape(
		__("From {0} to {1}.", [side(data.from_version), side(data.to_version)])
	)}</p>`;
	html += rows.length
		? `<table class="table table-bordered table-sm">
			<thead><tr>
				<th>${tc_st_escape(__("Change type"))}</th>
				<th>${tc_st_escape(__("Instrument code"))}</th>
				<th>${tc_st_escape(__("Instrument name"))}</th>
				<th>${tc_st_escape(__("Change detail"))}</th>
			</tr></thead><tbody>${rows.join("")}</tbody></table>`
		: tc_st_muted(__("No line differs."));
	html += `<p>${tc_st_escape(
		__("{0} instruments unchanged in both versions.", [data.unchanged])
	)}</p>`;
	return html;
}

function tc_st_compare_dialog(frm, from, to) {
	const ctx = frm.tc_ctx || { versions: [] };
	const options = tc_st_version_options(ctx, [from, to]);
	const latest = Number(options.length ? options[0].value : 0);
	const second = Number(options.length > 1 ? options[1].value : 0);
	const effective = ctx.effective_version && ctx.effective_version !== latest;
	const default_from = from || (effective ? ctx.effective_version : second);
	const dialog = new frappe.ui.Dialog({
		title: __("Compare BOM versions of {0}", [frm.doc.name]),
		size: "large",
		fields: [
			{
				fieldname: "from_version",
				fieldtype: "Select",
				label: __("From version"),
				options,
				default: String(default_from || ""),
			},
			{ fieldname: "column_versions", fieldtype: "Column Break" },
			{
				fieldname: "to_version",
				fieldtype: "Select",
				label: __("To version"),
				options,
				default: String(to || latest || ""),
			},
			{ fieldname: "section_result", fieldtype: "Section Break" },
			{ fieldname: "result", fieldtype: "HTML" },
		],
		primary_action_label: __("Compare"),
		primary_action: () => run(),
	});
	async function run() {
		const values = dialog.get_values(true) || {};
		const box = dialog.fields_dict.result.$wrapper;
		box.html(tc_st_muted(__("Loading...")));
		const result = await tc_st_get(TC_ST_COMPARE, {
			set_type: frm.doc.name,
			from_version: values.from_version || "",
			to_version: values.to_version || "",
		});
		box.html(result.ok ? tc_st_compare_html(result.data) : tc_st_block(result.error));
	}
	dialog.show();
	if (default_from && (to || latest)) {
		// giá trị mặc định của Select được đặt sau khi vẽ: đặt rõ rồi mới so sánh
		Promise.resolve(
			dialog.set_values({
				from_version: String(default_from),
				to_version: String(to || latest),
			})
		).then(run);
	}
}

// --- In phiếu kiểm đếm ----------------------------------------------------------------------------------------

function tc_st_print_dialog(frm) {
	const ctx = frm.tc_ctx;
	const options = tc_st_version_options(ctx, []);
	const dialog = new frappe.ui.Dialog({
		title: __("Print count sheet of {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "version",
				fieldtype: "Select",
				label: __("BOM version"),
				options,
				default: String(ctx.effective_version || (options[0] && options[0].value) || ""),
			},
		],
		primary_action_label: __("Open PDF"),
		primary_action(values) {
			const query = new URLSearchParams({ set_type: frm.doc.name, version: values.version });
			window.open(
				`/api/method/${TC_ST_COUNT_SHEET}?${query.toString()}`,
				"_blank",
				"noopener"
			);
			dialog.hide();
		},
	});
	dialog.show();
}

// --- Lịch sử và sao chép loại bộ ------------------------------------------------------------------------------

function tc_st_render_history(frm, ctx) {
	const field = frm.fields_dict.history_html;
	if (!field) {
		return;
	}
	if (!(ctx.versions || []).length) {
		field.$wrapper.html(tc_st_muted(__("No BOM version yet.")));
		return;
	}
	const rows = ctx.versions
		.map(
			(row) => `<tr>
				<td class="text-right">${tc_st_escape(row.bom_version)}</td>
				<td>${tc_st_escape(tc_st_date(row.effective_from))}</td>
				<td>${tc_st_status(row.status)}</td>
				<td>${tc_st_escape(row.reason)}</td>
				<td class="text-right">${tc_st_escape(row.based_on_version || "-")}</td>
				<td>${tc_st_escape(tc_st_user(row.created_by))}</td>
				<td>${tc_st_escape(tc_st_datetime(row.created_on))}</td>
				<td class="text-right">${tc_st_escape(row.line_count)}</td>
				<td class="text-right">${tc_st_escape(row.total_qty)}</td>
			</tr>`
		)
		.join("");
	field.$wrapper.html(`<table class="table table-bordered table-sm">
		<thead><tr>
			<th class="text-right">${tc_st_escape(__("BOM version"))}</th>
			<th>${tc_st_escape(__("Effective from"))}</th>
			<th>${tc_st_escape(__("Version status"))}</th>
			<th>${tc_st_escape(__("Reason for the change"))}</th>
			<th class="text-right">${tc_st_escape(__("Based on version"))}</th>
			<th>${tc_st_escape(__("Saved by"))}</th>
			<th>${tc_st_escape(__("Saved at"))}</th>
			<th class="text-right">${tc_st_escape(__("Line count"))}</th>
			<th class="text-right">${tc_st_escape(__("Instrument count"))}</th>
		</tr></thead><tbody>${rows}</tbody></table>`);
}

function tc_st_copy_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Copy set type {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "intro",
				fieldtype: "HTML",
				options: tc_st_muted(
					__(
						"The new set type gets this header (without code, GTIN and photos) and the BOM in effect as its version 1."
					)
				),
			},
			{ fieldname: "type_code", fieldtype: "Data", label: __("New type code") },
			{
				fieldname: "set_type_name",
				fieldtype: "Data",
				label: __("New set type name"),
				default: frm.doc.set_type_name,
			},
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Copy set type"),
		async primary_action(values) {
			const result = await tc_st_dialog_send(dialog, TC_ST_COPY, {
				source: frm.doc.name,
				type_code: values.type_code || "",
				set_type_name: values.set_type_name || "",
			});
			if (result.ok) {
				dialog.hide();
				frappe.show_alert({
					message: __("Set type {0} created as a copy of {1}.", [
						result.data.set_type,
						frm.doc.name,
					]),
					indicator: "green",
				});
				frappe.set_route("Form", frm.doctype, result.data.set_type);
			} else if (result.error && result.error.code === "BOM_LINE_INVALID") {
				dialog.fields_dict.tc_error.$wrapper.append(tc_st_items_html(result.error.items));
			}
		},
	});
	dialog.show();
}

// --- Nút theo quyền do server trả -----------------------------------------------------------------------

// Chỉ gỡ nút do script này thêm: xóa toàn bộ nút của form sẽ xóa cả nút của Client Script khác
function tc_st_add_button(frm, label, action, group) {
	frm.add_custom_button(label, action, group);
	(frm.tc_st_buttons || (frm.tc_st_buttons = [])).push([label, group]);
}

function tc_st_remove_buttons(frm) {
	(frm.tc_st_buttons || []).forEach(([label, group]) => frm.remove_custom_button(label, group));
	frm.tc_st_buttons = [];
}

function tc_st_buttons(frm, ctx) {
	const group = __("BOM");
	const perms = ctx.permissions;
	const has_versions = (ctx.versions || []).length > 0;
	const can_write = perms.can_edit && tc_st_ready();
	// FR-M2-07.8: R02/R10 không mở được form Item của ERPNext → sửa hạn lưu loại gói mặc định ngay tại đây
	if (
		perms.can_set_shelf_life &&
		frm.doc.default_pack_type &&
		tc_st_ready() &&
		tracecore.shelf_life
	) {
		tc_st_add_button(frm, __("Set pack type shelf life"), () =>
			tracecore.shelf_life.dialog({
				item: frm.doc.default_pack_type,
				current_days: (ctx.shelf_life || {}).pack_type_days,
				on_saved: () => frm.reload_doc(),
			})
		);
	}
	if (can_write) {
		tc_st_add_button(frm, __("Edit BOM"), () => tc_st_edit_dialog(frm), group);
	}
	if ((ctx.versions || []).length > 1) {
		tc_st_add_button(frm, __("Compare versions"), () => tc_st_compare_dialog(frm), group);
	}
	if (has_versions) {
		tc_st_add_button(frm, __("Print count sheet"), () => tc_st_print_dialog(frm), group);
	}
	if (can_write && has_versions) {
		tc_st_add_button(frm, __("Copy set type"), () => tc_st_copy_dialog(frm));
	}
	// FEAT-016 (SCR-03): cấp Set ID cho loại bộ đang xem, cùng hộp thoại với list Set Unit (tc_set_unit.js); quyền theo
	// form_context của Set Unit, server kiểm lại BOM hiệu lực và role
	if (ctx.effective_version && tc_st_ready() && tracecore.set_unit) {
		tracecore.set_unit.context().then((result) => {
			if (result.ok && result.data.permissions.can_issue && frm.tc_ctx === ctx) {
				tc_st_add_button(frm, __("Issue Set IDs"), () =>
					tracecore.set_unit.issue_dialog({ set_type: frm.doc.name })
				);
			}
		});
	}
}

function tc_st_render_state(frm, html) {
	["shelf_life_html", "tray_html", "bom_html", "history_html"].forEach((fieldname) => {
		const field = frm.fields_dict[fieldname];
		if (field) {
			field.$wrapper.html(html);
		}
	});
}

async function tc_st_load(frm) {
	const token = (frm.tc_ctx_token = (frm.tc_ctx_token || 0) + 1);
	tc_st_render_state(frm, tc_st_muted(__("Loading...")));
	const result = await tc_st_get(TC_ST_CONTEXT, { set_type: frm.doc.name });
	if (token !== frm.tc_ctx_token || frm.is_new()) {
		return; // form đã chuyển bản ghi hoặc đã tải lại
	}
	if (!result.ok) {
		tc_st_render_state(frm, tc_st_block(result.error));
		return;
	}
	const ctx = result.data;
	frm.tc_ctx = ctx;
	tc_st_render_shelf_life(frm, ctx);
	tc_st_render_indicators(frm, ctx);
	tc_st_render_warnings(frm, ctx);
	tc_st_render_photos(frm, ctx);
	tc_st_render_history(frm, ctx);
	tc_st_remove_buttons(frm);
	tc_st_buttons(frm, ctx);
	tc_st_render_gtin(frm, ctx);
	const known = tc_st_version_row(ctx, frm.tc_view_version);
	const version = known
		? frm.tc_view_version
		: ctx.effective_version || tc_st_latest(ctx) || null;
	await tc_st_show_version(frm, version);
}

async function tc_st_new_form_gtin(frm) {
	const { ok, data: status } = await tc_st_get(TC_ST_GTIN_STATUS, {});
	if (ok && frm.is_new()) {
		frm.set_intro(status.prefix ? "" : tc_st_escape(tc_st_prefix_missing_text()), "orange");
		frm.set_df_property(
			"gtin",
			"description",
			status.prefix ? __("Leave blank to issue the next GTIN-14 automatically.") : ""
		);
	}
}

function tc_st_new_form(frm) {
	tc_st_new_form_gtin(frm);
	// FR-M1-03.1: loại bộ chỉ tạo cùng BOM v1 → nút lưu mặc định thay bằng hộp thoại nhập dòng BOM
	frm.disable_save();
	frm.tc_st_new_mode = true;
	frm.page.set_primary_action(__("Save and create BOM v1"), () => tc_st_create_dialog(frm));
	tc_st_render_state(frm, "");
	const bom = frm.fields_dict.bom_html;
	if (bom) {
		bom.$wrapper.html(
			tc_st_muted(__("The BOM is entered when you press Save and create BOM v1."))
		);
	}
	const tray = frm.fields_dict.tray_html;
	if (tray) {
		tray.$wrapper.html(tc_st_muted(__("Add tray photos after the set type is created.")));
	}
}

frappe.ui.form.on("Instrument Set Type", {
	setup(frm) {
		// chỉ gợi ý loại gói dùng được, kèm số ngày hạn lưu (server lọc, cùng tiêu chí với kiểm khi lưu); khoa qua query
		// riêng vì R02/R10 không có quyền đọc Department/Item của ERPNext. Bỏ kiểm Link phía client
		// (frappe.client.validate_link cần quyền đó); server vẫn kiểm Link tồn tại và luật loại gói khi lưu.
		frm.set_query("default_pack_type", () => ({ query: TC_ST_PACK_QUERY }));
		frm.set_query("department", () => ({ query: TC_ST_DEPARTMENT_QUERY }));
		["default_pack_type", "department"].forEach((fieldname) =>
			frm.set_df_property(fieldname, "ignore_link_validation", 1)
		);
	},

	refresh(frm) {
		tc_st_remove_buttons(frm);
		if (frm.is_new()) {
			tc_st_new_form(frm);
			return;
		}
		if (frm.tc_st_new_mode) {
			frm.tc_st_new_mode = false;
			frm.enable_save();
		}
		if (frm.tc_ctx && frm.tc_ctx.set_type !== frm.doc.name) {
			frm.tc_view_version = null;
		}
		tc_st_load(frm);
	},

	validate(frm) {
		// đường lưu khác (phím tắt, script khác) cho form mới: mở hộp thoại tạo cùng BOM v1 thay vì lưu thường
		if (frm.is_new()) {
			frappe.validated = false;
			tc_st_create_dialog(frm);
		}
	},
});
