// Cổng khoa — lệnh cách ly (SCR-60 DEPT, FEAT-068, UC-52; FR-M14-06, .1; BRU-MDR-003; A-146 Q4, Q6).
// Chữ hiển thị do server dịch sẵn (boot.labels). Ghi qua tracecore.v1.isolation.create_order / close_order với
// X-Idempotency-Key (thử lại giữ nguyên khóa). Mất mạng: không ghi được, giữ form và báo (Cổng khoa không xếp hàng
// offline). Lỗi chặn = alert-error inline (kết quả → lý do → hành động), ô thiếu viền đỏ + chữ "Bắt buộc".
(function () {
	const CREATE = "tracecore.v1.isolation.create_order";
	const CLOSE = "tracecore.v1.isolation.close_order";
	const CONTEXT = "tracecore.v1.isolation.portal_context";
	const FIELD_OF = {
		ISOLATION_PRECAUTION_REQUIRED: "precaution_type",
		ISOLATION_REASON_REQUIRED: "reason",
		ISOLATION_PATIENT_REQUIRED: "patient_code",
		ISOLATION_END_REASON_REQUIRED: "end_reason",
	};
	const root = document.getElementById("tc-iso-portal");
	const bootEl = document.getElementById("tc-iso-boot");
	if (!root || !bootEl) return;
	const boot = JSON.parse(bootEl.textContent || "{}");
	const L = boot.labels || {};
	const state = {
		data: boot.data || {},
		isolate: boot.isolate || "",
		form: {},
		notice: null,
		invalid: null,
		busy: false,
		pending: null,
		closing: null,
		endReason: "",
	};

	function esc(value) {
		const div = document.createElement("div");
		div.textContent = value == null ? "" : String(value);
		return div.innerHTML;
	}

	function fmt(text, args) {
		return String(text || "").replace(/\{(\d+)\}/g, (_m, i) =>
			args[i] == null ? "" : args[i]
		);
	}

	function uuid4() {
		const bytes = crypto.getRandomValues(new Uint8Array(16));
		bytes[6] = (bytes[6] & 0x0f) | 0x40;
		bytes[8] = (bytes[8] & 0x3f) | 0x80;
		const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
		return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(
			16,
			20
		)}-${hex.slice(20)}`;
	}

	function pad(n) {
		return String(Math.floor(Math.abs(n))).padStart(2, "0");
	}

	function iso(date = new Date()) {
		const offset = -date.getTimezoneOffset();
		return (
			`${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
			`T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
			`${offset >= 0 ? "+" : "-"}${pad(offset / 60)}:${pad(offset % 60)}`
		);
	}

	function dmy(value) {
		if (!value) return "-";
		const [y, m, d] = String(value).slice(0, 10).split("-");
		return `${d}/${m}/${y}`;
	}

	function resetForm() {
		const p = state.data.prefill || {};
		const first = (state.data.departments || [])[0] || {};
		state.form = {
			department: p.department || first.name || "",
			patient_code: "",
			precaution_type: p.precaution_type || "",
			reason: p.reason || "",
			reason_detail: "",
			isolation_room: "",
			start_at: "",
		};
	}

	// ---- mạng ----
	async function call(method, args, httpMethod = "POST") {
		const headers = {
			Accept: "application/json",
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": (window.frappe && frappe.csrf_token) || "",
		};
		let url = `/api/method/${method}`;
		const init = { method: httpMethod, headers, credentials: "same-origin" };
		if (httpMethod === "GET") url += `?${new URLSearchParams(args)}`;
		else {
			headers["X-Idempotency-Key"] = args.__key;
			const { __key, ...rest } = args;
			init.body = JSON.stringify(rest);
		}
		const response = await fetch(url, init);
		const body = await response.json().catch(() => ({}));
		return { status: response.status, message: body.message };
	}

	function offlineOr(failure) {
		if (!navigator.onLine || failure instanceof TypeError)
			return { variant: "info", title: L.offline_title, reason: L.offline_reason };
		return {
			variant: "error",
			technical: true,
			title: L.server_error,
			reason: L.server_error_reason,
			action: L.server_error_action,
		};
	}

	async function reload() {
		try {
			const result = await call(CONTEXT, { isolate: "" }, "GET");
			if (result.status >= 400 || !result.message) throw result;
			state.data = result.message;
		} catch (e) {
			state.notice = offlineOr(e);
		}
		render();
	}

	async function send(method, args, onOk) {
		if (state.busy) return;
		const sig = JSON.stringify([method, args]);
		if (!state.pending || state.pending.sig !== sig)
			state.pending = { sig, key: uuid4(), ts: iso() };
		const pending = state.pending;
		if (!navigator.onLine) {
			state.notice = offlineOr(null);
			return render();
		}
		state.busy = true;
		render();
		let result;
		try {
			result = await call(method, { ...args, client_ts: pending.ts, __key: pending.key });
		} catch (e) {
			state.busy = false;
			state.notice = offlineOr(e);
			return render();
		}
		state.busy = false;
		const message = result.message;
		if (message && message.ok === false) {
			state.pending = null;
			state.invalid = FIELD_OF[message.error.code] || null;
			state.notice = { variant: "error", ...message.error };
			return render();
		}
		if (result.status >= 400 || !message) {
			if (result.status < 500) state.pending = null;
			state.notice = offlineOr({});
			return render();
		}
		state.pending = null;
		state.invalid = null;
		onOk(message);
	}

	// ---- vẽ ----
	function alertHtml(notice) {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(notice.title)}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
			${
				notice.technical
					? `<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
							L.retry
					  )}</button></div>`
					: ""
			}
		</div>`;
	}

	function invalidMark(field) {
		return state.invalid === field ? ` class="is-error" aria-invalid="true"` : "";
	}

	function requiredNote(field) {
		return state.invalid === field
			? `<span class="tc-cen-field-error">${esc(L.required)}</span>`
			: "";
	}

	function select(field, options, labels) {
		const chosen = state.form[field] || "";
		return `<select id="tc-iso-${field}" data-field="${field}"${invalidMark(field)}>
			<option value="">${esc(L.choose)}</option>
			${options
				.map(
					(value) =>
						`<option value="${esc(value)}"${value === chosen ? " selected" : ""}>${esc(
							labels[value] || value
						)}</option>`
				)
				.join("")}
		</select>`;
	}

	function roomOptions() {
		const rooms = (state.data.rooms || []).filter(
			(room) => room.department === state.form.department
		);
		return (
			`<option value="">${esc(L.no_room)}</option>` +
			rooms
				.map((room) => {
					const condition = room.meets_standard ? L.meets : L.not_met;
					const free = room.free ? fmt(L.room_free, [room.free]) : L.room_full;
					return `<option value="${esc(room.name)}"${
						room.name === state.form.isolation_room ? " selected" : ""
					}>${esc(`${room.room_code} (${condition}, ${free})`)}</option>`;
				})
				.join("")
		);
	}

	function formHtml() {
		const data = state.data;
		const p = data.prefill;
		const departments = (data.departments || [])
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						row.name === state.form.department ? " selected" : ""
					}>${esc(row.label)}</option>`
			)
			.join("");
		const patient = p
			? `<div class="tc-field"><span>${esc(L.patient_from_isolate)}</span>
				<div class="tc-iso-readonly tc-mono">${esc(p.patient_code_masked)} · ${esc(p.isolate)} · ${esc(
					p.mdro_flags || p.organism_name || ""
			  )}</div></div>`
			: `<div class="tc-field"><label for="tc-iso-patient_code">${esc(
					L.patient_code
			  )} *</label>
				<input id="tc-iso-patient_code" data-field="patient_code" autocomplete="off" maxlength="64"${invalidMark(
					"patient_code"
				)} value="${esc(state.form.patient_code)}">${requiredNote("patient_code")}
				<p class="tc-hint">${esc(L.code_hint)}</p></div>`;
		return `<section class="tc-cen-card">
			<h2>${esc(L.create)} <span class="tc-mono tc-dept-ref">Isolation Order · CL-</span></h2>
			<div class="tc-iso-form">
				${patient}
				<div class="tc-field"><label for="tc-iso-department">${esc(L.department)}</label>
					<select id="tc-iso-department" data-field="department"${
						p ? " disabled" : ""
					}>${departments}</select></div>
				<div class="tc-field"><label for="tc-iso-precaution_type">${esc(L.precaution)} *</label>
					${select("precaution_type", Object.keys(L.precautions), L.precautions)}${requiredNote(
			"precaution_type"
		)}</div>
				<div class="tc-field"><label for="tc-iso-reason">${esc(L.reason)} *</label>
					${select("reason", Object.keys(L.reasons), L.reasons)}${requiredNote("reason")}</div>
				<div class="tc-field"><label for="tc-iso-reason_detail">${esc(L.reason_detail)}</label>
					<input id="tc-iso-reason_detail" data-field="reason_detail" maxlength="500" value="${esc(
						state.form.reason_detail
					)}"></div>
				<div class="tc-field"><label for="tc-iso-isolation_room">${esc(L.room)}</label>
					<select id="tc-iso-isolation_room" data-field="isolation_room">${roomOptions()}</select></div>
				<div class="tc-field"><label for="tc-iso-start_at">${esc(L.start_at)}</label>
					<input id="tc-iso-start_at" type="datetime-local" data-field="start_at" value="${esc(
						state.form.start_at
					)}"></div>
			</div>
			${
				state.notice && state.notice.variant === "error" && !state.closing
					? alertHtml(state.notice)
					: ""
			}
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="create"${
					state.busy ? " disabled" : ""
				}>${esc(state.busy ? L.creating : L.create)}</button>
				<button type="button" class="tc-btn" data-action="reset">${esc(L.cancel)}</button>
			</div>
		</section>`;
	}

	function endHtml(row) {
		return `<div class="tc-iso-end">
			<div class="tc-field"><label for="tc-iso-end_reason">${esc(L.end_reason)} *</label>
				<input id="tc-iso-end_reason" data-field="end_reason" maxlength="500"${invalidMark(
					"end_reason"
				)} value="${esc(state.endReason)}">${requiredNote("end_reason")}
				<p class="tc-hint">${esc(L.end_hint)}</p></div>
			<button type="button" class="tc-btn tc-btn-primary" data-action="end-confirm" data-order="${esc(
				row.name
			)}"${state.busy ? " disabled" : ""}>${esc(L.end_confirm)}</button>
			<button type="button" class="tc-btn" data-action="end-cancel">${esc(L.cancel)}</button>
		</div>${state.notice && state.notice.variant === "error" ? alertHtml(state.notice) : ""}`;
	}

	function ordersHtml() {
		const data = state.data;
		const rows = data.orders || [];
		const body = rows
			.map((row) => {
				const mdro =
					row.is_mdro || (row.mdro_history || []).length
						? ` <span class="tc-badge tc-badge-r">${esc(L.mdro)}</span>`
						: "";
				const room = row.room_code
					? `<span class="tc-mono">${esc(row.room_code)}</span>`
					: `<span class="tc-badge tc-badge-x">${esc(L.bedside)}</span>`;
				const action =
					row.is_mdro && !data.mdro_close
						? `<span class="tc-hint">${esc(L.ic_closes)}</span>`
						: `<button type="button" class="tc-btn" data-action="end" data-order="${esc(
								row.name
						  )}">${esc(L.end)}</button>`;
				const end =
					state.closing === row.name
						? `<tr><td colspan="7">${endHtml(row)}</td></tr>`
						: "";
				return `<tr>
					<td class="tc-mono">${esc(row.name)}</td>
					<td class="tc-mono">${esc(row.patient_code_masked)}${mdro}</td>
					<td>${esc(L.precautions[row.precaution_type] || row.precaution_type)}</td>
					<td>${room}</td>
					<td>${esc(dmy(row.start_at))}</td>
					<td class="tc-num">${esc(row.days)}</td>
					<td>${action}</td>
				</tr>${end}`;
			})
			.join("");
		return `<section class="tc-cen-card">
			<h2>${esc(L.open_title)} <span class="tc-badge tc-badge-x">${esc(
			fmt(L.open_count, [rows.length])
		)}</span></h2>
			${
				rows.length
					? `<div class="tc-cen-scroll"><table class="tc-cen-table"><thead><tr>
						<th>${esc(L.order)}</th><th>${esc(L.patient_code)}</th><th>${esc(L.precaution_short)}</th>
						<th>${esc(L.room_short)}</th><th>${esc(L.from)}</th><th class="tc-num">${esc(L.days)}</th><th></th>
					</tr></thead><tbody>${body}</tbody></table></div>`
					: `<p class="tc-empty">${esc(L.no_orders)}</p>`
			}
		</section>`;
	}

	function roomsHtml() {
		const rows = state.data.rooms || [];
		const condition = (room) =>
			room.meets_standard
				? `<span class="tc-badge tc-badge-g">&#10003; ${esc(L.meets)}</span>`
				: room.checked_on
				? `<span class="tc-badge tc-badge-r">&#10005; ${esc(L.not_met)}</span>`
				: `<span class="tc-badge tc-badge-x">${esc(L.not_checked)}</span>`;
		return `<section class="tc-cen-card"><h2>${esc(L.rooms_title)}</h2>
			${
				rows.length
					? `<ul>${rows
							.map(
								(room) =>
									`<li><span class="tc-mono">${esc(
										room.room_code
									)}</span> — ${esc(
										room.occupied
											? fmt(L.in_use, [room.occupied, room.beds])
											: L.free
									)} ${condition(room)}</li>`
							)
							.join("")}</ul>`
					: `<p class="tc-empty">${esc(L.no_rooms)}</p>`
			}</section>`;
	}

	function render() {
		const data = state.data;
		if (!(data.departments || []).length) {
			root.innerHTML = `<p class="tc-empty">${esc(L.no_department)}</p>`;
			return;
		}
		const top = [];
		if (!navigator.onLine)
			top.push(
				alertHtml({ variant: "info", title: L.offline_title, reason: L.offline_reason })
			);
		if (state.notice && state.notice.variant !== "error") top.push(alertHtml(state.notice));
		root.innerHTML = `${top.join(
			""
		)}${formHtml()}<div class="tc-cen-grid">${ordersHtml()}${roomsHtml()}</div>`;
		if (state.invalid) {
			const input = root.querySelector(`[data-field="${state.invalid}"]`);
			if (input) input.focus();
		}
	}

	// ---- sự kiện (ủy quyền trên root, vì render vẽ lại DOM) ----
	root.addEventListener("input", (event) => {
		const field = event.target.dataset.field;
		if (!field) return;
		if (field === "end_reason") state.endReason = event.target.value;
		else state.form[field] = event.target.value;
	});
	root.addEventListener("change", (event) => {
		const field = event.target.dataset.field;
		if (!field) return;
		state.form[field] = event.target.value;
		if (field === "department") {
			state.form.isolation_room = "";
			render();
		}
	});
	root.addEventListener("click", (event) => {
		const button = event.target.closest("[data-action]");
		if (!button) return;
		const action = button.dataset.action;
		if (action === "retry") {
			state.notice = null;
			return reload();
		}
		if (action === "reset") {
			state.isolate = "";
			state.data.prefill = null;
			state.notice = null;
			state.invalid = null;
			resetForm();
			return render();
		}
		if (action === "create") {
			state.closing = null;
			return send(
				CREATE,
				{ ...state.form, isolate: state.isolate, start_at: state.form.start_at || "" },
				(message) => {
					const warn = (message.warnings || []).join(" ");
					state.notice = {
						variant: warn ? "warn" : "ok",
						title: fmt(L.created, [message.order.name]),
						reason: [L.created_reason, warn].filter(Boolean).join(" "),
					};
					state.isolate = "";
					state.data.prefill = null;
					resetForm();
					reload();
				}
			);
		}
		if (action === "end") {
			state.closing = button.dataset.order;
			state.endReason = "";
			state.notice = null;
			state.invalid = null;
			return render();
		}
		if (action === "end-cancel") {
			state.closing = null;
			state.notice = null;
			return render();
		}
		if (action === "end-confirm") {
			return send(
				CLOSE,
				{ order: button.dataset.order, end_reason: state.endReason },
				(message) => {
					state.closing = null;
					state.notice = {
						variant: "ok",
						title: fmt(L.closed, [message.order.name]),
					};
					reload();
				}
			);
		}
	});
	window.addEventListener("online", render);
	window.addEventListener("offline", render);

	resetForm();
	render();
})();
