/* global tracecore */
// Desk: in nhãn QR đối tượng và cấp mã cuộn (SCR-33, FEAT-005 Task 5, A-05 R1-R4/R8).
// Nạp trên mọi trang Desk qua app_include_js (tracecore.bundle.js). Hàm dùng chung tracecore.codes.print_dialog cho
// form Equipment / Zone Station / Item (cuộn) và thao tác hàng loạt của list view; các FEAT sau (thẻ nhân viên NV-,
// kệ KE-) chỉ cần gắn nút gọi hàm này.
// fetch thay frappe.call: Frappe tự hiện "Không tìm thấy" cho HTTP 404 và bỏ mất body, trong khi CODE_DISABLED (409),
// EQUIPMENT_NOT_FOUND (404), ROLL_NOT_LABEL (422)… mang body {message: {ok: false, error}} cần hiện cho người dùng.
// Mọi kiểm tra nghiệp vụ (mã Active, thiết bị Retired, số lượng cuộn, máy in hoạt động) nằm ở server.
// Sau khi gửi, hộp thoại hỏi tracecore.v1.print.job_status vài giây một lần để hiện "Đã in" / "Không in được: lý do"
// thay vì dừng ở "Đã xếp hàng" (đường in server là at-least-once, kết quả thật do worker ghi).

frappe.provide("tracecore.codes");

const TC_CODES_LABEL = "tracecore.v1.print.object_label";
const TC_CODES_PREVIEW = "tracecore.v1.print.object_preview";
const TC_CODES_JOB_STATUS = "tracecore.v1.print.job_status";
const TC_CODES_ISSUE_ROLLS = "tracecore.v1.codes.issue_rolls";
const TC_CODES_LIST_ROLLS = "tracecore.v1.codes.list_rolls";

// In nhãn đối tượng và cấp mã cuộn: R10 và System Manager (A-05 R8)
tracecore.codes.PRINT_ROLES = ["TC R10", "System Manager"];
// Giới hạn của thao tác hàng loạt (list view, in lại nhãn cuộn): gửi tuần tự từng mã
tracecore.codes.MAX_BULK = 50;
// Chỉ để hiển thị trong hộp thoại; server (v1.codes.issue_rolls) mới là nơi kiểm tra
tracecore.codes.MAX_ROLLS = 200;
// Hỏi kết quả lệnh in: mỗi 2 giây, tối đa 10 lần (~20 giây) rồi để server tự thử lại
tracecore.codes.POLL_INTERVAL_MS = 2000;
tracecore.codes.POLL_ROUNDS = 10;

tracecore.codes.can_print = function () {
	return frappe.user.has_role(tracecore.codes.PRINT_ROLES);
};

tracecore.codes.uuid = function () {
	if (window.crypto && window.crypto.randomUUID) {
		return window.crypto.randomUUID();
	}
	return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
		const n = Math.floor(Math.random() * 16);
		return (c === "x" ? n : (n & 0x3) | 0x8).toString(16);
	});
};

// ISO 8601 có offset của máy đang dùng, ví dụ 2026-10-21T08:30:00+07:00
tracecore.codes.client_ts = function () {
	const now = new Date();
	const pad = (n) => String(Math.abs(n)).padStart(2, "0");
	const offset = -now.getTimezoneOffset();
	const sign = offset >= 0 ? "+" : "-";
	const local = new Date(now.getTime() + offset * 60000).toISOString().slice(0, 19);
	return `${local}${sign}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(
		Math.abs(offset) % 60
	)}`;
};

// Một thao tác ghi của người dùng = một khóa X-Idempotency-Key + một body (kèm client_ts) cố định. Gửi lại sau lỗi
// mạng dùng NGUYÊN request này (cùng khóa, cùng body) nên server không làm hai lần; thao tác mới mới tạo request mới.
tracecore.codes.new_request = function (args) {
	return {
		key: tracecore.codes.uuid(),
		payload: Object.assign({}, args, { client_ts: tracecore.codes.client_ts() }),
	};
};

function tc_codes_server_message(body) {
	try {
		return JSON.parse(JSON.parse(body._server_messages || "[]")[0] || "{}").message || "";
	} catch (e) {
		return "";
	}
}

