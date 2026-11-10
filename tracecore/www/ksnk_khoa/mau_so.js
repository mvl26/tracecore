// Cổng khoa — mẫu số ngày & đợt thiết bị (SCR-55 DEPT, FEAT-062, UC-47; FR-M13-02, FR-M13-04, FR-M12-07; A-141 Q4).
// Chữ hiển thị do server dịch sẵn (boot.labels). Ghi qua tracecore.v1.hai.census_upsert_portal / device_episode_portal
// với X-Idempotency-Key (thử lại giữ nguyên khóa). Mất mạng: không ghi được, giữ số trên form và báo (Cổng khoa không
// xếp hàng offline; PDA có hàng đợi). Lỗi chặn = alert-error inline (kết quả → lý do → hành động), ô sai viền đỏ + chữ.
(function () {
	const UPSERT = "tracecore.v1.hai.census_upsert_portal";
	const EPISODE = "tracecore.v1.hai.device_episode_portal";
	const CONTEXT = "tracecore.v1.hai.portal_context";
	const COUNTS = [
		"patient_count",
		"vent_count",
		"cvc_count",
		"urinary_catheter_count",
		"admissions",
	];
	const DEVICE_COUNTS = ["vent_count", "cvc_count", "urinary_catheter_count"];
	const root = document.getElementById("tc-census-portal");
	const bootEl = document.getElementById("tc-census-boot");
	if (!root || !bootEl) return;
	const boot = JSON.parse(bootEl.textContent || "{}");
	const L = boot.labels || {};
	const state = {
		data: boot.data || {},
		counts: {},
		notice: null,
		busy: false,
		episodeForm: null,
		pending: null,
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

	// "2026-11-02" → "02/11/2026"
	function dmy(value) {
		if (!value) return "-";
		const [y, m, d] = String(value).slice(0, 10).split("-");
		return `${d}/${m}/${y}`;
	}

	function fillCounts() {
		const source = state.data.census || state.data.prefill || {};
		state.counts = {};
		for (const field of COUNTS)
			state.counts[field] = source[field] == null ? "" : String(source[field]);
	}

	// ---- kiểm trên máy theo đúng luật server (census.validate) ----
	function check() {
		for (const field of COUNTS) {
			const raw = state.counts[field];
			if (raw === "" && field === "admissions") continue;
			const value = Number(raw);
			if (raw === "" || !Number.isInteger(value) || value < 0)
				return {
					title: L.count_invalid,
					reason: fmt(L.count_invalid_reason, [L[field]]),
					action: fmt(L.count_action, [L[field]]),
					items: [field],
				};
		}
		const patients = Number(state.counts.patient_count);
		for (const field of DEVICE_COUNTS) {
			if (Number(state.counts[field]) > patients)
				return {
					title: L.not_saved,
					reason: fmt(L.too_many, [
						String(L[field]).toLowerCase(),
						state.counts[field],
						patients,
					]),
					action: fmt(L.count_action, [L[field]]),
					items: [field],
				};
		}
		return null;
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

	async function reload(department, date) {
		state.busy = true;
		render();
		try {
			const result = await call(
				CONTEXT,
				{ department: department || "", census_date: date || "" },
				"GET"
			);
			if (result.status >= 400 || !result.message) throw result;
			state.data = result.message;
			fillCounts();
			state.notice = state.notice && state.notice.keep ? state.notice : null;
		} catch (e) {
			state.notice = offlineOr(e);
		}
		state.busy = false;
		render();
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

	async function send(method, args, onOk) {
		if (state.busy) return;
		const sig = JSON.stringify([method, args]);
		if (!state.pending || state.pending.sig !== sig)
			state.pending = { sig, method, args, key: uuid4(), ts: iso(), onOk };
		const pending = state.pending;
		if (!navigator.onLine) {
			state.notice = offlineOr(null);
			return render();
		}
		state.busy = true;
		render();
		let result;
		try {
			result = await call(pending.method, {
				...pending.args,
				client_ts: pending.ts,
				__key: pending.key,
			});
		} catch (e) {
			state.busy = false;
			state.notice = offlineOr(e);
			return render();
		}
		state.busy = false;
		const message = result.message;
		if (message && message.ok === false) {
			state.pending = null;
			state.notice = { variant: "error", ...message.error };
			return render();
		}
		if (result.status >= 400 || !message) {
			if (result.status < 500) state.pending = null;
			state.notice = offlineOr({});
			return render();
		}
		state.pending = null;
		onOk(message);
	}

	// ---- thao tác ----
	function saveCensus() {
		const error = check();
		if (error) {
			state.notice = { variant: "error", ...error };
			return render();
		}
		const data = state.data;
		const args = {
			department: data.department,
			census_date: data.census_date,
			census: data.census ? data.census.name : "",
		};
		for (const field of COUNTS)
			args[field] = state.counts[field] === "" ? "" : Number(state.counts[field]);
		send(UPSERT, args, (message) => {
			state.data.census = message.census;
			state.notice = {
				variant: "ok",
				keep: true,
				title: L.saved,
				reason: fmt(L.saved_reason, [dmy(data.census_date)]),
			};
			reload(data.department, data.census_date);
		});
	}

	function saveEpisode() {
		const form = state.episodeForm;
		if (
			form.mode === "open" &&
			(!form.device_type || !String(form.patient_code || "").trim())
		) {
			state.notice = {
				variant: "error",
				title: L.episode_required,
				reason: L.episode_required_reason,
				action: L.episode_required_action,
			};
			return render();
		}
		const args =
			form.mode === "open"
				? {
						action: "open",
						department: state.data.department,
						device_type: form.device_type,
						patient_code: String(form.patient_code).trim(),
						birth_year: form.birth_year || "",
						sex: form.sex || "",
						inserted_on: form.inserted_on,
				  }
				: { action: "close", episode: form.episode, removed_on: form.removed_on };
		send(EPISODE, args, () => {
			state.episodeForm = null;
			state.notice = {
				variant: "ok",
				keep: true,
				title: form.mode === "open" ? L.episode_opened : L.episode_closed,
				reason: L.episode_updated,
			};
			reload(state.data.department, state.data.census_date);
		});
	}

	function today() {
		return state.data.today || iso().slice(0, 10);
	}

	root.addEventListener("click", (event) => {
		const button = event.target.closest("[data-action]");
		if (!button) return;
		const action = button.dataset.action;
		const value = button.dataset.value;
		if (action === "save") return saveCensus();
		if (action === "copy") {
			const prefill = state.data.prefill || {};
			for (const field of COUNTS)
				state.counts[field] = prefill[field] == null ? "" : String(prefill[field]);
			state.notice = null;
			return render();
		}
		if (action === "open")
			state.episodeForm = {
				mode: "open",
				device_type: "",
				patient_code: "",
				birth_year: "",
				sex: "",
				inserted_on: today(),
			};
		if (action === "close")
			state.episodeForm = {
				mode: "close",
				episode: button.dataset.episode,
				removed_on: today(),
			};
		if (action === "cancel") state.episodeForm = null;
		if (action === "device" || action === "sex") {
			const field = action === "device" ? "device_type" : "sex";
			state.episodeForm[field] = state.episodeForm[field] === value ? "" : value;
		}
		if (action === "ep-save") return saveEpisode();
		if (action === "retry") {
			state.notice = null;
			if (state.pending)
				return send(state.pending.method, state.pending.args, state.pending.onOk);
			return reload(state.data.department, state.data.census_date);
		}
		if (["open", "close", "cancel"].includes(action)) state.notice = null;
		render();
	});

	root.addEventListener("input", (event) => {
		const field = event.target.dataset && event.target.dataset.field;
		if (!field) return;
		if (field.startsWith("ep_")) state.episodeForm[field.slice(3)] = event.target.value;
		else if (COUNTS.includes(field)) state.counts[field] = event.target.value;
	});

	root.addEventListener("change", (event) => {
		const field = event.target.dataset && event.target.dataset.field;
		if (field === "department") reload(event.target.value, state.data.census_date);
		if (field === "census_date" && event.target.value)
			reload(state.data.department, event.target.value);
	});

	window.addEventListener("online", () => render());
	window.addEventListener("offline", () => {
		state.notice = offlineOr(null);
		render();
	});

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

	function badge(result) {
		if (result === "Pass")
			return `<span class="tc-badge tc-badge-g">&#10003; ${esc(L.pass)}</span>`;
		if (result === "Fail")
			return `<span class="tc-badge tc-badge-r">&#10005; ${esc(L.fail)}</span>`;
		return `<span class="tc-badge tc-badge-x">${esc(L.not_checked)}</span>`;
	}

	function pickHtml() {
		const data = state.data;
		const options = (data.departments || [])
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						row.name === data.department ? " selected" : ""
					}>${esc(row.label)}</option>`
			)
			.join("");
		return `<div class="tc-cen-pick">
			${
				(data.departments || []).length > 1
					? `<div class="tc-field"><label for="tc-cen-dept">${esc(
							L.department
					  )}</label><select id="tc-cen-dept" data-field="department">${options}</select></div>`
					: ""
			}
			<div class="tc-field"><label for="tc-cen-date">${esc(
				L.census_date
			)}</label><input id="tc-cen-date" type="date" data-field="census_date" max="${esc(
			today()
		)}" value="${esc(data.census_date)}"></div>
		</div>`;
	}

	function censusHtml() {
		const data = state.data;
		const current = data.census;
		const locked = current && current.locked;
		const bad = (state.notice && state.notice.items) || [];
		const fields = COUNTS.map((field) => {
			const error = bad.includes(field);
			return `<div class="tc-field">
				<label for="tc-cen-${field}">${esc(L[field])}${field === "admissions" ? "" : " *"}</label>
				<input id="tc-cen-${field}" type="number" inputmode="numeric" min="0" step="1" data-field="${field}"
					class="${error ? "is-error" : ""}" value="${esc(state.counts[field])}"${
				locked ? " disabled" : ""
			}${error ? ' aria-invalid="true"' : ""}>
				${error && state.notice ? `<p class="tc-cen-field-error">${esc(state.notice.reason)}</p>` : ""}
			</div>`;
		}).join("");
		const status = current
			? `<p class="tc-hint">${esc(
					fmt(L.existing, [
						current.name,
						(L.sources || {})[current.source] || current.source,
					])
			  )}${locked ? ` <span class="tc-badge tc-badge-x">${esc(L.locked)}</span>` : ""}</p>`
			: "";
		const buttons = locked
			? ""
			: `<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="save"${
					state.busy ? " disabled" : ""
				}>${esc(state.busy ? L.saving : current ? L.save_changes : L.save)}</button>
				${
					data.prefill && !current
						? `<button type="button" class="tc-btn" data-action="copy">${esc(
								L.copy
						  )}</button>`
						: ""
				}
			</div>`;
		return `<section class="tc-cen-card" aria-label="${esc(
			fmt(L.census_title, [dmy(data.census_date)])
		)}">
			<h2>${esc(
				fmt(L.census_title, [dmy(data.census_date)])
			)} <span class="tc-mono tc-dept-ref">Ward Daily Census · MS-</span></h2>
			${status}
			<div class="tc-cen-counts">${fields}</div>
			${
				state.notice && state.notice.variant === "error" && !state.episodeForm
					? alertHtml(state.notice)
					: ""
			}
			${buttons}
		</section>`;
	}

	function episodeFormHtml() {
		const form = state.episodeForm;
		const buttons = `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-primary" data-action="ep-save"${
				state.busy ? " disabled" : ""
			}>${esc(form.mode === "open" ? L.open_episode : L.close_episode)}</button>
			<button type="button" class="tc-btn" data-action="cancel">${esc(L.cancel)}</button>
		</div>`;
		const notice =
			state.notice && state.notice.variant === "error" ? alertHtml(state.notice) : "";
		if (form.mode === "close") {
			const row =
				(state.data.episodes || []).find((item) => item.name === form.episode) || {};
			return `<div class="tc-cen-form">
				<p><span class="tc-mono">${esc(row.patient_code_masked)}</span> · ${esc(
				(L.devices || {})[row.device_type] || row.device_type
			)} · ${esc(L.inserted_on)} ${esc(dmy(row.inserted_on))}</p>
				<div class="tc-field"><label for="tc-cen-removed">${esc(L.removed_on)}</label>
					<input id="tc-cen-removed" type="date" data-field="ep_removed_on" min="${esc(
						row.inserted_on || ""
					)}" max="${esc(today())}" value="${esc(form.removed_on)}"></div>
				${notice}${buttons}
			</div>`;
		}
		const option = (action, value, label, chosen) =>
			`<button type="button" class="tc-btn tc-exp-option${
				chosen ? " is-chosen" : ""
			}" data-action="${action}" data-value="${esc(value)}" aria-pressed="${chosen}">${
				chosen ? '<span aria-hidden="true">&#10003; </span>' : ""
			}${esc(label)}</button>`;
		const devices = Object.entries(L.devices || {})
			.map(([value, label]) => option("device", value, label, form.device_type === value))
			.join("");
		const sexes = Object.entries(L.sexes || {})
			.map(([value, label]) => option("sex", value, label, form.sex === value))
			.join("");
		return `<div class="tc-cen-form">
			<p class="tc-exp-question">${esc(L.device)}</p>
			<div class="tc-exp-options tc-exp-inline">${devices}</div>
			<div class="tc-field"><label for="tc-cen-code">${esc(L.code)} *</label>
				<input id="tc-cen-code" type="password" autocomplete="off" maxlength="64" data-field="ep_patient_code" value="${esc(
					form.patient_code
				)}">
				<p class="tc-hint">${esc(L.code_hint)}</p></div>
			<div class="tc-field"><label for="tc-cen-birth">${esc(L.birth_year)}</label>
				<input id="tc-cen-birth" type="number" inputmode="numeric" min="1900" data-field="ep_birth_year" value="${esc(
					form.birth_year
				)}"></div>
			<p class="tc-exp-question">${esc(L.sex)}</p>
			<div class="tc-exp-options tc-exp-inline">${sexes}</div>
			<div class="tc-field"><label for="tc-cen-inserted">${esc(L.inserted_on)}</label>
				<input id="tc-cen-inserted" type="date" data-field="ep_inserted_on" max="${esc(
					today()
				)}" value="${esc(form.inserted_on)}"></div>
			${notice}${buttons}
		</div>`;
	}

	function episodesHtml() {
		const rows = (state.data.episodes || [])
			.map(
				(row) => `<tr>
				<td class="tc-mono">${esc(row.patient_code_masked)}</td>
				<td>${esc((L.devices || {})[row.device_type] || row.device_type)}</td>
				<td>${esc(dmy(row.inserted_on))}</td>
				<td class="tc-num">${esc(row.device_days)}</td>
				<td>${badge(row.bundle_result)}</td>
				<td><button type="button" class="tc-btn" data-action="close" data-episode="${esc(row.name)}">${esc(
					L.close_episode
				)}</button></td>
			</tr>`
			)
			.join("");
		const table = rows
			? `<div class="tc-cen-scroll"><table class="tc-cen-table"><thead><tr>
				<th>${esc(L.code)}</th><th>${esc(L.device)}</th><th>${esc(L.inserted_on)}</th><th>${esc(
					L.days
			  )}</th><th>${esc(L.bundle_today)}</th><th></th>
			</tr></thead><tbody>${rows}</tbody></table></div>`
			: `<p class="tc-empty">${esc(L.no_episode)}</p>`;
		return `<section class="tc-cen-card" id="goi-du-phong" aria-label="${esc(L.episodes)}">
			<h2>${esc(L.episodes)} <span class="tc-mono tc-dept-ref">Device Episode · DTB-</span></h2>
			${
				state.episodeForm
					? episodeFormHtml()
					: `${table}
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="open">${esc(
				L.open_episode
			)}</button></div>`
			}
			<p class="tc-hint">${esc(L.code_hint)}</p>
			<p class="tc-hint">${esc(L.bundle_hint)}</p>
		</section>`;
	}

	function recentHtml() {
		const rows = (state.data.recent || [])
			.map(
				(row) => `<tr>
				<td>${esc(dmy(row.census_date))}</td>
				<td class="tc-num">${esc(row.patient_count)}</td>
				<td class="tc-num">${esc(row.vent_count)}</td>
				<td class="tc-num">${esc(row.cvc_count)}</td>
				<td class="tc-num">${esc(row.urinary_catheter_count)}</td>
				<td>${esc((L.sources || {})[row.source] || row.source)}${
					row.locked ? ` <span class="tc-badge tc-badge-x">${esc(L.locked)}</span>` : ""
				}</td>
			</tr>`
			)
			.join("");
		const source = state.data.device_day_source
			? `<p class="tc-hint">${esc(
					fmt(L.device_source, [
						(L.sources || {})[state.data.device_day_source] ||
							state.data.device_day_source,
					])
			  )}</p>`
			: "";
		return `<section class="tc-cen-card" aria-label="${esc(L.recent)}">
			<h2>${esc(L.recent)}</h2>
			${
				rows
					? `<div class="tc-cen-scroll"><table class="tc-cen-table"><thead><tr>
				<th>${esc(L.date)}</th><th>${esc(L.patient_count)}</th><th>${esc(L.vent_count)}</th><th>${esc(
							L.cvc_count
					  )}</th><th>${esc(L.urinary_catheter_count)}</th><th>${esc(L.source)}</th>
			</tr></thead><tbody>${rows}</tbody></table></div>`
					: `<p class="tc-empty">${esc(L.no_recent)}</p>`
			}
			${source}
		</section>`;
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
		if (data.missing)
			top.push(
				alertHtml({
					variant: "warn",
					title: fmt(L.missing_title, [dmy(data.census_date)]),
					reason: L.missing_reason,
				})
			);
		if (state.notice && state.notice.variant !== "error") top.push(alertHtml(state.notice));
		root.innerHTML = `${top.join("")}
			${pickHtml()}
			${censusHtml()}
			<div class="tc-cen-grid">${episodesHtml()}${recentHtml()}</div>`;
	}

	fillCounts();
	render();
})();
