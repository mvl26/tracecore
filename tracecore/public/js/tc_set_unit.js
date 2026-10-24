/* global tracecore */
// Desk SCR-03 dùng chung (FEAT-016 Task 7; UC-03; FR-M1-05, .1, .3, .4): hộp thoại "Cấp Set ID" (list Set Unit và form
// loại bộ), hộp thoại in thẻ kim loại / nhãn khay (form Set Unit và thao tác hàng loạt của list), bảng kết quả in theo
// từng nhãn (hỏi lại print_status), tải CSV khắc. Nạp trên mọi trang Desk qua tracecore.bundle.js.
// Dữ liệu, giới hạn (số bộ một lô, độ dài lý do, cơ số tối đa), quyền và máy in gợi ý đến từ
// tracecore.v1.set_unit.form_context: JS không chép hằng số nghiệp vụ; mọi kiểm tra nằm ở server.
// Ghi qua tracecore.codes.send (tc_codes.js): mỗi thao tác một khóa X-Idempotency-Key + client_ts có offset; sau lỗi
// mạng/gateway, bấm lại với cùng nội dung gửi lại đúng request cũ nên server không cấp/in hai lần.
// Lỗi chặn trong hộp thoại: khối đỏ inline (kết quả → lý do → hành động), các dòng lỗi liệt kê ngay dưới.

frappe.provide("tracecore.set_unit");

const TC_SU_CONTEXT = "tracecore.v1.set_unit.form_context";
const TC_SU_CREATE = "tracecore.v1.set_unit.create_batch";
const TC_SU_PRINT = "tracecore.v1.set_unit.print_tags";
const TC_SU_REPRINT = "tracecore.v1.set_unit.reprint_tag";
const TC_SU_CANCEL = "tracecore.v1.set_unit.cancel_print";
const TC_SU_STATUS = "tracecore.v1.set_unit.print_status";
const TC_SU_CSV = "tracecore.v1.set_unit.batch_csv";
const TC_SU_SET_TYPE_CONTEXT = "tracecore.v1.set_type.form_context";
const TC_SU_DEPARTMENT_QUERY = "tracecore.v1.set_type.department_query";

// Màu của chỉ báo trạng thái Set Unit; nhãn luôn là chữ đã dịch (không chỉ màu)
const TC_SU_STATUS_COLORS = {
	New: "blue",
	"In Circulation": "green",
	Processing: "orange",
	Reprocess: "red",
	Sterile: "green",
	"At Department": "purple",
	"Awaiting Receipt": "orange",
	"End of Life": "gray",
	Disposed: "gray",
};

function tc_su_ready() {
	return Boolean(window.tracecore && tracecore.codes && tracecore.codes.get);
}

function tc_su_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_su_mono(text) {
	return `<span style="font-family: var(--tc-font-mono)">${tc_su_escape(text)}</span>`;
}

function tc_su_muted(text) {
	return `<p class="text-muted">${tc_su_escape(text)}</p>`;
}

function tc_su_not_loaded() {
	return {
		title: __("Not available"),
		reason: __("The TraceCore Desk script is not loaded."),
		action: __("Reload the page and try again."),
	};
}

function tc_su_block(error) {
	if (tc_su_ready()) {
		return tracecore.codes.block_html(error);
	}
	return `<div class="alert alert-danger" role="alert"><p><strong>${tc_su_escape(
		error.title
	)}</strong></p><p>${tc_su_escape(error.reason)}</p><p>${tc_su_escape(error.action)}</p></div>`;
}

function tc_su_warning_html(lines) {
	const text = lines.filter(Boolean);
	if (!text.length) {
		return "";
	}
	return `<div class="alert alert-warning" role="status">${text
		.map((line) => `<p>${tc_su_escape(line)}</p>`)
		.join("")}</div>`;
}

// dd/mm/yyyy HH:mm theo giờ hệ thống do server trả (không đổi múi giờ)
tracecore.set_unit.datetime = function (value) {
	return value ? moment(String(value), "YYYY-MM-DD HH:mm:ss").format("DD/MM/YYYY HH:mm") : "";
};

tracecore.set_unit.user = function (user) {
	return user ? (frappe.user_info(user) || {}).fullname || user : "";
};

tracecore.set_unit.status_color = function (status) {
	return TC_SU_STATUS_COLORS[status] || "gray";
};

tracecore.set_unit.status_html = function (status) {
	return `<span class="indicator-pill ${tracecore.set_unit.status_color(status)}">${tc_su_escape(
		__(status, null, "Set Unit")
	)}</span>`;
};

tracecore.set_unit.set_link = function (name) {
	return `<a href="/app/set-unit/${encodeURIComponent(
		name
	)}" target="_blank" rel="noopener">${tc_su_mono(name)}</a>`;
};

function tc_su_kind_label(ctx, kind) {
	const row = ((ctx && ctx.kinds) || []).find((item) => item.kind === kind);
	return row ? row.label : kind;
}