// POST một RPC; trả {ok: true, data} hoặc {ok: false, error: {title, reason, action}, network?}.
// `request`: {key, payload} của tracecore.codes.new_request (RPC ghi) hoặc null (RPC chỉ đọc, body = `args`).
tracecore.codes.send = async function (method, request, args) {
	const headers = {
		"Content-Type": "application/json",
		Accept: "application/json",
		"X-Frappe-CSRF-Token": frappe.csrf_token,
	};
	if (request) {
		headers["X-Idempotency-Key"] = request.key;
	}
	try {
		const response = await fetch(`/api/method/${method}`, {
			method: "POST",
			headers,
			body: JSON.stringify(request ? request.payload : args || {}),
		});
		const body = await response.json().catch(() => ({}));
		const result = body.message || {};
		if (result.ok) {
			return { ok: true, data: result };
		}
		if (result.error) {
			return { ok: false, error: result.error };
		}
		// lỗi hệ thống (quyền, tham số sai…): Frappe đóng gói thông báo trong _server_messages
		return {
			ok: false,
			error: {
				title: __("Request refused"),
				reason:
					tc_codes_server_message(body) ||
					__("The server refused the request (HTTP {0}).", [response.status]),
				action: __("Check your permissions and the selected printer, then try again."),
			},
		};
	} catch (e) {
		// không có phản hồi: có thể server đã làm rồi → chỉ gửi lại bằng đúng request cũ
		return {
			ok: false,
			network: true,
			error: {
				title: __("Server not reachable"),
				reason: __("The server could not be reached."),
				action: __("Try again."),
			},
		};
	}
};

// Gọi nhanh: RPC ghi → request mới (khóa mới) cho lần gọi này; RPC chỉ đọc → không khóa.
tracecore.codes.post = function (method, args, write = true) {
	return write
		? tracecore.codes.send(method, tracecore.codes.new_request(args))
		: tracecore.codes.send(method, null, args);
};

function tc_codes_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_codes_mono(text) {
	return `<span style="font-family: var(--tc-font-mono)">${tc_codes_escape(text)}</span>`;
}

// Lỗi chặn: khối đỏ inline theo thứ tự kết quả → lý do → hành động
tracecore.codes.block_html = function (error) {
	return `<div class="alert alert-danger" role="alert">
		<p><strong>${tc_codes_escape(error.title)}</strong></p>
		<p>${tc_codes_escape(error.reason)}</p>
		<p>${tc_codes_escape(error.action)}</p>
	</div>`;
};

tracecore.codes.show_block = function (error) {
	frappe.msgprint({
		title: error.title || __("Request refused"),
		indicator: "red",
		message: `<p>${tc_codes_escape(error.reason)}</p><p>${tc_codes_escape(error.action)}</p>`,
	});
};

// Trạng thái hiện tại của một dòng: rejected (server từ chối / không gửi được) hoặc Queued/Waiting/Printed/Failed
function tc_codes_state(row) {
	if (!row.result.ok) {
		return "rejected";
	}
	return (row.job && row.job.status) || row.result.data.status;
}

// Kết quả một lệnh in, luôn có chữ (không chỉ màu)
function tc_codes_status(row) {
	const state = tc_codes_state(row);
	if (state === "rejected") {
		return {
			indicator: "red",
			label: __("Not printed"),
			detail: [row.result.error.title, row.result.error.reason, row.result.error.action],
		};
	}
	const job = row.result.data.print_job;
	if (state === "Printed") {
		return { indicator: "green", label: __("Printed"), detail: [__("Print job {0}.", [job])] };
	}
	if (state === "Failed") {
		return {
			indicator: "red",
			label: __("Not printed: {0}", [
				(row.job && row.job.error) || __("the printer did not respond"),
			]),
			detail: [
				__("Print job {0}.", [job]),
				__("Check that the printer is on and connected, then print the label again."),
			],
		};
	}
	if (state === "Waiting") {
		const warning = row.result.data.warning || {};
		return {
			indicator: "orange",
			label: __("Waiting for the Station Agent"),
			detail: [warning.title, warning.reason, warning.action, __("Print job {0}.", [job])],
		};
	}
	if (row.poll_done) {
		return {
			indicator: "orange",
			label: __("No result yet"),
			detail: [
				__(
					"The server keeps retrying print job {0} for a few minutes; check the printer.",
					[job]
				),
			],
		};
	}
	return {
		indicator: "blue",
		label: __("Queued for printing"),
		detail: [__("The server sends the label to the printer (print job {0}).", [job])],
	};
}

