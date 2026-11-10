/* global uuid4, clientTs, esc, tcErrorTitle, tcGuideButton, t8Encrypt */
// SCR-55 Mẫu số ngày & đợt thiết bị trên PDA của khoa (FEAT-062; UC-47; FR-M13-02, FR-M13-04, FR-M12-07; BRU-HAI-002,
// BRU-HAI-005; NFR-AVAIL-05; ADR-003, ADR-010; A-141). Page station, chức năng trạm CENSUS.
// - Mẫu số: form 1 cột, ô số lớn điền sẵn số ngày trước; một bản mỗi (ngày, khoa) — đã có thì hiện bản đó để sửa;
//   số thiết bị > số người bệnh → alert-error inline chỉ rõ ô (FR-M13-02.1). Bản thuộc kỳ đã khóa chỉ xem.
// - Đợt thiết bị: danh sách đợt đang mở (mã BN che, số ngày, gói hôm nay bằng chữ), "Mở đợt" / "Đóng đợt".
// - Mất mạng: ghi xếp hàng IndexedDB (`TcOutbox`), gửi lại cùng X-Idempotency-Key khi có mạng; mã BN chỉ vào hàng đợi
//   khi mã hóa được bằng khóa công khai của site, không thì phải chờ có mạng.

const CEN_CONTEXT = "tracecore.v1.hai.context";
const CEN_UPSERT = "tracecore.v1.hai.census_upsert";
const CEN_EPISODE = "tracecore.v1.hai.device_episode";
const CEN_COUNTS = [
	["patient_count", "Inpatients"],
	["vent_count", "On Ventilator"],
	["cvc_count", "Central Line"],
	["urinary_catheter_count", "Urinary Catheter"],
	["admissions", "Admissions"],
];
const CEN_DEVICES = ["Ventilator", "Central Line", "Urinary Catheter"];
const CEN_SEX = ["Male", "Female", "Other"];