// --- Gọi server -----------------------------------------------------------------------------------------------

tracecore.set_unit.context = function (set_unit) {
	if (!tc_su_ready()) {
		return Promise.resolve({ ok: false, error: tc_su_not_loaded() });
	}
	return tracecore.codes.get(TC_SU_CONTEXT, set_unit ? { set_unit } : {});
};

// Ghi từ một hộp thoại/nút: cùng nội dung sau lỗi mạng/gateway → gửi lại đúng request cũ (cùng khóa idempotent);
// nội dung khác hoặc server đã trả lời → request mới
tracecore.set_unit.send = async function (holder, method, args) {
	if (!tc_su_ready()) {
		return { ok: false, error: tc_su_not_loaded() };
	}
	const signature = `${method} ${JSON.stringify(args)}`;
	if (!holder.tc_su_pending || holder.tc_su_pending.signature !== signature) {
		holder.tc_su_pending = { signature, request: tracecore.codes.new_request(args) };
	}
	const result = await tracecore.codes.send(method, holder.tc_su_pending.request);
	if (!result.network) {
		holder.tc_su_pending = null;
	}
	if (!result.ok && result.error && !result.error.code && !result.network) {
		// lỗi kiểm tra của Frappe (tham số, quyền): hành động chung
		result.error.action = __("Correct the data shown in the message, then try again.");
	}
	return result;
};

// Các dòng đi kèm lỗi chặn: dòng BOM, bộ cần in lại / đang chờ in, máy in không có địa chỉ mạng, mẫu nhãn lỗi
tracecore.set_unit.items_html = function (error, ctx) {
	const items = (error && error.items) || [];
	if (!items.length) {
		return "";
	}
	const lines = items.map((item) => {
		if (typeof item === "string") {
			return tc_su_mono(item);
		}
		if (error.code === "SET_TYPE_BOM_INVALID") {
			const parts = [];
			if (item.row) {
				parts.push(tc_su_escape(__("Row {0}", [item.row])));
			}
			if (item.instrument) {
				parts.push(tc_su_mono(item.instrument));
			}
			parts.push(tc_su_escape(item.message));
			return parts.join(" — ");
		}
		if (item.set_unit) {
			const kind = item.kind ? ` — ${tc_su_escape(tc_su_kind_label(ctx, item.kind))}` : "";
			return `${tracecore.set_unit.set_link(item.set_unit)}${kind}`;
		}
		if (item.expected || item.scanned) {
			return tc_su_escape(
				__("Expected {0}, scanned {1}", [item.expected || "-", item.scanned || "-"])
			);
		}
		if (item.kind) {
			return tc_su_escape(tc_su_kind_label(ctx, item.kind));
		}
		return tc_su_escape(item.message || JSON.stringify(item));
	});
	let html = `<ul class="text-danger">${lines.map((line) => `<li>${line}</li>`).join("")}</ul>`;
	if (error.code === "REASON_REQUIRED") {
		html += tc_su_muted(
			__(
				"Open each set listed above and use Reprint on its form: a reprint needs a reason for each set."
			)
		);
	}
	return html;
};

tracecore.set_unit.error_html = function (error, ctx) {
	return tc_su_block(error) + tracecore.set_unit.items_html(error, ctx);
};

// --- Tải CSV khắc (GET trả file; lỗi trả JSON) -------------------------------------------------------------------

function tc_su_csv_filename(response) {
	const header = response.headers.get("Content-Disposition") || "";
	const match = header.match(/filename="?([^";]+)"?/);
	const name = match ? match[1].replace(/[^\w.-]/g, "") : "";
	return name.endsWith(".csv") ? name : "set-ids.csv";
}

// Trả null khi đã tải, ngược lại {title, reason, action}
tracecore.set_unit.download_csv = async function (set_units) {
	if (!tc_su_ready()) {
		return tc_su_not_loaded();
	}
	const query = new URLSearchParams({ set_units: JSON.stringify(set_units) });
	let response;
	try {
		response = await fetch(`/api/method/${TC_SU_CSV}?${query.toString()}`, {
			method: "GET",
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
		});
	} catch (e) {
		return {
			title: __("Server not reachable"),
			reason: __("The server could not be reached."),
			action: __("Try again."),
		};
	}
	const type = response.headers.get("Content-Type") || "";
	if (response.ok && !type.includes("json")) {
		const blob = await response.blob();
		const url = URL.createObjectURL(blob);
		const link = document.createElement("a");
		link.href = url;
		link.download = tc_su_csv_filename(response);
		document.body.appendChild(link);
		link.click();
		link.remove();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
		return null;
	}
	const body = await response.json().catch(() => null);
	const result = (body && body.message) || {};
	if (result.error) {
		return result.error;
	}
	return {
		title: __("Request refused"),
		reason: __("The server refused the request (HTTP {0}).", [response.status]),
		action: __("Reload the page and try again."),
	};
};

