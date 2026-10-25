/* global uuid4, clientTs, esc, t5Kind, t5Date, t5IndicatorLabel, T5Load */
// Màn T5b dỡ mẻ và giải phóng (SCR-10, FEAT-023, UC-10) trên Page station: chế độ "Dỡ mẻ" của màn T5.
// Frappe nối file này sau station_t5.js (hook page_js) nên dùng chung uuid4/clientTs/esc/t5Kind/t5IndicatorLabel.
// T5Load đổi `station.screen` sang T5Release khi người dùng chọn "Dỡ mẻ / giải phóng"; nút "Nạp mẻ" trả màn về T5Load.
// Quét QR máy và QR mã mẻ (hai mã, thứ tự bất kỳ, server kiểm lại) mở mẻ: kết quả chu trình, chỉ thị, giải phóng bằng PIN
// R02 (hoặc R01 kèm lý do khẩn), mẻ Không đạt, đọc BI. Lỗi chặn = alert-error inline (kết quả → lý do → hành động).

const T5B_CONTEXT = "tracecore.v1.release.context";
const T5B_RESULT = "tracecore.v1.release.cycle_result";
const T5B_INDICATOR = "tracecore.v1.release.indicator";
const T5B_RELEASE = "tracecore.v1.release.release";
const T5B_REJECT = "tracecore.v1.release.reject";
const T5B_BI = "tracecore.v1.release.bi_result";
const T5B_VERIFY_PIN = "tracecore.v1.station.verify_pin";
// từ chối làm mẻ đang mở không còn dùng được → bỏ mẻ để quét mẻ khác
const T5B_RESET_CODES = [
	"LOAD_NOT_FOUND",
	"LOAD_NOT_OPEN",
	"STATION_WRONG_STEP",
	"EQUIPMENT_MISMATCH",
];

class T5Release {
	constructor(station, back) {
		this.station = station;
		this.back = back; // màn T5Load để quay lại
		this.result = station.result;
		this.input = station.input;
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.reset();
		this.result.addEventListener("change", (event) => this.onChange(event));
		this.result.addEventListener("input", (event) => this.onInput(event));
	}

	get dialogOpen() {
		return false;
	}