function tc_codes_result_rows(rows) {
	return rows
		.map((row) => {
			const status = tc_codes_status(row);
			const detail = status.detail
				.filter(Boolean)
				.map((line) => tc_codes_escape(line))
				.join("<br>");
			return `<tr>
				<td>${tc_codes_mono(row.code)}</td>
				<td><span class="indicator-pill ${status.indicator}">${tc_codes_escape(status.label)}</span></td>
				<td>${detail}</td>
			</tr>`;
		})
		.join("");
}

// Tổng kết cả loạt: nhãn chờ agent KHÔNG tính là đã in
function tc_codes_summary(rows) {
	const count = (states) => rows.filter((row) => states.includes(tc_codes_state(row))).length;
	const printed = count(["Printed"]);
	const waiting = count(["Waiting"]);
	const failed = count(["rejected", "Failed"]);
	const pending = count(["Queued"]);
	const parts = [
		__("{0} of {1} labels printed; {2} waiting for the Station Agent; {3} not printed.", [
			printed,
			rows.length,
			waiting,
			failed,
		]),
	];
	if (pending) {
		parts.push(__("{0} labels still being sent to the printer.", [pending]));
	}
	return parts.join(" ");
}

function tc_codes_render_results(dialog, rows) {
	const summary = rows.length > 1 ? `<p>${tc_codes_escape(tc_codes_summary(rows))}</p>` : "";
	dialog.fields_dict.result.$wrapper.html(`${summary}
		<table class="table table-bordered">
			<thead><tr>
				<th>${tc_codes_escape(__("Object code"))}</th>
				<th>${tc_codes_escape(__("Result"))}</th>
				<th>${tc_codes_escape(__("Details"))}</th>
			</tr></thead>
			<tbody>${tc_codes_result_rows(rows)}</tbody>
		</table>`);
}

const tc_codes_sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Hỏi kết quả các lệnh in còn Queued (đường server) tới khi xong hoặc hết số lần; hộp thoại đóng thì thôi hỏi.
async function tc_codes_poll(dialog, rows) {
	for (let round = 0; round < tracecore.codes.POLL_ROUNDS; round++) {
		const queued = rows.filter((row) => tc_codes_state(row) === "Queued");
		if (!queued.length || !dialog.display) {
			break;
		}
		await tc_codes_sleep(tracecore.codes.POLL_INTERVAL_MS);
		const response = await tracecore.codes.send(TC_CODES_JOB_STATUS, null, {
			names: queued.map((row) => row.result.data.print_job),
		});
		if (!response.ok) {
			break; // không hỏi được: dòng còn Queued hiện "Chưa có kết quả"
		}
		for (const row of queued) {
			const job = response.data.jobs[String(row.result.data.print_job)];
			if (job) {
				row.job = job;
			}
		}
		tc_codes_render_results(dialog, rows);
	}
	rows.forEach((row) => {
		row.poll_done = true;
	});
	tc_codes_render_results(dialog, rows);
}

async function tc_codes_load_preview(dialog, label_object, code) {
	const wrapper = dialog.fields_dict.preview.$wrapper;
	wrapper.html(`<p>${tc_codes_escape(__("Loading label preview..."))}</p>`);
	const result = await tracecore.codes.post(TC_CODES_PREVIEW, { label_object, code }, false);
	if (!result.ok) {
		// mã không in được (Disabled, Retired, chưa cấp…): không cho bấm In
		wrapper.html(tracecore.codes.block_html(result.error));
		dialog.get_primary_btn().prop("disabled", true);
		return;
	}
	wrapper.html(
		`<img src="data:image/png;base64,${result.data.png_b64}" alt="${tc_codes_escape(
			__("QR label preview of {0}", [code])
		)}" style="max-width: 100%">`
	);
}