function cenToday() {
	const now = new Date();
	const pad = (n) => String(n).padStart(2, "0");
	return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function cenAddDays(value, days) {
	const date = new Date(`${value}T00:00:00`);
	date.setDate(date.getDate() + days);
	const pad = (n) => String(n).padStart(2, "0");
	return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// Kiểm trên máy theo đúng luật server (census.validate); kết quả chính thức do server trả
const TcCensus = {
	check(counts) {
		for (const [field, label] of CEN_COUNTS) {
			const raw = counts[field];
			if ((raw === "" || raw === undefined || raw === null) && field === "admissions")
				continue;
			const value = Number(raw);
			if (raw === "" || raw === undefined || !Number.isInteger(value) || value < 0)
				return {
					code: "CENSUS_COUNT_INVALID",
					title: __("Count not valid"),
					reason: __("{0} must be a whole number of 0 or more.", [__(label)]),
					action: __("Correct the {0} box and save again.", [__(label)]),
					items: [field],
				};
		}
		const patients = Number(counts.patient_count);
		for (const [field, label] of CEN_COUNTS.slice(1, 4)) {
			if (Number(counts[field]) > patients)
				return {
					code: "CENSUS_COUNT_INVALID",
					title: __("Census not saved"),
					reason: __("Patients with {0} ({1}) cannot be more than inpatients ({2}).", [
						__(label).toLowerCase(),
						counts[field],
						patients,
					]),
					action: __("Correct the {0} box and save again.", [__(label)]),
					items: [field],
				};
		}
		return null;
	},

	bundleBadge(result) {
		if (result === "Pass") return { cls: "g", label: __("Pass") };
		if (result === "Fail") return { cls: "r", label: __("Fail") };
		return { cls: "x", label: __("Not checked") };
	},
};

class CensusStation {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		station.listen(this.result, "input", (event) => this.onInput(event));
		station.listen(this.result, "change", (event) => this.onInput(event));
		this.clearSession();
	}

	clearSession() {
		this.context = null;
		this.contextFailed = null;
		this.loading = false;
		this.busy = false;
		this.offline = false;
		this.department = "";
		this.censusDate = "";
		this.counts = {};
		this.episodeForm = null; // {mode: "open"|"close", ...}
		this.notice = null;
		this.pending = null;
		this.updatePlaceholder();
	}

	get dialogOpen() {
		return Boolean(this.episodeForm); // form đợt giữ focus, ô quét không giành lại
	}

	updatePlaceholder() {
		const text = __("Enter the daily census below");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	scan() {
		this.input.value = "";
		this.station.focus();
	}

	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- dữ liệu ----
	async loadContext(department, censusDate) {
		const station = this.station;
		if (this.loading || !station.session || station.isOffline()) return;
		const version = station.sessionVersion;
		this.loading = true;
		this.contextFailed = null;
		this.show();
		try {
			const res = await station.rpcRead(CEN_CONTEXT, {
				station: station.station,
				department: department || this.department || "",
				census_date: censusDate || this.censusDate || "",
				client_ts: clientTs(),
			});
			if (version !== station.sessionVersion) return;
			if (res && res.ok !== false) this.applyContext(res);
			else this.contextFailed = station.failureCause(null, res);
		} catch (error) {
			if (error.sessionEnded) return;
			this.contextFailed = station.failureCause(error);
		} finally {
			this.loading = false;
		}
		if (version === station.sessionVersion) this.show();
	}

	applyContext(res) {
		this.context = res;
		this.department = res.department || "";
		this.censusDate = res.census_date || cenAddDays(cenToday(), -1);
		const source = res.census || res.prefill || {};
		this.counts = {};
		for (const [field] of CEN_COUNTS) {
			const value = source[field];
			this.counts[field] = value === null || value === undefined ? "" : String(value);
		}
	}

	onInput(event) {
		const target = event.target;
		const field = target && target.dataset && target.dataset.cen;
		if (!field) return;
		if (field === "census_date") {
			if (event.type !== "change" || !target.value) return; // ô ngày phát cả input lẫn change
			this.notice = null;
			return this.loadContext(this.department, target.value);
		}
		if (field.startsWith("ep_")) {
			if (this.episodeForm) this.episodeForm[field.slice(3)] = target.value;
			return;
		}
		this.counts[field] = target.value;
	}

	// ---- thao tác ----
	onAction(action, button) {
		const data = (button && button.dataset) || {};
		const handlers = {
			"cen-department": () => this.loadContext(data.department, this.censusDate),
			"cen-day": () => this.loadContext(this.department, data.day),
			"cen-copy": () => this.copyPrevious(),
			"cen-save": () => this.saveCensus(),
			"cen-open": () => this.startEpisode("open"),
			"cen-close": () => this.startEpisode("close", data.episode),
			"cen-device": () => this.setEpisode("device_type", data.value),
			"cen-sex": () => this.setEpisode("sex", data.value),
			"cen-ep-save": () => this.saveEpisode(),
			"cen-ep-cancel": () => {
				this.episodeForm = null;
				this.notice = null;
				this.show();
			},
			retry: () => this.retry(),
		};
		if (!handlers[action]) return false;
		handlers[action]();
		return true;
	}

	copyPrevious() {
		const prefill = this.context && this.context.prefill;
		if (!prefill) return;
		for (const [field] of CEN_COUNTS)
			this.counts[field] =
				prefill[field] === null || prefill[field] === undefined
					? ""
					: String(prefill[field]);
		this.notice = null;
		this.show();
	}

	startEpisode(mode, episode) {
		this.notice = null;
		this.episodeForm =
			mode === "open"
				? {
						mode,
						device_type: "",
						patient_code: "",
						birth_year: "",
						sex: "",
						inserted_on: cenToday(),
				  }
				: { mode, episode, removed_on: cenToday() };
		this.show();
	}

	setEpisode(field, value) {
		if (!this.episodeForm) return;
		this.episodeForm[field] = this.episodeForm[field] === value ? "" : value;
		this.show();
	}

	block(notice) {
		this.notice = { variant: "error", ...notice };
		this.show();
	}

	saveCensus() {
		const error = TcCensus.check(this.counts);
		if (error) return this.block(error);
		const current = this.context && this.context.census;
		const args = {
			station: this.station.station,
			department: this.department,
			census_date: this.censusDate,
			census: current ? current.name : "",
		};
		for (const [field] of CEN_COUNTS)
			args[field] = this.counts[field] === "" ? "" : Number(this.counts[field]);
		return this.send(CEN_UPSERT, args, (res) => {
			this.context.census = res.census;
			this.context.missing = false;
			this.done(
				__("Census saved"),
				__("Daily census of {0} is saved.", [frappe.datetime.str_to_user(this.censusDate)])
			);
		});
	}

	async saveEpisode() {
		const form = this.episodeForm;
		if (!form) return;
		if (form.mode === "open" && (!form.device_type || !String(form.patient_code || "").trim()))
			return this.block({
				code: "DEVICE_EPISODE_REQUIRED",
				title: __("Device and patient code required"),
				reason: __("An episode needs the device and the patient code."),
				action: __("Choose the device and enter the patient code, then save."),
			});
		const args = { station: this.station.station, action: form.mode };
		if (form.mode === "open") {
			Object.assign(args, {
				department: this.department,
				device_type: form.device_type,
				birth_year: form.birth_year || "",
				sex: form.sex || "",
				inserted_on: form.inserted_on,
			});
			const code = String(form.patient_code).trim();
			const key = this.station.offlineData && this.station.offlineData.patient_key;
			if (key && window.crypto && crypto.subtle && typeof t8Encrypt === "function")
				args.patient_code_enc = await t8Encrypt(key, code);
			else if (this.station.isOffline())
				return this.block({
					code: "OFFLINE_PATIENT_CODE",
					title: __("Network needed to open the episode"),
					reason: __(
						"The patient code cannot be kept on this device without encryption."
					),
					action: __("Open the episode when the connection returns."),
				});
			else args.patient_code = code;
		} else {
			Object.assign(args, { episode: form.episode, removed_on: form.removed_on });
		}
		return this.send(CEN_EPISODE, args, () => {
			this.episodeForm = null;
			this.done(
				form.mode === "open" ? __("Episode opened") : __("Episode closed"),
				__("The device episode list is updated.")
			);
			this.loadContext(this.department, this.censusDate);
		});
	}

	async send(method, args, onOk) {
		if (this.busy || !this.station.session) return;
		const sig = JSON.stringify([method, args]);
		if (!this.pending || this.pending.sig !== sig)
			this.pending = { sig, method, args, key: uuid4(), ts: clientTs(), onOk };
		const pending = this.pending;
		if (this.station.isOffline()) return this.queue(pending);
		const version = this.station.sessionVersion;
		this.busy = true;
		this.show();
		let res = null;
		let failure = null;
		try {
			res = await this.station.rpc(
				method,
				{ ...pending.args, client_ts: pending.ts },
				pending.key
			);
		} catch (error) {
			failure = error;
		}
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		this.busy = false;
		if (failure && failure.offline) return this.queue(pending);
		if (failure) return this.failure(failure);
		this.pending = null;
		if (res && res.ok === false) return this.block(res.error || {});
		pending.onOk(res || {});
	}

	async queue(pending) {
		try {
			await this.station.queueCall(pending.method, pending.args, pending.key, pending.ts);
		} catch (error) {
			if (error.sessionEnded) return;
			return this.block({
				code: "OFFLINE_STORE_FAILED",
				title: __("Could not keep the data on this device"),
				reason: __("The station storage is not available."),
				action: __("Write the numbers down and enter them when the connection returns."),
			});
		}
		this.pending = null;
		this.episodeForm = null;
		this.done(
			__("Kept on this device"),
			__("It is sent when the connection returns."),
			"info"
		);
	}

	done(title, reason, variant = "ok") {
		this.notice = { variant, title, reason, action: "" };
		this.show();
	}

	failure(error) {
		if (error.status >= 400 && error.status < 500) this.pending = null;
		this.block({
			technical: true,
			title: error.status === 403 ? __("Not permitted") : __("Server error"),
			reason:
				error.status === 403
					? __("This account cannot enter the census of this department.")
					: __("The server could not process the request ({0}).", [error.status || "?"]),
			action: __("Retry, or tell the infection control supervisor."),
		});
	}

	retry() {
		this.station.manualOffline = false;
		if (!navigator.onLine) return this.station.setOffline(true);
		this.station.setOffline(false);
		this.notice = null;
		if (this.pending)
			return this.send(this.pending.method, this.pending.args, this.pending.onOk);
		this.loadContext(this.department, this.censusDate);
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		const station = this.station;
		if (!this.context && !this.loading && !this.contextFailed && !station.isOffline())
			return this.loadContext();
		if (this.loading || this.busy) return station.renderLoading();
		if (!this.context) {
			if (station.isOffline())
				return station.setState(
					"offline",
					this.alertHtml({
						variant: "info",
						title: __("Station offline"),
						reason: __(
							"The census screen needs the network once to load the department."
						),
						action: __("Reconnect, then open the screen again."),
					})
				);
			return station.setState(
				"error",
				this.alertHtml({
					variant: "error",
					technical: true,
					...(this.contextFailed || {}),
				})
			);
		}
		if (!(this.context.departments || []).length)
			return station.setState(
				"empty",
				`<p class="tc-empty">${esc(
					__(
						"No inpatient department is assigned to you. Ask R10 to set your department."
					)
				)}</p>`
			);
		const failed = this.notice && this.notice.variant === "error";
		station.setState(
			station.isOffline() ? "offline" : failed ? "error" : "result",
			`<div class="tc-linen tc-census">
				${
					station.isOffline()
						? this.alertHtml({
								variant: "info",
								title: __("Station offline"),
								reason: __(
									"Census and episodes are kept on this device and sent when the connection returns."
								),
						  })
						: ""
				}
				${
					this.context.missing
						? this.alertHtml({
								variant: "warn",
								title: __("No census for {0} yet", [
									frappe.datetime.str_to_user(this.censusDate),
								]),
								reason: __("Enter the counts of that day below."),
						  })
						: ""
				}
				<div data-region="notice">${this.notice ? this.alertHtml(this.notice) : ""}</div>
				${this.headHtml()}
				${this.episodeForm ? this.episodeFormHtml() : this.censusHtml()}
				${this.episodeForm ? "" : this.episodesHtml()}
			</div>`
		);
	}

	alertHtml(notice) {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(tcErrorTitle(notice))}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
			${typeof tcGuideButton === "function" ? tcGuideButton(notice) : ""}
			${
				notice.technical
					? `<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
							__("Retry")
					  )}</button></div>`
					: ""
			}
		</div>`;
	}

	headHtml() {
		const ctx = this.context;
		const departments = (ctx.departments || [])
			.map((row) => {
				const chosen = row.name === this.department;
				return `<button type="button" class="tc-btn ${
					chosen ? "tc-btn-primary" : "tc-btn-secondary"
				} tc-aud-choice" data-action="cen-department" data-department="${esc(
					row.name
				)}" aria-pressed="${chosen}">${chosen ? "&#10003; " : ""}${esc(
					row.label
				)}</button>`;
			})
			.join("");
		const yesterday = cenAddDays(ctx.today || cenToday(), -1);
		const day = (value, label) =>
			`<button type="button" class="tc-btn ${
				this.censusDate === value ? "tc-btn-primary" : "tc-btn-secondary"
			}" data-action="cen-day" data-day="${esc(value)}" aria-pressed="${
				this.censusDate === value
			}">${esc(label)}</button>`;
		return `<section class="tc-t6-block">
			${
				(ctx.departments || []).length > 1
					? `<h3>${esc(
							__("Department")
					  )}</h3><div class="tc-aud-choices">${departments}</div>`
					: ""
			}
			<div class="tc-actions">${day(yesterday, __("Yesterday"))}${day(
			ctx.today || cenToday(),
			__("Today")
		)}</div>
			<div class="tc-field">
				<label for="tc-cen-date">${esc(__("Census Date"))}</label>
				<input id="tc-cen-date" type="date" data-cen="census_date" max="${esc(
					ctx.today || cenToday()
				)}" value="${esc(this.censusDate)}">
			</div>
		</section>`;
	}

	censusHtml() {
		const current = this.context.census;
		const locked = current && current.locked;
		const bad = (this.notice && this.notice.items) || [];
		const fields = CEN_COUNTS.map(([field, label]) => {
			const error = bad.includes(field);
			return `<div class="tc-field">
				<label for="tc-cen-${field}">${esc(__(label))}${field === "admissions" ? "" : " *"}</label>
				<input id="tc-cen-${field}" class="tc-cen-count${
				error ? " is-error" : ""
			}" type="number" inputmode="numeric" min="0" step="1"
					data-cen="${field}" value="${esc(this.counts[field] || "")}"${locked ? " disabled" : ""}${
				error ? ' aria-invalid="true"' : ""
			}>
			</div>`;
		}).join("");
		const status = current
			? `<p class="tc-hint">${esc(
					__("Census {0} already entered ({1}).", [current.name, __(current.source)])
			  )}${
					locked
						? ` <span class="tc-badge tc-badge-x">${esc(__("Period locked"))}</span>`
						: ""
			  }</p>`
			: "";
		return `<section class="tc-t6-block" aria-label="${esc(__("Daily census"))}">
			<h2 class="tc-exp-title">${esc(
				__("Daily census {0}", [frappe.datetime.str_to_user(this.censusDate)])
			)}</h2>
			${status}
			${fields}
			${
				locked
					? ""
					: `<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary tc-cen-save" data-action="cen-save">${esc(
					current ? __("Save changes") : __("Save census")
				)}</button>
				${
					this.context.prefill && !current
						? `<button type="button" class="tc-btn tc-btn-secondary" data-action="cen-copy">${esc(
								__("Copy from the previous day")
						  )}</button>`
						: ""
				}
			</div>`
			}
		</section>`;
	}

	episodesHtml() {
		const rows = (this.context.episodes || [])
			.map((row) => {
				const badge = TcCensus.bundleBadge(row.bundle_result);
				return `<li class="tc-cen-episode">
					<p><span class="tc-mono">${esc(row.patient_code_masked || "")}</span> · ${esc(
					__(row.device_type)
				)}</p>
					<p class="tc-hint">${esc(
						__("Inserted {0} · day {1}", [
							frappe.datetime.str_to_user(row.inserted_on),
							row.device_days,
						])
					)}
						· ${esc(__("Bundle today"))}: <span class="tc-badge tc-badge-${badge.cls}">${esc(
					badge.label
				)}</span></p>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="cen-close" data-episode="${esc(
						row.name
					)}">${esc(__("Close episode"))}</button>
				</li>`;
			})
			.join("");
		return `<section class="tc-t6-block" aria-label="${esc(__("Open device episodes"))}">
			<h2 class="tc-exp-title">${esc(__("Open device episodes"))}</h2>
			${
				rows
					? `<ul class="tc-cen-episodes">${rows}</ul>`
					: `<p class="tc-empty">${esc(__("No open device episode."))}</p>`
			}
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="cen-open">${esc(
					__("Open device episode")
				)}</button>
			</div>
			<p class="tc-hint">${esc(
				__(
					"The patient code is encrypted and shown masked. Do not enter the patient name."
				)
			)}</p>
		</section>`;
	}

	optionHtml(action, value, label, chosen) {
		return `<button type="button" class="tc-btn tc-btn-secondary tc-exp-option${
			chosen ? " is-chosen" : ""
		}" data-action="${action}" data-value="${esc(value)}" aria-pressed="${chosen}">${
			chosen ? '<span aria-hidden="true">&#10003; </span>' : ""
		}${esc(label)}</button>`;
	}

	episodeFormHtml() {
		const form = this.episodeForm;
		const buttons = `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-primary tc-cen-save" data-action="cen-ep-save">${esc(
				form.mode === "open" ? __("Open episode") : __("Close episode")
			)}</button>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="cen-ep-cancel">${esc(
				__("Cancel")
			)}</button>
		</div>`;
		if (form.mode === "close") {
			const row =
				(this.context.episodes || []).find((item) => item.name === form.episode) || {};
			return `<section class="tc-t6-block" aria-label="${esc(__("Close episode"))}">
				<h2 class="tc-exp-title">${esc(__("Close episode"))} <span class="tc-mono">${esc(
				row.patient_code_masked || ""
			)}</span></h2>
				<p class="tc-hint">${esc(__(row.device_type || ""))} · ${esc(
				__("Inserted {0}", [frappe.datetime.str_to_user(row.inserted_on || "")])
			)}</p>
				<div class="tc-field">
					<label for="tc-cen-removed">${esc(__("Removed On"))}</label>
					<input id="tc-cen-removed" type="date" data-cen="ep_removed_on" min="${esc(
						row.inserted_on || ""
					)}" max="${esc(cenToday())}" value="${esc(form.removed_on)}">
				</div>
				${buttons}
			</section>`;
		}
		const devices = CEN_DEVICES.map((value) =>
			this.optionHtml("cen-device", value, __(value), form.device_type === value)
		).join("");
		const sexes = CEN_SEX.map((value) =>
			this.optionHtml("cen-sex", value, __(value), form.sex === value)
		).join("");
		return `<section class="tc-t6-block" aria-label="${esc(__("Open device episode"))}">
			<h2 class="tc-exp-title">${esc(__("Open device episode"))}</h2>
			<div class="tc-exp-options">${devices}</div>
			<div class="tc-field">
				<label for="tc-cen-code">${esc(__("Patient Code"))} *</label>
				<input id="tc-cen-code" type="password" autocomplete="off" maxlength="64" data-cen="ep_patient_code" value="${esc(
					form.patient_code
				)}">
				<p class="tc-t6-hint">${esc(
					__("The code is encrypted and shown masked; do not enter the patient name.")
				)}</p>
			</div>
			<div class="tc-field">
				<label for="tc-cen-birth">${esc(__("Birth Year"))}</label>
				<input id="tc-cen-birth" type="number" inputmode="numeric" min="1900" max="${new Date().getFullYear()}" data-cen="ep_birth_year" value="${esc(
			form.birth_year
		)}">
			</div>
			<div class="tc-exp-options tc-exp-inline">${sexes}</div>
			<div class="tc-field">
				<label for="tc-cen-inserted">${esc(__("Inserted On"))}</label>
				<input id="tc-cen-inserted" type="date" data-cen="ep_inserted_on" max="${esc(
					cenToday()
				)}" value="${esc(form.inserted_on)}">
			</div>
			${buttons}
		</section>`;
	}
}

window.CensusStation = CensusStation;
window.TcCensus = TcCensus;
