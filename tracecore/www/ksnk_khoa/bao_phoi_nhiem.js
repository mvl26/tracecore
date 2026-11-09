// Cổng khoa — báo phơi nhiễm 3 bước (SCR-63 DEPT, FEAT-071, UC-55, FR-M16-01, A-137 Q2, Q4).
// Chữ hiển thị do server dịch sẵn (boot.labels); trang không tự gõ chữ. Gửi tracecore.v1.exposure.report_portal với
// X-Idempotency-Key; mất mạng → giữ báo cáo trong trình duyệt (localStorage, KHÔNG giữ mã BN nguồn) và gửi lại khi có
// mạng với cùng khóa + X-TC-Replay (NFR-AVAIL-05). Bốn trạng thái: đang gửi / chưa chọn / lỗi / mất mạng.
(function () {
	const METHOD = "tracecore.v1.exposure.report_portal";
	const OUTBOX = "tc-exposure-outbox";
	const TYPES = [
		"Needlestick or Sharps",
		"Mucous Membrane Splash",
		"Non-intact Skin",
		"Respiratory",
		"Other",
	];
	const SOURCES = ["Yes", "No", "Unknown"];
	const root = document.getElementById("tc-exposure-portal");
	const bootEl = document.getElementById("tc-exposure-boot");
	if (!root || !bootEl) return;
	const boot = JSON.parse(bootEl.textContent || "{}");
	const L = boot.labels || {};
	const data = boot.data || {};

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

	function iso(date) {
		const offset = -date.getTimezoneOffset();
		return (
			`${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
			`T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
			`${offset >= 0 ? "+" : "-"}${pad(offset / 60)}:${pad(offset % 60)}`
		);
	}

	function localInput(date = new Date()) {
		return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
			date.getHours()
		)}:${pad(date.getMinutes())}`;
	}

	function readOutbox() {
		try {
			return JSON.parse(localStorage.getItem(OUTBOX) || "[]");
		} catch (e) {
			return [];
		}
	}

	function writeOutbox(items) {
		try {
			localStorage.setItem(OUTBOX, JSON.stringify(items));
			return true;
		} catch (e) {
			return false;
		}
	}

	const state = {
		form: blank(),
		busy: false,
		notice: null,
		done: null,
		pending: null,
		records: data.records || [],
	};

	function blank() {
		return {
			step: 1,
			employee: "",
			exposure_type: "",
			occurred_at: localInput(),
			activity: "",
			device: "",
			source_known: "Unknown",
			source_patient_code: "",
		};
	}

	async function post(args, key, replay) {
		const headers = {
			Accept: "application/json",
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": (window.frappe && frappe.csrf_token) || "",
			"X-Idempotency-Key": key,
		};
		if (replay) headers["X-TC-Replay"] = "1";
		const response = await fetch(`/api/method/${METHOD}`, {
			method: "POST",
			headers,
			body: JSON.stringify(args),
			credentials: "same-origin",
		});
		const body = await response.json().catch(() => ({}));
		return { status: response.status, message: body.message };
	}

	async function flush() {
		if (!navigator.onLine) return;
		const items = readOutbox();
		const left = [];
		for (const item of items) {
			try {
				const result = await post(item.args, item.key, true);
				if (result.status >= 500) left.push(item); // lỗi server: giữ lại, gửi lần sau
			} catch (e) {
				left.push(item); // vẫn mất mạng
			}
		}
		writeOutbox(left);
		render();
	}

	function args() {
		const form = state.form;
		return {
			employee: form.employee || null,
			exposure_type: form.exposure_type,
			occurred_at: iso(new Date(form.occurred_at || Date.now())),
			activity: form.activity.trim(),
			device: form.device.trim(),
			source_known: form.source_known,
			source_patient_code:
				form.source_known === "Yes" ? form.source_patient_code.trim() : "",
		};
	}

	function queue(pending) {
		const { source_patient_code: _code, ...rest } = pending.args; // mã BN không lưu trong trình duyệt
		const items = readOutbox();
		items.push({ key: pending.key, args: { ...rest, client_ts: pending.ts } });
		state.pending = null;
		if (!writeOutbox(items)) {
			state.notice = {
				title: L.server_error,
				reason: L.server_error_reason,
				action: L.server_error_action,
			};
			return render();
		}
		state.done = { queued: true };
		render();
	}

	async function send() {
		if (state.busy) return;
		const current = args();
		const sig = JSON.stringify(current);
		if (!state.pending || state.pending.sig !== sig)
			state.pending = { sig, args: current, key: uuid4(), ts: iso(new Date()) };
		const pending = state.pending;
		if (!navigator.onLine) return queue(pending);
		state.busy = true;
		render();
		let result;
		try {
			result = await post({ ...pending.args, client_ts: pending.ts }, pending.key, false);
		} catch (e) {
			state.busy = false;
			return queue(pending);
		}
		state.busy = false;
		const message = result.message || {};
		if (message.ok === false) {
			state.pending = null;
			state.notice = message.error || {};
			return render();
		}
		if (!message.ok) {
			if (result.status >= 400 && result.status < 500) state.pending = null;
			state.notice = {
				title: L.server_error,
				reason: L.server_error_reason,
				action: L.server_error_action,
				retry: true,
			};
			return render();
		}
		state.pending = null;
		state.done = message.exposure;
		state.records = [
			{
				name: message.exposure.name,
				exposure_type: message.exposure.exposure_type,
				status: "New",
				followups: [],
			},
			...state.records,
		];
		render();
	}

	function stepError() {
		const form = state.form;
		if (form.step === 1 && !form.exposure_type)
			return {
				title: L.type_required,
				reason: L.type_required_reason,
				action: L.type_required_action,
			};
		if (form.step === 1 && new Date(form.occurred_at) > new Date(Date.now() + 5 * 60000))
			return { title: L.future_title, reason: L.future_reason, action: L.future_action };
		return null;
	}

	function alertHtml(notice, variant) {
		const icon = { error: "&#10005;", ok: "&#10003;", info: "i" }[variant];
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(notice.title)}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${
				notice.action
					? `<p class="tc-alert-action">${notice.action_html || esc(notice.action)}</p>`
					: ""
			}
			${
				notice.retry
					? `<button type="button" class="tc-btn tc-btn-primary" data-act="send">${esc(
							L.retry
					  )}</button>`
					: ""
			}
		</div>`;
	}

	function option(act, value, label, chosen) {
		return `<button type="button" class="tc-btn tc-exp-option${
			chosen ? " is-chosen" : ""
		}" data-act="${act}" data-value="${esc(value)}" aria-pressed="${chosen}">${
			chosen ? '<span aria-hidden="true">&#10003; </span>' : ""
		}${esc(label)}</button>`;
	}

	function stepsHtml() {
		return `<ol class="tc-exp-steps">${[L.step1, L.step2, L.step3]
			.map((label, i) => {
				const current = state.form.step === i + 1;
				return `<li class="tc-exp-chip${current ? " is-current" : ""}"${
					current ? ' aria-current="step"' : ""
				}>${i + 1} ${esc(label)}</li>`;
			})
			.join("")}</ol>`;
	}

	function reporterHtml() {
		const colleagues = data.colleagues || [];
		if (!colleagues.length) return "";
		const options = colleagues
			.filter((row) => row.employee !== data.employee)
			.map(
				(row) =>
					`<option value="${esc(row.employee)}"${
						state.form.employee === row.employee ? " selected" : ""
					}>${esc(row.employee_name)}</option>`
			)
			.join("");
		return `<div class="tc-field"><label for="tc-exp-for">${esc(L.reporter)}</label>
			<select id="tc-exp-for" data-field="employee"><option value="">${esc(
				L.myself
			)}</option>${options}</select></div>`;
	}

	function step1() {
		return `<h2 class="tc-exp-title">${esc(L.step1_title)}</h2>
			${reporterHtml()}
			<div class="tc-exp-options">${TYPES.map((t) =>
				option("type", t, (L.types || {})[t] || t, state.form.exposure_type === t)
			).join("")}</div>
			<div class="tc-field"><label for="tc-exp-time">${esc(L.when)}</label>
				<input id="tc-exp-time" type="datetime-local" data-field="occurred_at" max="${esc(
					localInput()
				)}" value="${esc(state.form.occurred_at)}"></div>
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-act="next"${
				state.form.exposure_type ? "" : " disabled"
			}>${esc(L.continue)}</button></div>`;
	}

	function step2() {
		const form = state.form;
		return `<h2 class="tc-exp-title">${esc(L.step2_title)}</h2>
			<div class="tc-field"><label for="tc-exp-activity">${esc(L.activity)}</label>
				<input id="tc-exp-activity" type="text" maxlength="140" autocomplete="off" data-field="activity" value="${esc(
					form.activity
				)}"></div>
			<div class="tc-field"><label for="tc-exp-device">${esc(L.device)}</label>
				<input id="tc-exp-device" type="text" maxlength="140" autocomplete="off" data-field="device" value="${esc(
					form.device
				)}"></div>
			<p class="tc-exp-question">${esc(L.source_question)}</p>
			<div class="tc-exp-options tc-exp-inline">${SOURCES.map((s) =>
				option("source", s, (L.sources || {})[s] || s, form.source_known === s)
			).join("")}</div>
			${
				form.source_known === "Yes"
					? `<div class="tc-field"><label for="tc-exp-code">${esc(L.source_code)}</label>
				<input id="tc-exp-code" type="password" maxlength="64" autocomplete="off" data-field="source_patient_code" value="${esc(
					form.source_patient_code
				)}"><p class="tc-hint">${esc(L.source_code_hint)}</p></div>`
					: ""
			}
			<div class="tc-actions"><button type="button" class="tc-btn" data-act="back">${esc(
				L.back
			)}</button>
				<button type="button" class="tc-btn tc-btn-primary" data-act="next">${esc(
					L.continue
				)}</button></div>`;
	}

	function step3() {
		const form = state.form;
		const row = (label, value) =>
			`<div class="tc-exp-row"><dt>${esc(label)}</dt><dd>${esc(value || "-")}</dd></div>`;
		const source =
			((L.sources || {})[form.source_known] || form.source_known) +
			(form.source_known === "Yes" && form.source_patient_code
				? " · " + L.code_entered
				: "");
		return `<h2 class="tc-exp-title">${esc(L.step3_title)}</h2>
			<dl class="tc-exp-summary">
				${row(L.exposure_type, (L.types || {})[form.exposure_type])}
				${row(L.occurred_at, form.occurred_at.replace("T", " "))}
				${row(L.activity, form.activity)}
				${row(L.device, form.device)}
				${row(L.source_known, source)}
			</dl>
			<p class="tc-hint">${esc(L.notified)}</p>
			<div class="tc-actions"><button type="button" class="tc-btn" data-act="back">${esc(
				L.back
			)}</button>
				<button type="button" class="tc-btn tc-btn-primary tc-exp-send" data-act="send">${esc(
					L.send
				)}</button></div>`;
	}

	function doneHtml() {
		const done = state.done;
		if (done.queued)
			return alertHtml(
				{ title: L.queued_title, reason: L.queued_reason, action: L.no_procedure },
				"info"
			);
		const procedure = done.procedure;
		const action = procedure
			? {
					action: `${L.procedure}: ${procedure.title}`,
					action_html:
						`${esc(L.procedure)}: ${esc(procedure.title)}` +
						(procedure.file
							? ` <a href="${esc(
									procedure.file
							  )}" target="_blank" rel="noopener">${esc(L.open)}</a>`
							: ""),
			  }
			: { action: L.no_procedure };
		return alertHtml(
			{ title: fmt(L.done_title, [done.name]), reason: L.done_reason, ...action },
			"ok"
		);
	}

	function recordsHtml() {
		const rows = state.records
			.map((r) => {
				const steps = (r.followups || [])
					.map(
						(f) =>
							`<li>${esc(f.step)} · ${esc(L.due)} ${esc(f.due_date || "-")} · ${esc(
								f.done_on ? `${L.done_on} ${f.done_on}` : L.not_yet
							)}</li>`
					)
					.join("");
				return `<li class="tc-dept-record"><span class="tc-mono">${esc(
					r.name
				)}</span> · ${esc(
					(L.types || {})[r.exposure_type] || r.exposure_type
				)} · <span class="tc-badge">${esc(
					(L.statuses || {})[r.status] || r.status
				)}</span>${
					steps
						? `<ul class="tc-dept-steps" aria-label="${esc(
								L.followups
						  )}">${steps}</ul>`
						: ""
				}</li>`;
			})
			.join("");
		return `<section class="tc-dept-records"><h2 class="tc-exp-title">${esc(
			L.my_records
		)}</h2>${
			rows ? `<ul>${rows}</ul>` : `<p class="tc-empty">${esc(L.no_records)}</p>`
		}</section>`;
	}

	function render() {
		const waiting = readOutbox().length;
		let body = "";
		let view = "result";
		if (!data.employee && !(data.colleagues || []).length) {
			view = "empty";
			body = `<p class="tc-empty">${esc(L.no_employee)}</p>`;
		} else if (state.busy) {
			view = "loading";
			body = `<p class="tc-loading" role="status" aria-busy="true">${esc(L.sending)}</p>`;
		} else if (state.done) {
			body = `${doneHtml()}<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-act="new">${esc(
				L.new_report
			)}</button></div>`;
		} else {
			const step =
				state.form.step === 1 ? step1() : state.form.step === 2 ? step2() : step3();
			if (state.notice) view = "error";
			else if (state.form.step === 1 && !state.form.exposure_type) view = "empty";
			body = `${state.notice ? alertHtml(state.notice, "error") : ""}${stepsHtml()}${step}`;
		}
		if (!navigator.onLine) view = "offline";
		const offline = !navigator.onLine
			? alertHtml({ title: L.offline_title, reason: L.offline_reason }, "info")
			: "";
		const queued = waiting
			? `<p class="tc-hint" role="status">${esc(fmt(L.queued_count, [waiting]))}</p>`
			: "";
		root.dataset.state = view;
		root.innerHTML = `${offline}${queued}${body}${recordsHtml()}`;
	}

	root.addEventListener("click", (event) => {
		const button = event.target.closest("[data-act]");
		if (!button) return;
		const act = button.dataset.act;
		const form = state.form;
		if (act === "type") form.exposure_type = button.dataset.value;
		else if (act === "source") {
			form.source_known = button.dataset.value;
			if (form.source_known !== "Yes") form.source_patient_code = "";
		} else if (act === "next") {
			const error = stepError();
			state.notice = error;
			if (!error) form.step = Math.min(3, form.step + 1);
		} else if (act === "back") {
			state.notice = null;
			form.step = Math.max(1, form.step - 1);
		} else if (act === "send") return send();
		else if (act === "new") {
			state.done = null;
			state.notice = null;
			state.form = blank();
		}
		render();
	});

	root.addEventListener("input", (event) => {
		const field = event.target.dataset && event.target.dataset.field;
		if (field) state.form[field] = event.target.value;
	});
	root.addEventListener("change", (event) => {
		const field = event.target.dataset && event.target.dataset.field;
		if (field) state.form[field] = event.target.value;
	});

	window.addEventListener("online", flush);
	window.addEventListener("offline", render);
	render();
	flush();
})();