// --- Kết quả in theo từng nhãn ----------------------------------------------------------------------------------

// Trạng thái một nhãn, luôn có chữ
tracecore.set_unit.job_state = function (job) {
	if (!job) {
		return { indicator: "gray", label: __("Not requested") };
	}
	if (job.status === "Printed") {
		return { indicator: "green", label: __("Printed") };
	}
	if (job.status === "Failed") {
		return {
			indicator: "red",
			label: __("Not printed: {0}", [job.error || __("the printer did not respond")]),
		};
	}
	if (job.status === "Waiting") {
		return { indicator: "orange", label: __("Waiting for the Station Agent") };
	}
	if (job.poll_done) {
		return { indicator: "orange", label: __("No result yet") };
	}
	return { indicator: "blue", label: __("Queued for printing") };
};

function tc_su_job_cell(job) {
	const state = tracecore.set_unit.job_state(job);
	const ref = job ? `<br><small class="text-muted">${tc_su_escape(job.print_job)}</small>` : "";
	return `<span class="indicator-pill ${state.indicator}">${tc_su_escape(
		state.label
	)}</span>${ref}`;
}

function tc_su_all_jobs(model) {
	const jobs = [];
	model.rows.forEach((row) =>
		model.kinds.forEach((kind) => row.jobs[kind] && jobs.push(row.jobs[kind]))
	);
	return jobs;
}

function tc_su_failed(model) {
	const failed = {};
	model.rows.forEach((row) =>
		model.kinds.forEach((kind) => {
			const job = row.jobs[kind];
			if (job && job.status === "Failed") {
				(failed[kind] || (failed[kind] = [])).push(row.set_unit);
			}
		})
	);
	return failed;
}

function tc_su_results_html(model) {
	const jobs = tc_su_all_jobs(model);
	const count = (status) => jobs.filter((job) => job.status === status).length;
	let html = model.intro ? `<p>${tc_su_escape(model.intro)}</p>` : "";
	if (model.test_labels) {
		html += tc_su_warning_html([
			__(
				"Test site: Set IDs use the GS1 demo prefix and every tag and tray label carries a TEST line. Do not fit them on real sets."
			),
		]);
	}
	html += tc_su_warning_html(
		(model.warnings || []).map((warning) =>
			[warning.title, warning.message || warning.reason, warning.action]
				.filter(Boolean)
				.join(" ")
		)
	);
	if (jobs.length) {
		html += `<p>${tc_su_escape(
			__("{0} of {1} labels printed; {2} not printed; {3} waiting or queued.", [
				count("Printed"),
				jobs.length,
				count("Failed"),
				count("Queued") + count("Waiting"),
			])
		)}</p>`;
	}
	const head = model.kinds
		.map((kind) => `<th>${tc_su_escape(tc_su_kind_label(model.ctx, kind))}</th>`)
		.join("");
	const body = model.rows
		.map(
			(row, index) => `<tr>
				<td class="text-right">${index + 1}</td>
				<td>${tracecore.set_unit.set_link(row.set_unit)}</td>
				${model.kinds.map((kind) => `<td>${tc_su_job_cell(row.jobs[kind])}</td>`).join("")}
			</tr>`
		)
		.join("");
	html += `<table class="table table-bordered table-sm">
		<thead><tr><th class="text-right">#</th><th>${tc_su_escape(__("Set ID"))}</th>${head}</tr></thead>
		<tbody>${body}</tbody>
	</table>`;
	const buttons = [];
	if (model.ctx.permissions.can_issue) {
		buttons.push(
			`<button type="button" class="btn btn-default btn-sm tc-su-csv">${tc_su_escape(
				__("Download engraving CSV")
			)}</button>`
		);
	}
	if (Object.keys(tc_su_failed(model)).length && model.ctx.permissions.can_print) {
		buttons.push(
			`<button type="button" class="btn btn-default btn-sm tc-su-refill">${tc_su_escape(
				__("Print failed labels again")
			)}</button>`
		);
	}
	html += buttons.length ? `<p>${buttons.join(" ")}</p>` : "";
	html += `<div class="tc-su-result-error"></div>`;
	return html;
}

function tc_su_render_results(dialog, model) {
	const wrapper = dialog.fields_dict.result.$wrapper;
	wrapper.html(tc_su_results_html(model));
	wrapper.find(".tc-su-csv").on("click", async () => {
		const error = await tracecore.set_unit.download_csv(model.rows.map((row) => row.set_unit));
		wrapper
			.find(".tc-su-result-error")
			.html(error ? tracecore.set_unit.error_html(error) : "");
	});
	wrapper.find(".tc-su-refill").on("click", () => tc_su_refill(dialog, model));
}