// Mô tả máy in đang chọn: có địa chỉ mạng → server gửi thẳng; không có → lệnh chờ Station Agent
function tc_codes_describe_printer(dialog) {
	const printer = dialog.get_value("printer");
	const field = dialog.fields_dict.printer;
	if (!printer) {
		field.set_description(
			__("Only network printers are listed: the server sends the label straight to them.")
		);
		return;
	}
	frappe.db.get_value("Printer", printer, "host").then((r) => {
		if (dialog.get_value("printer") !== printer) {
			return;
		}
		const host = r && r.message && r.message.host;
		field.set_description(
			host
				? __("Network printer: the server sends the label directly.")
				: __("No network address: the label waits for the Station Agent of this printer.")
		);
	});
}

// In từ Desk đi đường server: chỉ gợi ý và liệt kê máy in đang hoạt động có địa chỉ mạng (A-05 R1)
const TC_CODES_PRINTER_FILTERS = { is_active: 1, host: ["is", "set"] };

function tc_codes_suggest_printer(dialog) {
	frappe.db
		.get_list("Printer", {
			filters: TC_CODES_PRINTER_FILTERS,
			fields: ["name"],
			order_by: "name asc",
			limit: 1,
		})
		.then((rows) => {
			if (rows && rows.length && !dialog.get_value("printer")) {
				dialog.set_value("printer", rows[0].name);
			}
		});
}

// Gửi tuần tự các dòng `rows` (mỗi dòng giữ request riêng: gửi lại sau lỗi mạng dùng đúng khóa cũ)
async function tc_codes_send_rows(dialog, label_object, rows) {
	for (const [index, row] of rows.entries()) {
		dialog.fields_dict.result.$wrapper.html(
			`<p>${tc_codes_escape(
				__("Sending label {0} of {1}...", [index + 1, rows.length])
			)}</p>`
		);
		row.result = await tracecore.codes.send(TC_CODES_LABEL, row.request);
		row.job = null;
		row.poll_done = false;
	}
}

async function tc_codes_send_all(dialog, label_object, codes) {
	const printer = dialog.get_value("printer");
	if (!printer) {
		dialog.fields_dict.result.$wrapper.html(
			tracecore.codes.block_html({
				title: __("Printer missing"),
				reason: __("No printer is selected."),
				action: __("Choose an active printer, then press Print."),
			})
		);
		return;
	}
	const button = dialog.get_primary_btn();
	button.prop("disabled", true);
	// một lần bấm In = một thao tác: mỗi mã một request (khóa idempotent) cố định cho mọi lần gửi lại
	const rows = codes.map((code) => ({
		code,
		request: tracecore.codes.new_request({ label_object, code, printer }),
	}));
	await tc_codes_send_rows(dialog, label_object, rows);
	tc_codes_finish(dialog, label_object, rows);
	button.prop("disabled", false);
}

// Sau khi gửi: còn mã chưa tới được server (lỗi mạng) → nút "Gửi lại" dùng đúng request cũ; hết thì nút "Đóng"
function tc_codes_finish(dialog, label_object, rows) {
	tc_codes_render_results(dialog, rows);
	const unsent = rows.filter((row) => row.result.network);
	if (unsent.length) {
		dialog.set_primary_action(__("Resend unsent labels"), async () => {
			const button = dialog.get_primary_btn();
			button.prop("disabled", true);
			await tc_codes_send_rows(dialog, label_object, unsent);
			tc_codes_finish(dialog, label_object, rows);
			button.prop("disabled", false);
		});
	} else {
		// đã gửi: nút chính thành "Đóng" để không in trùng khi bấm lại
		dialog.set_primary_action(__("Close"), () => dialog.hide());
	}
	tc_codes_poll(dialog, rows);
}