	reset() {
		this.mode = "unload"; // unload | bi
		this.scans = { equipment_raw: "", load_raw: "" };
		this.ctx = null; // kết quả release.context
		this.notice = null;
		this.form = {
			result: "",
			confirmed: false,
			pin: "",
			review: false,
			reason: "",
			redo: "T4",
			reject: "",
		};
		this.indicator = {}; // nháp từng chỉ thị: {kind: {result, test_date, lot, incubator}}
		this.biLoad = "";
		this.biResult = "";
		this.finished = null;
	}

	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.reset();
		this.back.clearSession();
		this.station.screen = this.back;
		this.input.placeholder = __("Scan Set ID...");
		this.input.setAttribute("aria-label", __("Scan Set ID"));
	}

	// ---- quét ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline()) return this.station.setOffline(true);
		const code = t5Kind(raw);
		if (this.mode === "bi") {
			if (code.kind !== "load") return this.blocked(this.scanHint());
			this.biLoad = raw;
			this.notice = null;
			return this.show();
		}
		if (code.kind !== "equipment" && code.kind !== "load")
			return this.blocked(this.scanHint());
		this.finished = null;
		this.scans[code.kind === "equipment" ? "equipment_raw" : "load_raw"] = raw;
		this.notice = null;
		if (this.scans.equipment_raw && this.scans.load_raw) return this.openLoad();
		this.show();
	}

	scanHint() {
		return {
			title: __("Invalid code"),
			reason: __(
				"This screen needs the QR code of the sterilizer and the QR code of the load."
			),
			action: __("Scan the QR code of the sterilizer, then the QR code on the load label."),
		};
	}

	loadName() {
		return t5Kind(this.scans.load_raw).id || "";
	}

	args(extra = {}) {
		return {
			load: this.loadName(),
			equipment_raw: this.scans.equipment_raw,
			load_raw: this.scans.load_raw,
			station: this.station.station,
			...extra,
		};
	}

	openLoad() {
		this.request(T5B_CONTEXT, this.args(), (res) => {
			this.ctx = res.load;
			this.show();
		});
	}

	async request(method, args, onOk) {
		if (this.busy || !this.station.session) return;
		const version = this.station.sessionVersion;
		const sig = method + JSON.stringify(args);
		if (!this.pending || this.pending.sig !== sig) {
			this.pending = { sig, method, args, onOk, key: uuid4(), ts: clientTs() };
		}
		const pending = this.pending;
		this.busy = method;
		let response = null;
		let failure = null;
		const started = performance.now();
		try {
			response = await this.station.rpc(
				method,
				{ ...args, client_ts: pending.ts },
				pending.key
			);
		} catch (error) {
			failure = error;
		}
		// phiên đã kết thúc hoặc đổi người trong lúc chờ: clearSession đã xóa màn, bỏ câu trả lời cũ
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		if (!failure) {
			this.pending = null;
			this.result.dataset.ms = String(Math.round(performance.now() - started));
		}
		this.busy = null;
		if (failure) this.failure(failure);
		else if (response && response.ok === false) this.reject(response.error);
		else onOk(response);
		this.station.focus();
	}

	retry() {
		this.station.manualOffline = false;
		if (!navigator.onLine) return this.station.setOffline(true);
		this.station.setOffline(false);
		const pending = this.pending;
		if (pending) return this.request(pending.method, pending.args, pending.onOk);
		this.notice = null;
		this.show();
	}

	failure(error) {
		if (error.offline && navigator.onLine === false) return this.station.setOffline(true);
		if (error.status >= 400 && error.status < 500) this.pending = null;
		let notice;
		if (error.offline) {
			notice = {
				title: __("No answer from the server"),
				reason: __(
					"The request got no answer in time; the server may already have recorded it."
				),
				action: __("Retry: the same request is sent again and is never recorded twice."),
			};
		} else if (error.status === 403) {
			notice = {
				title: __("Not permitted"),
				reason: __("This account cannot unload or release sterilization loads."),
				action: __("Log in with the station account or call R10."),
			};
		} else {
			notice = {
				title: __("Server error"),
				reason: __("The server could not process the request ({0}).", [
					error.status || "?",
				]),
				action: __("Retry, or call R02 if it happens again."),
			};
		}
		this.notice = { variant: "error", technical: true, ...notice };
		this.show();
	}

	reject(error) {
		if (T5B_RESET_CODES.includes(error.code)) {
			this.ctx = null;
			this.scans = { equipment_raw: "", load_raw: "" };
		}
		this.notice = { variant: "error", ...error };
		this.show();
	}

	blocked(notice) {
		this.notice = { variant: "error", ...notice };
		this.show();
	}

	// ---- thao tác ----
	setMode(mode) {
		if (this.busy || (mode !== "unload" && mode !== "bi")) return;
		this.mode = mode;
		this.notice = null;
		this.show();
		this.station.focus(true);
	}

	backToLoad() {
		if (this.busy) return;
		this.station.screen = this.back;
		this.back.mode = "load";
		this.back.notice = null;
		this.back.show();
		this.station.focus(true);
	}

	recordResult() {
		if (!this.form.result) {
			return this.blocked({
				title: __("Cycle result is not chosen"),
				reason: __("The cycle result needs a Pass or Fail."),
				action: __("Choose Pass or Fail, tick the confirmation, then record the result."),
			});
		}
		this.request(
			T5B_RESULT,
			this.args({ result: this.form.result, confirmed: this.form.confirmed ? 1 : 0 }),
			() => this.afterWrite(__("Cycle result recorded"))
		);
	}

	recordIndicator(kind) {
		const draft = this.indicator[kind] || {};
		const result = kind === "biological" ? "Pending" : draft.result;
		if (!result) {
			return this.blocked({
				title: __("Indicator result is not chosen"),
				reason: __("Choose Pass or Fail for the indicator."),
				action: __("Choose the result, then record it."),
			});
		}
		const extra = { indicator: kind, result };
		if (kind === "bowie_dick") extra.test_date = draft.test_date || this.today();
		if (kind === "biological") {
			extra.lot = draft.lot || "";
			extra.incubator = draft.incubator || "";
		}
		this.request(T5B_INDICATOR, this.args(extra), () =>
			this.afterWrite(__("Indicator {0} recorded", [t5IndicatorLabel(kind)]))
		);
	}

	today() {
		return new Date().toISOString().slice(0, 10);
	}

	afterWrite(title) {
		// ghi xong thì mở lại thẻ mẻ để thấy trạng thái chỉ thị và điều kiện còn thiếu
		this.notice = { variant: "ok", title };
		this.request(T5B_CONTEXT, this.args(), (res) => {
			this.ctx = res.load;
			this.show();
		});
	}

	async verifiedProof() {
		const pin = (this.form.pin || "").trim();
		if (!/^\d{6}$/.test(pin)) {
			this.blocked({
				title: __("PIN is required"),
				reason: __("Only R02 releases a load with the PIN; R01 releases in an emergency."),
				action: __(
					"R02 signs in with the card at this station and enters the 6-digit PIN."
				),
			});
			return null;
		}
		const version = this.station.sessionVersion;
		try {
			const res = await this.station.rpc(T5B_VERIFY_PIN, {
				token: this.station.session.token,
				pin,
				client_ts: clientTs(),
			});
			if (version !== this.station.sessionVersion) return null;
			this.form.pin = "";
			if (res && res.ok && res.proof) return res.proof;
			this.blocked({ ...(res && res.error) });
		} catch (error) {
			if (!error.sessionEnded) this.failure(error);
		}
		return null;
	}

	async release() {
		if (this.busy) return;
		const proof = await this.verifiedProof();
		if (!proof) return;
		this.request(
			T5B_RELEASE,
			this.args({
				pin_proof: proof,
				review_confirmed: this.form.review ? 1 : 0,
				emergency_reason: this.form.reason || "",
			}),
			(res) => {
				this.finished = res;
				this.ctx = null;
				this.scans = { equipment_raw: "", load_raw: "" };
				this.notice = {
					variant: "ok",
					title:
						res.status === "Quarantine"
							? __(
									"Load {0} is in quarantine until the biological indicator is read",
									[res.load]
							  )
							: __("Load {0} released", [res.load]),
					reason: __("{0} set(s) updated.", [(res.sets || []).length]),
					action:
						res.status === "Quarantine"
							? __("Read the biological indicator, then record it with Read BI.")
							: __("The packs can now go to the sterile store (T6)."),
				};
				this.show();
			}
		);
	}

	rejectLoad() {
		this.request(
			T5B_REJECT,
			this.args({ reason: this.form.reject || "", redo_from: this.form.redo }),
			(res) => {
				this.ctx = null;
				this.scans = { equipment_raw: "", load_raw: "" };
				this.notice = {
					variant: "warn",
					title: __("Load {0} failed", [res.load]),
					reason: __(
						"Every pack of the load is no longer valid; the sets go back to reprocessing."
					),
					action: __("Take the packs back to the dirty zone."),
				};
				this.show();
			}
		);
	}

	recordBi() {
		if (!this.biResult || !this.biLoad) {
			return this.blocked({
				title: __("Biological indicator result is not chosen"),
				reason: __("Scan the load and choose negative (Pass) or positive (Fail)."),
				action: __("Scan the QR code on the load label, then choose the result."),
			});
		}
		this.request(
			T5B_BI,
			{
				load: t5Kind(this.biLoad).id || "",
				result: this.biResult,
				station: this.station.station,
			},
			(res) => {
				const failed = res.status === "Failed" || res.recall_needed;
				this.notice = {
					variant: failed ? "warn" : "ok",
					title: res.recall_needed
						? __("Positive indicator after release: recall needed")
						: res.status === "Failed"
						? __("Load {0} failed", [res.load])
						: __("Load {0} released", [res.load]),
					reason: res.recall_needed
						? __("Call R01: packs of this load may already be issued or used.")
						: __("The biological indicator was recorded."),
					action: __("Scan the next load."),
				};
				this.biLoad = "";
				this.biResult = "";
				this.show();
			}
		);
	}

	onAction(action, button) {
		const data = (button && button.dataset) || {};
		const handlers = {
			retry: () => this.retry(),
			"t5b-mode": () => this.setMode(data.mode),
			"t5b-back": () => this.backToLoad(),
			"t5b-result": () => {
				this.form.result = data.value;
				this.show();
			},
			"t5b-record-result": () => this.recordResult(),
			"t5b-ind-result": () => {
				this.indicator[data.kind] = {
					...(this.indicator[data.kind] || {}),
					result: data.value,
				};
				this.show();
			},
			"t5b-record-ind": () => this.recordIndicator(data.kind),
			"t5b-release": () => this.release(),
			"t5b-redo": () => {
				this.form.redo = data.value;
				this.show();
			},
			"t5b-reject": () => this.rejectLoad(),
			"t5b-bi-result": () => {
				this.biResult = data.value;
				this.show();
			},
			"t5b-bi-record": () => this.recordBi(),
			"t5b-reset": () => {
				this.ctx = null;
				this.scans = { equipment_raw: "", load_raw: "" };
				this.notice = null;
				this.show();
			},
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	onChange(event) {
		if (this.station.screen !== this) return;
		const target = event.target;
		if (target.dataset.t5bConfirm !== undefined) this.form.confirmed = target.checked;
		else if (target.dataset.t5bReview !== undefined) this.form.review = target.checked;
		else if (target.dataset.t5bInd) {
			const kind = target.dataset.t5bInd;
			this.indicator[kind] = {
				...(this.indicator[kind] || {}),
				[target.dataset.t5bField]: target.value,
			};
		}
	}

	onInput(event) {
		if (this.station.screen !== this) return;
		const target = event.target;
		if (target.dataset.t5bPin !== undefined) this.form.pin = target.value;
		else if (target.dataset.t5bReason !== undefined) this.form.reason = target.value;
		else if (target.dataset.t5bRejectReason !== undefined) this.form.reject = target.value;
		else if (target.dataset.t5bInd) {
			const kind = target.dataset.t5bInd;
			this.indicator[kind] = {
				...(this.indicator[kind] || {}),
				[target.dataset.t5bField]: target.value,
			};
		}
	}

	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	show() {
		const text = this.ctx
			? __("Scan Set ID...")
			: this.mode === "bi"
			? __("Scan the QR code on the load label...")
			: __("Scan the sterilizer QR code and the load QR code...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
		if (this.offline && !this.ctx) return this.station.setState("offline", this.offlineHtml());
		const state = this.notice && this.notice.variant === "error" ? "error" : "result";
		this.station.setState(
			state,
			`<div class="tc-t2 tc-t5 tc-t5b" data-mode="${esc(this.mode)}">
				${this.modeHtml()}
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.mode === "bi" ? this.biHtml() : this.ctx ? this.contextHtml() : this.idleHtml()}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
	}

	modeHtml() {
		const chip = (mode, label) =>
			`<button type="button" class="tc-chip" data-action="t5b-mode" data-mode="${mode}"
				aria-pressed="${this.mode === mode ? "true" : "false"}">${esc(label)}</button>`;
		return `<div class="tc-chips" role="group" aria-label="${esc(__("Unload and release"))}">
			<button type="button" class="tc-chip" data-action="t5b-back" aria-pressed="false">${esc(
				__("Load sterilizer")
			)}</button>
			${chip("unload", __("Unload and release"))}
			${chip("bi", __("Read BI"))}
		</div>`;
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		const items = (notice.items || []).map((item) => `<li>${esc(item)}</li>`).join("");
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(notice.title)}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${items ? `<ul class="tc-alert-items">${items}</ul>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
			${buttons}
		</div>`;
	}

	standardButtons() {
		return `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
				__("Retry")
			)}</button>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="offline">${esc(
				__("Switch to offline")
			)}</button>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
				__("Call R02")
			)}</button>
		</div>`;
	}

	offlineHtml() {
		return this.alertHtml(
			{
				variant: "info",
				title: __("Station offline"),
				reason: __("Unloading and releasing a load needs a network connection."),
				action: __("Retry when the connection returns."),
			},
			`<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
					__("Retry")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
					__("Call R02")
				)}</button>
			</div>`
		);
	}

	noticeHtml() {
		let html = "";
		if (this.busy) {
			html += `<p class="tc-loading" role="status" aria-busy="true">${esc(
				__("Loading...")
			)}</p>`;
		}
		if (this.notice) {
			const standalone = !this.ctx && this.notice.variant === "error";
			html += this.alertHtml(
				this.notice,
				this.notice.technical || standalone ? this.standardButtons() : ""
			);
		}
		return html;
	}

	idleHtml() {
		const have = (value, label) =>
			`<li>${esc(label)}: <b>${
				value ? "&#10003; " + esc(value) : esc(__("not scanned"))
			}</b></li>`;
		return `<p class="tc-empty">${esc(
			__("Scan the sterilizer QR code and the load QR code.")
		)}</p>
			<ul class="tc-t6-hint">
				${have(this.scans.equipment_raw, __("Sterilizer"))}
				${have(this.scans.load_raw, __("Load"))}
			</ul>`;
	}

	statusText(value) {
		return (
			{
				Pass: __("Pass", null, "Step Gate Result"),
				Fail: __("Fail", null, "Step Gate Result"),
				Missing: __("Not recorded"),
				Pending: __("Waiting to be read"),
			}[value] || value
		);
	}

	chip(action, field, value, label, active) {
		return `<button type="button" class="tc-chip" data-action="${action}" data-kind="${esc(
			field
		)}"
			data-value="${esc(value)}" aria-pressed="${active ? "true" : "false"}">${esc(label)}</button>`;
	}

	passFail(action, kind, current) {
		return `<div class="tc-chips" role="group">
			${this.chip(action, kind, "Pass", __("Pass", null, "Step Gate Result"), current === "Pass")}
			${this.chip(action, kind, "Fail", __("Fail", null, "Step Gate Result"), current === "Fail")}
		</div>`;
	}

	packsHtml(ctx) {
		return `<table class="tc-t6-table">
			<thead><tr><th scope="col">${esc(__("Cycle ID"))}</th><th scope="col">${esc(
			__("Set ID")
		)}</th><th scope="col">${esc(__("Set Name"))}</th></tr></thead>
			<tbody>${(ctx.packs || [])
				.map(
					(row) =>
						`<tr><td class="tc-mono">${esc(
							row.cycle_id
						)}</td><td class="tc-mono">${esc(row.set_id)}</td><td>${esc(
							row.set_name || ""
						)}</td></tr>`
				)
				.join("")}</tbody>
		</table>`;
	}

	indicatorHtml(kind, state) {
		const draft = this.indicator[kind] || {};
		let fields = "";
		if (kind === "bowie_dick") {
			fields = `<div class="tc-field"><label>${esc(__("Test date"))}
				<input type="date" data-t5b-ind="${kind}" data-t5b-field="test_date" value="${esc(
				draft.test_date || this.today()
			)}"></label></div>`;
		} else if (kind === "biological") {
			fields = `<div class="tc-field"><label>${esc(__("Indicator lot"))}
				<input type="text" autocomplete="off" data-t5b-ind="${kind}" data-t5b-field="lot" value="${esc(
				draft.lot || ""
			)}"></label></div>
				<div class="tc-field"><label>${esc(__("Incubator"))}
				<input type="text" autocomplete="off" data-t5b-ind="${kind}" data-t5b-field="incubator" value="${esc(
				draft.incubator || ""
			)}"></label></div>`;
		}
		const choose =
			kind === "biological" ? "" : this.passFail("t5b-ind-result", kind, draft.result);
		return `<section class="tc-t4-block">
			<h3>${esc(t5IndicatorLabel(kind))}
				<span class="tc-badge${
					state === "Pass" ? " tc-badge-g" : state === "Fail" ? " tc-badge-r" : ""
				}">${esc(this.statusText(state))}</span></h3>
			${choose}${fields}
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="t5b-record-ind" data-kind="${kind}">${esc(
			kind === "biological" ? __("Start incubation") : __("Record indicator")
		)}</button></div>
		</section>`;
	}

	contextHtml() {
		const ctx = this.ctx;
		const missing = ctx.missing || [];
		const form = this.form;
		const indicators = Object.entries(ctx.indicator_state || {})
			.map(([kind, state]) => this.indicatorHtml(kind, state))
			.join("");
		return `<section class="tc-t4-block" aria-label="${esc(__("Load"))}">
			<div class="tc-res-head">
				<b class="tc-code">${esc(ctx.load)}</b>
				<span class="tc-badge">${esc(__(ctx.status, null, "Sterilization Load"))}</span>
			</div>
			<dl class="tc-res-grid">
				<dt>${esc(__("Sterilizer"))}</dt><dd>${esc(ctx.equipment ? ctx.equipment.equipment_name : "")}</dd>
				<dt>${esc(__("Program"))}</dt><dd>${esc(ctx.program ? ctx.program.program_name : "")}</dd>
				<dt>${esc(__("Cycle data"))}</dt><dd>${esc(
			ctx.data_complete ? __("Entered and confirmed") : __("Not entered yet")
		)}${
			ctx.needs_review
				? ` <span class="tc-badge tc-badge-o">${esc(__("Needs review"))}</span>`
				: ""
		}</dd>
			</dl>
			${this.packsHtml(ctx)}
		</section>
		<section class="tc-t4-block">
			<h3>${esc(__("Cycle result (applies to every pack)"))}
				<span class="tc-badge${
					ctx.cycle_result === "Pass"
						? " tc-badge-g"
						: ctx.cycle_result === "Fail"
						? " tc-badge-r"
						: ""
				}">${esc(
			ctx.cycle_result ? this.statusText(ctx.cycle_result) : this.statusText("Missing")
		)}</span></h3>
			${this.passFail("t5b-result", "result", form.result)}
			<label class="tc-t2-confirm"><input type="checkbox" class="tc-check" data-t5b-confirm${
				form.confirmed ? " checked" : ""
			}><span>${esc(
			__("I confirm that the result above matches the sterilizer printout or screen.")
		)}</span></label>
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="t5b-record-result">${esc(
				__("Record cycle result")
			)}</button></div>
		</section>
		${indicators}
		${this.releaseHtml(ctx, missing)}`;
	}

	releaseHtml(ctx, missing) {
		const form = this.form;
		const review = ctx.needs_review
			? `<label class="tc-t2-confirm"><input type="checkbox" class="tc-check" data-t5b-review${
					form.review ? " checked" : ""
			  }><span>${esc(
					__("R02 reviewed the parameters outside the program range.")
			  )}</span></label>`
			: "";
		const waiting = missing.length
			? `<p class="tc-t6-hint">${esc(
					__("Still missing: {0}.", [
						missing.map((m) => this.missingLabel(m)).join(", "),
					])
			  )}</p>`
			: "";
		return `<section class="tc-t4-block">
			<h3>${esc(__("Release", null, "Sterilization Load"))}</h3>
			${waiting}${review}
			<div class="tc-field">
				<label for="tc-t5b-pin">${esc(__("R02 PIN"))}</label>
				<input id="tc-t5b-pin" type="password" inputmode="numeric" maxlength="6" autocomplete="off" data-t5b-pin value="">
				<p class="tc-hint">${esc(
					__("R02 signs in with the card at this station and enters the 6-digit PIN.")
				)}</p>
			</div>
			<div class="tc-field">
				<label for="tc-t5b-reason">${esc(__("Emergency release reason (R01 only)"))}</label>
				<textarea id="tc-t5b-reason" rows="2" data-t5b-reason>${esc(form.reason)}</textarea>
			</div>
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="t5b-release">${esc(
				__("Release the load")
			)}</button></div>
		</section>
		<section class="tc-t4-block">
			<h3>${esc(__("Reject the load"))}</h3>
			<p class="tc-t6-hint">${esc(__("Use it when the cycle or an indicator failed."))}</p>
			<div class="tc-chips" role="group" aria-label="${esc(__("Restart from"))}">
				${this.chip("t5b-redo", "redo", "T4", __("Restart from T4"), form.redo === "T4")}
				${this.chip("t5b-redo", "redo", "T2", __("Restart from T2"), form.redo === "T2")}
			</div>
			<div class="tc-field">
				<label for="tc-t5b-reject">${esc(__("Reason"))}</label>
				<textarea id="tc-t5b-reject" rows="2" data-t5b-reject-reason>${esc(form.reject)}</textarea>
			</div>
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-danger" data-action="t5b-reject">${esc(
				__("Reject: the load failed")
			)}</button></div>
		</section>`;
	}

	missingLabel(code) {
		return code === "cycle_result"
			? __("cycle result")
			: code === "review"
			? __("review confirmation")
			: t5IndicatorLabel(code);
	}

	biHtml() {
		return `<section class="tc-t4-block">
			<h3>${esc(__("Biological indicator of a load in quarantine"))}</h3>
			<p class="tc-t6-hint">${esc(
				this.biLoad
					? __("Load {0}", [t5Kind(this.biLoad).id || this.biLoad])
					: __("Scan the QR code on the load label.")
			)}</p>
			<div class="tc-chips" role="group" aria-label="${esc(__("Biological indicator"))}">
				${this.chip("t5b-bi-result", "bi", "Pass", __("Negative (Pass)"), this.biResult === "Pass")}
				${this.chip("t5b-bi-result", "bi", "Fail", __("Positive (Fail)"), this.biResult === "Fail")}
			</div>
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="t5b-bi-record">${esc(
				__("Record the biological indicator")
			)}</button></div>
		</section>`;
	}
}

// T5Load mở chế độ dỡ mẻ qua nút "Dỡ mẻ / giải phóng" (xem station_t5.js)
T5Load.prototype.openRelease = function () {
	if (this.busy || typeof T5Release === "undefined") return;
	this.releaseScreen = this.releaseScreen || new T5Release(this.station, this);
	const screen = this.releaseScreen;
	screen.reset();
	this.station.screen = screen;
	screen.show();
	this.station.focus(true);
};