const tc_su_sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Hỏi kết quả các nhãn còn Queued tới khi xong hoặc hết số lần; vòng mới (in bù) đổi token, vòng cũ dừng
async function tc_su_poll(dialog, model) {
	const token = (dialog.tc_su_poll_token = (dialog.tc_su_poll_token || 0) + 1);
	const polled = new Set();
	for (let round = 0; round < tracecore.codes.POLL_ROUNDS; round++) {
		const queued = tc_su_all_jobs(model).filter((job) => job.status === "Queued");
		// dialog.display chỉ thành true sau hiệu ứng mở hộp thoại: dùng cờ đóng của chính bảng kết quả
		if (!queued.length || model.closed) {
			break;
		}
		queued.forEach((job) => polled.add(job));
		await tc_su_sleep(tracecore.codes.POLL_INTERVAL_MS);
		if (dialog.tc_su_poll_token !== token) {
			return;
		}
		const response = await tracecore.codes.get(TC_SU_STATUS, {
			names: queued.map((job) => job.print_job),
		});
		if (dialog.tc_su_poll_token !== token) {
			return;
		}
		if (!response.ok) {
			break;
		}
		queued.forEach((job) => {
			const fresh = response.data.jobs[String(job.print_job)];
			if (fresh) {
				Object.assign(job, { status: fresh.status, error: fresh.error });
			}
		});
		tc_su_render_results(dialog, model);
	}
	polled.forEach((job) => {
		job.poll_done = true;
	});
	tc_su_render_results(dialog, model);
}

function tc_su_merge_jobs(model, jobs) {
	(jobs || []).forEach((job) => {
		const row = model.rows.find((item) => item.set_unit === job.set_unit);
		if (row) {
			row.jobs[job.kind] = Object.assign({}, job);
		}
	});
}

// In bù các nhãn Không in được (mọi bản in trước của loại đó đều Failed → không cần lý do): mỗi loại một lệnh
async function tc_su_refill(dialog, model) {
	const failed = tc_su_failed(model);
	const errors = [];
	for (const kind of Object.keys(failed)) {
		const args = { set_units: failed[kind], kinds: [kind] };
		args[`${kind}_printer`] = model.printers[kind];
		const holder = (model.holders[kind] = model.holders[kind] || {});
		const result = await tracecore.set_unit.send(holder, TC_SU_PRINT, args);
		if (result.ok) {
			tc_su_merge_jobs(model, result.data.jobs);
			model.warnings = (model.warnings || []).concat(result.data.warnings || []);
		} else {
			errors.push(result.error);
		}
	}
	tc_su_render_results(dialog, model);
	dialog.fields_dict.result.$wrapper
		.find(".tc-su-result-error")
		.html(errors.map((error) => tracecore.set_unit.error_html(error, model.ctx)).join(""));
	if (!errors.length) {
		tc_su_poll(dialog, model);
	}
}

// Bảng kết quả: `jobs` = [{set_unit, kind, print_job, status}] của create_batch / print_tags / reprint_tag
tracecore.set_unit.show_results = function (opts) {
	const kinds = (opts.ctx.kinds || [])
		.map((item) => item.kind)
		.filter((kind) => (opts.kinds || []).includes(kind));
	const model = {
		ctx: opts.ctx,
		intro: opts.intro,
		test_labels: opts.ctx.test_labels,
		warnings: opts.warnings || [],
		kinds,
		printers: opts.printers || {},
		holders: {},
		rows: opts.set_ids.map((set_unit) => ({ set_unit, jobs: {} })),
	};
	tc_su_merge_jobs(model, opts.jobs);
	const dialog = new frappe.ui.Dialog({
		title: opts.title,
		size: "large",
		fields: [{ fieldname: "result", fieldtype: "HTML" }],
		primary_action_label: __("Close"),
		primary_action() {
			dialog.hide();
		},
	});
	dialog.onhide = () => {
		model.closed = true; // thôi hỏi kết quả in
		if (opts.on_done) {
			opts.on_done();
		}
	};
	dialog.show();
	tc_su_render_results(dialog, model);
	tc_su_poll(dialog, model);
	return dialog;
};

// --- Chọn loại bản in và máy in -------------------------------------------------------------------------------

function tc_su_printer_options(ctx) {
	// tên máy in do R10 nhập: escape trước khi Select chèn vào DOM
	return (ctx.printers_hint || []).map((printer) => ({
		value: printer.name,
		label: tc_su_escape(
			[printer.name, printer.printer_name, printer.station].filter(Boolean).join(" · ")
		),
	}));
}

// Trường chọn loại bản in (Thẻ kim loại / Nhãn khay) và máy in từng loại; máy in chỉ gồm máy có địa chỉ mạng
function tc_su_print_fields(ctx, checked) {
	const options = tc_su_printer_options(ctx);
	const first = options.length ? options[0].value : "";
	const fields = [];
	(ctx.kinds || []).forEach((item, index) => {
		if (index) {
			fields.push({ fieldname: `column_${item.kind}`, fieldtype: "Column Break" });
		}
		fields.push(
			{
				fieldname: `print_${item.kind}`,
				fieldtype: "Check",
				label: item.label,
				default: checked && options.length ? 1 : 0,
			},
			{
				fieldname: `${item.kind}_printer`,
				fieldtype: "Select",
				label: __("Printer for {0}", [item.label]),
				options,
				default: first,
				depends_on: `eval:doc.print_${item.kind}`,
			}
		);
	});
	return fields;
}