// Hộp thoại in nhãn QR: `code` là một mã (có xem trước) hoặc mảng mã (in cả loạt, không xem trước).
// `frm` có thể null (list view). `title`/`subtitle` chỉ để hiển thị; nội dung nhãn do server dựng.
tracecore.codes.print_dialog = function (frm, label_object, code, title, subtitle) {
	const codes = Array.isArray(code) ? code : [code];
	const single = codes.length === 1;
	const heading = single
		? `<p>${tc_codes_mono(codes[0])} ${tc_codes_escape(title || "")}</p>`
		: `<p>${tc_codes_escape(__("{0} labels", [codes.length]))}: ${codes
				.map((c) => tc_codes_mono(c))
				.join(", ")}</p>`;
	const dialog = new frappe.ui.Dialog({
		title: single ? __("Print QR label") : __("Print QR labels"),
		size: single ? "small" : "large",
		fields: [
			{
				fieldname: "object_info",
				fieldtype: "HTML",
				options: `${heading}${
					subtitle ? `<p class="text-muted">${tc_codes_escape(subtitle)}</p>` : ""
				}`,
			},
			{ fieldname: "preview", fieldtype: "HTML" },
			{
				fieldname: "printer",
				fieldtype: "Link",
				options: "Printer",
				label: __("Printer"),
				reqd: 1,
				get_query: () => ({ filters: TC_CODES_PRINTER_FILTERS }),
				onchange: () => tc_codes_describe_printer(dialog),
			},
			{ fieldname: "result", fieldtype: "HTML" },
		],
		primary_action_label: single ? __("Print") : __("Print {0} labels", [codes.length]),
		primary_action() {
			tc_codes_send_all(dialog, label_object, codes);
		},
	});
	dialog.show();
	tc_codes_describe_printer(dialog);
	tc_codes_suggest_printer(dialog);
	if (single) {
		tc_codes_load_preview(dialog, label_object, codes[0]);
	}
	return dialog;
};

// Nút "In nhãn QR" trên form: chỉ khi mã còn Active; mã Disabled → không có nút, kèm dòng giải thích.
// `blocked`: lý do chặn biết trước ở client (thiết bị Retired), khi đó không cần tra sổ mã.
tracecore.codes.add_print_button = function (frm, label_object, title, subtitle, blocked) {
	if (frm.is_new() || !tracecore.codes.can_print()) {
		return;
	}
	const name = frm.doc.name;
	if (blocked) {
		frm.set_intro(blocked, "orange");
		return;
	}
	frappe.db.get_value("Code Registry", name, "status").then((r) => {
		if (frm.doc.name !== name) {
			return; // người dùng đã chuyển sang bản ghi khác trong lúc chờ
		}
		const status = r && r.message && r.message.status;
		if (status === "Active") {
			frm.add_custom_button(__("Print QR label"), () =>
				tracecore.codes.print_dialog(frm, label_object, name, title, subtitle)
			);
		} else if (status === "Disabled") {
			frm.set_intro(
				__(
					"QR label not available: code {0} has been disabled; its history can still be looked up.",
					[name]
				),
				"orange"
			);
		} else {
			frm.set_intro(
				__("QR label not available: code {0} has not been issued in TraceCore.", [name]),
				"orange"
			);
		}
	});
};

function tc_codes_too_many(count) {
	return {
		title: __("Too many records"),
		reason: __("{0} records are selected; at most {1} labels can be printed at once.", [
			count,
			tracecore.codes.MAX_BULK,
		]),
		action: __("Select at most {0} records and try again.", [tracecore.codes.MAX_BULK]),
	};
}

// Thao tác hàng loạt "In nhãn QR" trên list view (tối đa MAX_BULK bản ghi, gửi tuần tự)
tracecore.codes.add_bulk_print = function (listview, label_object) {
	if (!tracecore.codes.can_print()) {
		return;
	}
	listview.page.add_actions_menu_item(
		__("Print QR labels"),
		() => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				tracecore.codes.show_block({
					title: __("Nothing selected"),
					reason: __("No record is selected."),
					action: __("Tick the records whose QR labels you want to print."),
				});
				return;
			}
			if (names.length > tracecore.codes.MAX_BULK) {
				tracecore.codes.show_block(tc_codes_too_many(names.length));
				return;
			}
			tracecore.codes.print_dialog(null, label_object, names);
		},
		false
	);
};

function tc_codes_show_rolls(frm, codes) {
	const dialog = new frappe.ui.Dialog({
		title: __("Roll codes issued"),
		fields: [
			{
				fieldname: "codes",
				fieldtype: "HTML",
				options: `<p>${tc_codes_escape(
					__("{0} roll codes issued for {1}:", [
						codes.length,
						frm.doc.item_name || frm.doc.name,
					])
				)}</p><p>${codes.map((c) => tc_codes_mono(c)).join("<br>")}</p>`,
			},
		],
		primary_action_label: __("Print all"),
		primary_action() {
			dialog.hide();
			tracecore.codes.print_dialog(
				frm,
				"Roll",
				codes,
				frm.doc.item_name,
				__("{0} roll codes", [codes.length])
			);
		},
	});
	dialog.show();
}

