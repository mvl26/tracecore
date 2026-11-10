// Cổng khoa — khai báo bệnh truyền nhiễm (SCR-61 DEPT, FEAT-069, UC-53 bước 5–6; FR-M14-10, .1; BRU-MDR-005; A-150 Q4).
// Chữ hiển thị do server dịch sẵn (boot.labels). Ghi qua tracecore.v1.outbreak.create_report / record_reported với
// X-Idempotency-Key (thử lại giữ nguyên khóa). Mất mạng: không ghi được, giữ form và báo (Cổng khoa không xếp hàng
// offline). Lỗi chặn = alert-error inline (kết quả → lý do → hành động), ô thiếu viền đỏ + chữ "Bắt buộc".
(function () {
	const CREATE = "tracecore.v1.outbreak.create_report";
	const REPORTED = "tracecore.v1.outbreak.record_reported";
	const CONTEXT = "tracecore.v1.outbreak.portal_context";
	const FIELD_OF = {
		NOTIFIABLE_PATIENT_REQUIRED: "patient_code",
		NOTIFIABLE_DISEASE_REQUIRED: "disease",
		NOTIFIABLE_DATE_INVALID: "diagnosed_on",
		NOTIFIABLE_NOT_ALLOWED: "department",
	};
	const BADGE = {
		"Awaiting report": "tc-badge-w",
		Overdue: "tc-badge-r",
		"Reference missing": "tc-badge-w",
		Reported: "tc-badge-g",
		"Reported late": "tc-badge-r",
	};
	const root = document.getElementById("tc-kb-portal");
	const bootEl = document.getElementById("tc-kb-boot");
	if (!root || !bootEl) return;
	const boot = JSON.parse(bootEl.textContent || "{}");
	const L = boot.labels || {};
	const state = {
		data: boot.data || {},
		form: {},
		notice: null,
		invalid: null,
		busy: false,
		pending: null,
		reporting: null,
		reported: { reported_on: "", report_ref: "" },
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

	function dmyhm(value) {
		if (!value) return "-";
		const text = String(value);
		const [y, m, d] = text.slice(0, 10).split("-");
		return `${d}/${m}/${y} ${text.slice(11, 16)}`.trim();
	}

	function resetForm() {
		const first = (state.data.departments || [])[0] || {};
		state.form = {
			department: first.name || "",
			patient_code: "",
			disease: "",
			diagnosed_on: "",
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
			const result = await call(CONTEXT, {}, "GET");
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

	function stateBadge(row) {
		const text =
			row.state === "Awaiting report"
				? fmt(L.left, [
						Math.floor(Math.max(row.remaining_minutes || 0, 0) / 60),
						Math.max(row.remaining_minutes || 0, 0) % 60,
				  ])
				: (L.states || {})[row.state] || row.state;
		return `<span class="tc-badge ${BADGE[row.state] || "tc-badge-x"}">${esc(text)}</span>`;
	}

	function formHtml() {
		const data = state.data;
		const departments = (data.departments || [])
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						row.name === state.form.department ? " selected" : ""
					}>${esc(row.label)}</option>`
			)
			.join("");
		const diseases = (data.diseases || [])
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						row.name === state.form.disease ? " selected" : ""
					}>${esc(`${row.disease_name} (${row.disease_group})`)}</option>`
			)
			.join("");
		return `<section class="tc-cen-card">
			<h2>${esc(L.create)} <span class="tc-mono tc-dept-ref">Notifiable Disease Report · KB-</span></h2>
			<div class="tc-iso-form">
				<div class="tc-field"><label for="tc-kb-patient_code">${esc(L.patient_code)} *</label>
					<input id="tc-kb-patient_code" data-field="patient_code" autocomplete="off" maxlength="64"${invalidMark(
						"patient_code"
					)} value="${esc(state.form.patient_code)}">${requiredNote("patient_code")}
					<p class="tc-hint">${esc(L.code_hint)}</p></div>
				<div class="tc-field"><label for="tc-kb-department">${esc(L.department)}</label>
					<select id="tc-kb-department" data-field="department"${invalidMark(
						"department"
					)}>${departments}</select></div>
				<div class="tc-field"><label for="tc-kb-disease">${esc(L.disease)} *</label>
					<select id="tc-kb-disease" data-field="disease"${invalidMark("disease")}>
						<option value="">${esc(L.choose)}</option>${diseases}</select>${requiredNote("disease")}</div>
				<div class="tc-field"><label for="tc-kb-diagnosed_on">${esc(L.diagnosed_on)} *</label>
					<input id="tc-kb-diagnosed_on" type="datetime-local" data-field="diagnosed_on"${invalidMark(
						"diagnosed_on"
					)} value="${esc(state.form.diagnosed_on)}">${requiredNote(
			"diagnosed_on"
		)}</div>
			</div>
			${
				state.notice && state.notice.variant === "error" && !state.reporting
					? alertHtml(state.notice)
					: ""
			}
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="create"${
					state.busy ? " disabled" : ""
				}>${esc(state.busy ? L.creating : L.create)}</button>
			</div>
		</section>`;
	}

	function reportedHtml(row) {
		return `<div class="tc-kb-reported">
			<div class="tc-field"><label for="tc-kb-reported_on">${esc(L.reported_on)} *</label>
				<input id="tc-kb-reported_on" type="datetime-local" data-field="reported_on"${invalidMark(
					"diagnosed_on"
				)} value="${esc(state.reported.reported_on)}"></div>
			<div class="tc-field"><label for="tc-kb-report_ref">${esc(L.report_ref)}</label>
				<input id="tc-kb-report_ref" data-field="report_ref" maxlength="140" value="${esc(
					state.reported.report_ref
				)}"></div>
			<button type="button" class="tc-btn tc-btn-primary" data-action="reported-confirm" data-name="${esc(
				row.name
			)}"${state.busy ? " disabled" : ""}>${esc(L.save)}</button>
			<button type="button" class="tc-btn" data-action="reported-cancel">${esc(L.cancel)}</button>
		</div>${state.notice && state.notice.variant === "error" ? alertHtml(state.notice) : ""}`;
	}

	function listHtml() {
		const rows = state.data.reports || [];
		const done = ["Reported", "Reported late", "Cancelled"];
		const body = rows
			.map((row) => {
				const action = done.includes(row.state)
					? ""
					: `<button type="button" class="tc-btn" data-action="reported" data-name="${esc(
							row.name
					  )}">${esc(L.reported)}</button>`;
				const edit =
					state.reporting === row.name
						? `<tr><td colspan="7">${reportedHtml(row)}</td></tr>`
						: "";
				return `<tr>
					<td class="tc-mono">${esc(row.name)}</td>
					<td class="tc-mono">${esc(row.patient_code_masked)}</td>
					<td>${esc(row.disease_name || row.disease)} (${esc(row.disease_group || "")})</td>
					<td>${esc(dmyhm(row.diagnosed_on))}</td>
					<td>${esc(dmyhm(row.due_by))}</td>
					<td>${stateBadge(row)}${
					row.report_ref ? ` <span class="tc-mono">${esc(row.report_ref)}</span>` : ""
				}</td>
					<td>${action}</td>
				</tr>${edit}`;
			})
			.join("");
		return `<section class="tc-cen-card"><h2>${esc(L.title)}</h2>
			${
				rows.length
					? `<div class="tc-cen-scroll"><table class="tc-cen-table"><thead><tr>
						<th>${esc(L.code)}</th><th>${esc(L.patient_code)}</th><th>${esc(L.disease)}</th>
						<th>${esc(L.diagnosed_on)}</th><th>${esc(L.due_by)}</th><th>${esc(L.status)}</th><th></th>
					</tr></thead><tbody>${body}</tbody></table></div>`
					: `<p class="tc-empty">${esc(L.no_reports)}</p>`
			}
			<p class="tc-hint">${esc(L.note)}</p></section>`;
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
		if ((data.missing_groups || []).length)
			top.push(
				alertHtml({
					variant: "warn",
					title: fmt(L.missing_groups, [data.missing_groups.join(", ")]),
				})
			);
		if (state.notice && state.notice.variant !== "error") top.push(alertHtml(state.notice));
		root.innerHTML = `${top.join("")}${formHtml()}${listHtml()}`;
		if (state.invalid) {
			const input = root.querySelector(`[data-field="${state.invalid}"]`);
			if (input) input.focus();
		}
	}

	// ---- sự kiện (ủy quyền trên root, vì render vẽ lại DOM) ----
	const store = (event) => {
		const field = event.target.dataset.field;
		if (!field) return;
		if (field === "reported_on" || field === "report_ref")
			state.reported[field] = event.target.value;
		else state.form[field] = event.target.value;
	};
	root.addEventListener("input", store);
	root.addEventListener("change", store);
	root.addEventListener("click", (event) => {
		const button = event.target.closest("[data-action]");
		if (!button) return;
		const action = button.dataset.action;
		if (action === "retry") {
			state.notice = null;
			return reload();
		}
		if (action === "create") {
			state.reporting = null;
			return send(CREATE, { ...state.form }, (message) => {
				const warn = (message.warnings || []).join(" ");
				state.notice = {
					variant: warn ? "warn" : "ok",
					title: fmt(L.created, [message.report.name]),
					reason: [L.created_reason, warn].filter(Boolean).join(" "),
				};
				resetForm();
				reload();
			});
		}
		if (action === "reported") {
			state.reporting = button.dataset.name;
			state.reported = { reported_on: "", report_ref: "" };
			state.notice = null;
			state.invalid = null;
			return render();
		}
		if (action === "reported-cancel") {
			state.reporting = null;
			state.notice = null;
			return render();
		}
		if (action === "reported-confirm") {
			return send(
				REPORTED,
				{ report: button.dataset.name, ...state.reported },
				(message) => {
					state.reporting = null;
					const warn = (message.warnings || []).join(" ");
					state.notice = {
						variant: warn ? "warn" : "ok",
						title: fmt(L.saved, [message.report.name]),
						reason: warn,
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