function tc_su_print_note(ctx) {
	if ((ctx.printers_hint || []).length) {
		return tc_su_muted(
			__(
				"Only printers with a network address are listed: the server sends each label to them."
			)
		);
	}
	return tc_su_warning_html([
		__(
			"No printer with a network address is available. Set IDs can be issued without printing; ask R10 to set a printer host and port."
		),
	]);
}

// {kinds, printers, error}: loại đã chọn và máy in tương ứng, hoặc lỗi chặn khi thiếu máy in
function tc_su_chosen_print(ctx, values) {
	const kinds = [];
	const printers = {};
	for (const item of ctx.kinds || []) {
		if (!values[`print_${item.kind}`]) {
			continue;
		}
		const printer = values[`${item.kind}_printer`];
		if (!printer) {
			return {
				error: {
					title: __("Printer missing"),
					reason: __("No printer is selected for {0}.", [item.label]),
					action: __("Choose a printer with a network address, or untick {0}.", [
						item.label,
					]),
				},
			};
		}
		kinds.push(item.kind);
		printers[item.kind] = printer;
	}
	return { kinds, printers };
}

// --- Hộp thoại Cấp Set ID -----------------------------------------------------------------------------------------

function tc_su_cycles_hint(dialog) {
	const field = dialog.fields_dict.max_cycles;
	const cap = dialog.tc_su_cap || {};
	let html = "";
	if (cap.value) {
		html = tc_su_escape(
			cap.source === "Par Level"
				? __("Limit from the Par Level of the set type: {0}.", [cap.value])
				: __("Limit from the lowest max cycles of the instruments in the BOM: {0}.", [
						cap.value,
				  ])
		);
	} else if (dialog.get_value("set_type")) {
		html = tc_su_escape(
			__("No limit defined for this set type: enter the max cycles, 1 to {0}.", [
				dialog.tc_su_ctx.limits.max_cycles_limit,
			])
		);
	}
	const value = Number(dialog.get_value("max_cycles") || 0);
	if (cap.value && value > cap.value) {
		html += `<br><strong class="text-danger">${tc_su_escape(
			__("Higher than the limit {0}: the Set IDs cannot be issued.", [cap.value])
		)}</strong>`;
	}
	field.set_description(html);
}

// preset: loại bộ điền sẵn lúc mở hộp thoại (giá trị mặc định của trường Link chưa đọc được ngay sau show())
async function tc_su_load_set_type(dialog, preset) {
	const set_type = preset || dialog.get_value("set_type");
	const box = dialog.fields_dict.set_type_info.$wrapper;
	dialog.tc_su_cap = null;
	if (!set_type) {
		box.empty();
		tc_su_cycles_hint(dialog);
		return;
	}
	const token = (dialog.tc_su_type_token = (dialog.tc_su_type_token || 0) + 1);
	box.html(tc_su_muted(__("Loading...")));
	const [context, header, issue_ctx] = await Promise.all([
		tracecore.codes.get(TC_SU_SET_TYPE_CONTEXT, { set_type }),
		frappe.db.get_value("Instrument Set Type", set_type, ["department", "set_type_name"]),
		tracecore.codes.get(TC_SU_CONTEXT, { set_type }),
	]);
	if (token !== dialog.tc_su_type_token) {
		return;
	}
	if (!context.ok) {
		box.html(tracecore.set_unit.error_html(context.error, dialog.tc_su_ctx));
		return;
	}
	const row = (header && header.message) || {};
	const cap = (issue_ctx.ok && issue_ctx.data.max_cycles_cap) || {};
	dialog.tc_su_cap = cap;
	box.html(
		context.data.effective_version
			? tc_su_muted(
					__("{0}: BOM version {1} in effect.", [
						row.set_type_name || set_type,
						context.data.effective_version,
					])
			  )
			: tc_su_warning_html([
					__("Set type {0} has no BOM version effective today: it cannot be issued.", [
						set_type,
					]),
			  ])
	);
	// điền sẵn khoa và cơ số khi người dùng chưa tự nhập (hoặc giá trị đang là giá trị điền sẵn lần trước)
	const auto = dialog.tc_su_auto || {};
	const current_department = dialog.get_value("department");
	if (row.department && (!current_department || current_department === auto.department)) {
		await dialog.set_value("department", row.department);
	}
	const current_cycles = dialog.get_value("max_cycles");
	if (cap.value && (!current_cycles || current_cycles === auto.max_cycles)) {
		await dialog.set_value("max_cycles", cap.value);
	}
	dialog.tc_su_auto = { department: row.department, max_cycles: cap.value };
	tc_su_cycles_hint(dialog);
}