// Cấp mã cuộn nhãn CN-##### cho Item nhóm Nhãn (A-05 R3)
tracecore.codes.issue_rolls_dialog = function (frm) {
	// request của thao tác đang dở (lỗi mạng): bấm lại với cùng số lượng → gửi lại đúng khóa cũ, không cấp hai lần
	let pending = null;
	const dialog = new frappe.ui.Dialog({
		title: __("Issue roll codes"),
		fields: [
			{
				fieldname: "count",
				fieldtype: "Int",
				label: __("Number of rolls"),
				default: 1,
				reqd: 1,
				description: __(
					"Each roll gets its own code CN-#####; from 1 to {0} codes at a time.",
					[tracecore.codes.MAX_ROLLS]
				),
			},
			{ fieldname: "result", fieldtype: "HTML" },
		],
		primary_action_label: __("Issue codes"),
		async primary_action(values) {
			const args = { item: frm.doc.name, count: values.count };
			if (!pending || pending.count !== values.count) {
				pending = { count: values.count, request: tracecore.codes.new_request(args) };
			}
			dialog.get_primary_btn().prop("disabled", true);
			frappe.dom.freeze();
			const result = await tracecore.codes.send(TC_CODES_ISSUE_ROLLS, pending.request);
			frappe.dom.unfreeze();
			dialog.get_primary_btn().prop("disabled", false);
			if (result.network) {
				// chưa biết server đã cấp chưa: giữ hộp thoại và request để gửi lại an toàn
				dialog.fields_dict.result.$wrapper.html(tracecore.codes.block_html(result.error));
				return;
			}
			pending = null;
			dialog.hide();
			if (result.ok) {
				tc_codes_show_rolls(frm, result.data.codes);
			} else {
				tracecore.codes.show_block(result.error);
			}
		},
	});
	dialog.show();
};

// In lại nhãn cuộn đã cấp (lần in trước lỗi, nhãn hỏng/mất): chọn trong các mã CN- còn Active của Item nhãn
tracecore.codes.roll_labels_dialog = async function (frm) {
	const result = await tracecore.codes.post(TC_CODES_LIST_ROLLS, { item: frm.doc.name }, false);
	if (!result.ok) {
		tracecore.codes.show_block(result.error);
		return;
	}
	const codes = result.data.codes;
	if (!codes.length) {
		frappe.msgprint({
			title: __("No roll codes"),
			indicator: "orange",
			message: __("{0} has no active roll codes. Issue roll codes first.", [
				frm.doc.item_name || frm.doc.name,
			]),
		});
		return;
	}
	const notes = [
		__("Tick the roll codes to print; at most {0} labels at a time.", [
			tracecore.codes.MAX_BULK,
		]),
	];
	if (result.data.truncated) {
		notes.push(__("Only the first {0} active roll codes are listed.", [codes.length]));
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Print roll labels"),
		size: "large",
		fields: [
			{
				fieldname: "info",
				fieldtype: "HTML",
				options: notes.map((note) => `<p>${tc_codes_escape(note)}</p>`).join(""),
			},
			{
				fieldname: "codes",
				fieldtype: "MultiCheck",
				label: __("Roll codes"),
				select_all: true,
				columns: 4,
				options: codes.map((code) => ({ label: code, value: code, checked: 0 })),
			},
			{ fieldname: "result", fieldtype: "HTML" },
		],
		primary_action_label: __("Print selected"),
		primary_action() {
			const selected = dialog.get_value("codes") || [];
			if (!selected.length) {
				dialog.fields_dict.result.$wrapper.html(
					tracecore.codes.block_html({
						title: __("Nothing selected"),
						reason: __("No roll code is selected."),
						action: __("Tick the roll codes whose labels you want to print."),
					})
				);
				return;
			}
			if (selected.length > tracecore.codes.MAX_BULK) {
				dialog.fields_dict.result.$wrapper.html(
					tracecore.codes.block_html(tc_codes_too_many(selected.length))
				);
				return;
			}
			dialog.hide();
			tracecore.codes.print_dialog(
				frm,
				"Roll",
				selected,
				frm.doc.item_name,
				__("{0} roll codes", [selected.length])
			);
		},
	});
	dialog.show();
};