function tc_su_issue_args(values, chosen) {
	const args = {
		set_type: values.set_type || "",
		count: values.count === undefined || values.count === null ? "" : String(values.count),
		department: values.department || "",
		max_cycles:
			values.max_cycles === undefined ||
			values.max_cycles === null ||
			values.max_cycles === ""
				? ""
				: String(values.max_cycles),
		origin: values.origin || "New",
		cycles_used: values.origin === "Existing" ? String(values.cycles_used || 0) : "0",
		estimate_reason: values.origin === "Existing" ? values.estimate_reason || "" : "",
		kinds: chosen.kinds,
	};
	chosen.kinds.forEach((kind) => {
		args[`${kind}_printer`] = chosen.printers[kind];
	});
	return args;
}

// opts: {set_type?, on_done?}
tracecore.set_unit.issue_dialog = async function (opts = {}) {
	if (!tc_su_ready()) {
		frappe.msgprint(tc_su_block(tc_su_not_loaded()));
		return null;
	}
	const loaded = await tracecore.set_unit.context();
	if (!loaded.ok) {
		tracecore.codes.show_block(loaded.error);
		return null;
	}
	const ctx = loaded.data;
	if (!ctx.permissions.can_issue) {
		tracecore.codes.show_block({
			title: __("Not permitted"),
			reason: __("Only R02, R10 and the System Manager can issue Set IDs."),
			action: __("Ask R02 to issue the Set IDs."),
		});
		return null;
	}
	const intro = [
		tc_su_muted(
			__(
				"Each set gets a permanent Set ID (GS1 GIAI). Set IDs are never changed or issued again, even after disposal."
			)
		),
	];
	if (ctx.test_labels) {
		intro.push(
			tc_su_warning_html([
				__(
					"Test site: Set IDs use the GS1 demo prefix and every tag and tray label carries a TEST line. Do not fit them on real sets."
				),
			])
		);
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Issue Set IDs"),
		size: "large",
		fields: [
			{ fieldname: "intro", fieldtype: "HTML", options: intro.join("") },
			{
				fieldname: "set_type",
				fieldtype: "Link",
				options: "Instrument Set Type",
				label: __("Set type"),
				default: opts.set_type || "",
				description: __(
					"Only set types with a BOM are suggested; the server checks the BOM in effect today."
				),
				get_query: () => ({ filters: { current_bom_version: [">", 0] } }),
				onchange: () => tc_su_load_set_type(dialog),
			},
			{ fieldname: "set_type_info", fieldtype: "HTML" },
			{
				fieldname: "count",
				fieldtype: "Int",
				label: __("Number of sets"),
				default: 1,
				description: __(
					"From 1 to {0} sets per batch; split larger orders into several batches.",
					[ctx.limits.max_batch]
				),
			},
			{ fieldname: "column_main", fieldtype: "Column Break" },
			{
				fieldname: "department",
				fieldtype: "Link",
				options: "Department",
				label: __("Owning department"),
				description: __(
					"Filled in from the set type; change it if another department owns the sets."
				),
				get_query: () => ({ query: TC_SU_DEPARTMENT_QUERY }),
				ignore_link_validation: 1,
			},
			{ fieldname: "section_cycles", fieldtype: "Section Break", label: __("Cycles") },
			{
				fieldname: "max_cycles",
				fieldtype: "Int",
				label: __("Max cycles"),
				onchange: () => tc_su_cycles_hint(dialog),
			},
			{ fieldname: "column_cycles", fieldtype: "Column Break" },
			{
				fieldname: "origin",
				fieldtype: "Select",
				label: __("Set origin"),
				options: [
					{ value: "New", label: __("New set") },
					{ value: "Existing", label: __("Set already in circulation") },
				],
				default: "New",
			},
			{
				fieldname: "cycles_used",
				fieldtype: "Int",
				label: __("Cycles already used (estimated)"),
				default: 1,
				depends_on: 'eval:doc.origin === "Existing"',
				description: __(
					"Estimated number of cycles the set has been through, at least 1 and below the max cycles. Shown as Estimate on the set."
				),
			},
			{
				fieldname: "estimate_reason",
				fieldtype: "Small Text",
				label: __("Where the estimate comes from"),
				depends_on: 'eval:doc.origin === "Existing"',
				mandatory_depends_on: 'eval:doc.origin === "Existing"',
				description: __("Required, at most {0} characters.", [ctx.limits.reason_max]),
			},
			{ fieldname: "section_print", fieldtype: "Section Break", label: __("Printing") },
			{ fieldname: "print_note", fieldtype: "HTML", options: tc_su_print_note(ctx) },
			...tc_su_print_fields(ctx, true),
			{ fieldname: "section_error", fieldtype: "Section Break" },
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Issue and print"),
		async primary_action() {
			const values = dialog.get_values(true) || {};
			const box = dialog.fields_dict.tc_error.$wrapper;
			if (!values.set_type) {
				box.html(
					tc_su_block({
						title: __("Set IDs not issued"),
						reason: __("No set type is selected."),
						action: __("Choose the set type, then press Issue and print."),
					})
				);
				return;
			}
			const chosen = tc_su_chosen_print(ctx, values);
			if (chosen.error) {
				box.html(tc_su_block(chosen.error));
				return;
			}
			box.empty();
			dialog.disable_primary_action();
			let result;
			try {
				result = await tracecore.set_unit.send(
					dialog,
					TC_SU_CREATE,
					tc_su_issue_args(values, chosen)
				);
			} finally {
				dialog.enable_primary_action();
			}
			if (!result.ok) {
				box.html(tracecore.set_unit.error_html(result.error, ctx));
				return;
			}
			const data = result.data;
			dialog.hide();
			tracecore.set_unit.show_results({
				ctx,
				title: __("Set IDs issued"),
				intro: __("{0} Set IDs issued for set type {1}.", [
					data.set_ids.length,
					data.set_type,
				]),
				set_ids: data.set_ids,
				jobs: data.jobs,
				warnings: data.warnings,
				kinds: chosen.kinds,
				printers: chosen.printers,
				on_done: opts.on_done,
			});
		},
	});
	dialog.tc_su_ctx = ctx;
	dialog.show();
	if (opts.set_type) {
		tc_su_load_set_type(dialog, opts.set_type);
	} else {
		tc_su_cycles_hint(dialog);
	}
	return dialog;
};

// --- In gốc / in bù cho một hoặc nhiều bộ -----------------------------------------------------------------------

// opts: {set_units, ctx, on_done?}
tracecore.set_unit.print_dialog = function (opts) {
	const ctx = opts.ctx;
	const units = opts.set_units;
	const shown = units.map((name) => tc_su_mono(name)).join(", ");
	const dialog = new frappe.ui.Dialog({
		title:
			units.length === 1
				? __("Print tag of {0}", [units[0]])
				: __("Print tags of {0} sets", [units.length]),
		size: "large",
		fields: [
			{
				fieldname: "info",
				fieldtype: "HTML",
				options: `<p>${shown}</p>${tc_su_muted(
					__(
						"First print, or a new print after every earlier print of that label failed. A tag that was already printed is reprinted from the set form with a reason."
					)
				)}${tc_su_print_note(ctx)}`,
			},
			...tc_su_print_fields(ctx, true),
			{ fieldname: "section_error", fieldtype: "Section Break" },
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Print"),
		async primary_action() {
			const values = dialog.get_values(true) || {};
			const box = dialog.fields_dict.tc_error.$wrapper;
			const chosen = tc_su_chosen_print(ctx, values);
			if (chosen.error || !chosen.kinds.length) {
				box.html(
					tc_su_block(
						chosen.error || {
							title: __("Nothing to print"),
							reason: __("No label kind is ticked."),
							action: __("Tick the tag, the tray label or both."),
						}
					)
				);
				return;
			}
			const args = { set_units: units, kinds: chosen.kinds };
			chosen.kinds.forEach((kind) => {
				args[`${kind}_printer`] = chosen.printers[kind];
			});
			box.empty();
			dialog.disable_primary_action();
			let result;
			try {
				result = await tracecore.set_unit.send(dialog, TC_SU_PRINT, args);
			} finally {
				dialog.enable_primary_action();
			}
			if (!result.ok) {
				box.html(tracecore.set_unit.error_html(result.error, ctx));
				return;
			}
			dialog.hide();
			tracecore.set_unit.show_results({
				ctx,
				title: __("Print tags"),
				set_ids: units,
				jobs: result.data.jobs,
				warnings: result.data.warnings,
				kinds: chosen.kinds,
				printers: chosen.printers,
				on_done: opts.on_done,
			});
		},
	});
	dialog.show();
	return dialog;
};

// --- Thao tác hàng loạt trên list Set Unit ------------------------------------------------------------------------

function tc_su_checked(listview, ctx) {
	const names = listview.get_checked_items(true);
	if (!names.length) {
		tracecore.codes.show_block({
			title: __("Nothing selected"),
			reason: __("No set is selected."),
			action: __("Tick the sets first."),
		});
		return null;
	}
	if (names.length > ctx.limits.max_batch) {
		tracecore.codes.show_block({
			title: __("Too many sets"),
			reason: __("{0} sets are selected; at most {1} at a time.", [
				names.length,
				ctx.limits.max_batch,
			]),
			action: __("Select at most {0} sets and try again.", [ctx.limits.max_batch]),
		});
		return null;
	}
	return names;
}

tracecore.set_unit.add_bulk_actions = function (listview, ctx) {
	if (!ctx.permissions.can_print) {
		return;
	}
	listview.page.add_actions_menu_item(
		__("Print tags"),
		() => {
			const names = tc_su_checked(listview, ctx);
			if (names) {
				tracecore.set_unit.print_dialog({
					set_units: names,
					ctx,
					on_done: () => listview.refresh(),
				});
			}
		},
		false
	);
	listview.page.add_actions_menu_item(
		__("Download engraving CSV"),
		async () => {
			const names = tc_su_checked(listview, ctx);
			if (!names) {
				return;
			}
			const error = await tracecore.set_unit.download_csv(names);
			if (error) {
				tracecore.codes.show_block(error);
			}
		},
		false
	);
};

// --- In lại / hủy lệnh in kẹt (form Set Unit) --------------------------------------------------------------------

// opts: {set_unit, ctx, kind?, reason?, on_done?}
tracecore.set_unit.reprint_dialog = function (opts) {
	const ctx = opts.ctx;
	const options = tc_su_printer_options(ctx);
	const suggestions = [__("Tag lost"), __("Tag damaged"), __("Faulty tag – unreadable")];
	const dialog = new frappe.ui.Dialog({
		title: __("Reprint {0}", [opts.set_unit]),
		fields: [
			{
				fieldname: "kind",
				fieldtype: "Select",
				label: __("Label kind"),
				options: (ctx.kinds || []).map((item) => ({
					value: item.kind,
					label: tc_su_escape(item.label),
				})),
				default: opts.kind || ((ctx.kinds || [])[0] || {}).kind,
			},
			{
				fieldname: "printer",
				fieldtype: "Select",
				label: __("Printer"),
				options,
				default: options.length ? options[0].value : "",
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason for reprinting"),
				default: opts.reason || "",
				description: __(
					"Required, at most {0} characters. Recorded with the print job and in the history.",
					[ctx.limits.reason_max]
				),
			},
			{
				fieldname: "suggestions",
				fieldtype: "HTML",
				options: `<p>${suggestions
					.map(
						(text) =>
							`<button type="button" class="btn btn-default btn-sm tc-su-reason" data-reason="${tc_su_escape(
								text
							)}">${tc_su_escape(text)}</button>`
					)
					.join(" ")}</p>`,
			},
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Reprint"),
		async primary_action() {
			const values = dialog.get_values(true) || {};
			const box = dialog.fields_dict.tc_error.$wrapper;
			box.empty();
			dialog.disable_primary_action();
			let result;
			try {
				result = await tracecore.set_unit.send(dialog, TC_SU_REPRINT, {
					set_unit: opts.set_unit,
					kind: values.kind || "",
					printer: values.printer || "",
					reason: values.reason || "",
				});
			} finally {
				dialog.enable_primary_action();
			}
			if (!result.ok) {
				box.html(tracecore.set_unit.error_html(result.error, ctx));
				return;
			}
			dialog.hide();
			tracecore.set_unit.show_results({
				ctx,
				title: __("Reprint {0}", [opts.set_unit]),
				set_ids: [opts.set_unit],
				jobs: [
					{
						set_unit: opts.set_unit,
						kind: values.kind,
						print_job: result.data.print_job,
						status: result.data.status,
					},
				],
				warnings: result.data.warning ? [result.data.warning] : [],
				kinds: [values.kind],
				printers: { [values.kind]: values.printer },
				on_done: opts.on_done,
			});
		},
	});
	dialog.fields_dict.suggestions.$wrapper.find(".tc-su-reason").on("click", (event) => {
		dialog.set_value("reason", $(event.currentTarget).attr("data-reason"));
	});
	dialog.show();
	return dialog;
};

// opts: {set_unit, ctx, kind, on_done?}
tracecore.set_unit.cancel_dialog = function (opts) {
	const dialog = new frappe.ui.Dialog({
		title: __("Cancel pending print of {0}", [opts.set_unit]),
		fields: [
			{
				fieldname: "info",
				fieldtype: "HTML",
				options: tc_su_muted(
					__(
						"The pending print job of {0} is marked as not printed so the label can be printed again. Use this only when the job is stuck.",
						[tc_su_kind_label(opts.ctx, opts.kind)]
					)
				),
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason for cancelling"),
				description: __("Required, at most {0} characters.", [opts.ctx.limits.reason_max]),
			},
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Cancel pending print"),
		async primary_action() {
			const values = dialog.get_values(true) || {};
			const box = dialog.fields_dict.tc_error.$wrapper;
			box.empty();
			dialog.disable_primary_action();
			let result;
			try {
				result = await tracecore.set_unit.send(dialog, TC_SU_CANCEL, {
					set_unit: opts.set_unit,
					kind: opts.kind,
					reason: values.reason || "",
				});
			} finally {
				dialog.enable_primary_action();
			}
			if (!result.ok) {
				box.html(tracecore.set_unit.error_html(result.error, opts.ctx));
				return;
			}
			dialog.hide();
			frappe.show_alert({
				message: __("{0} pending print jobs cancelled.", [result.data.cancelled.length]),
				indicator: "green",
			});
			if (opts.on_done) {
				opts.on_done();
			}
		},
	});
	dialog.show();
	return dialog;
};
