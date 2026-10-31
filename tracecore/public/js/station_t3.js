/* global tcErrorTitle, tcGuideButton */
/* global uuid4, clientTs, esc */
// Màn T3 kiểm tra – lắp ráp theo BOM (SCR-07, FEAT-020) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// Ô quét của shell luôn ở đầu và có focus: quét Set ID mở bản nháp kiểm đếm (BOM kèm ảnh), quét mã GIAI dụng cụ tự tick
// dòng BOM (FR-M1-02.2/.4). Mỗi thao tác dòng gọi RPC ngay vào bản nháp trên server nên R02 đổi thẻ (PIN) không mất việc.
// Lỗi chặn = alert-error inline (kết quả → lý do → hành động); sau mỗi thao tác trả focus về ô quét.

const T3_OPEN = "tracecore.v1.assembly.open";
const T3_LINE = "tracecore.v1.assembly.line";
const T3_CONFIRM = "tracecore.v1.assembly.confirm_shortage";
const T3_SUBMIT = "tracecore.v1.assembly.submit";
const T3_VERIFY_PIN = "tracecore.v1.station.verify_pin";
const T3_QUEUE_MAX = 20;
// từ chối làm bản nháp đang mở không còn dùng được → bỏ để quét lại Set ID
const T3_RESET_CODES = [
	"ASSEMBLY_NOT_FOUND",
	"ASSEMBLY_CLOSED",
	"STATION_WRONG_STEP",
	"GATE_PREV_NOT_PASSED",
	"STATUS_INVALID_FOR_STATION",
	"SET_END_OF_LIFE",
];
const T3_LINE_BADGE = { Enough: "g", Short: "r", Over: "o" };

function t3Kind(raw) {
	// phân loại sơ bộ trên kiosk; server luôn kiểm lại (gs1.parse_scan): GIAI dụng cụ kết thúc bằng I-########
	return /I-\d{8}$/.test(String(raw || "").trim()) ? "instrument" : "set";
}

function t3Disabled(flag) {
	return flag ? " disabled" : "";
}

function t3GateLabel(step) {
	return (window.tcGateLabels || {})[step] || step;
}

function t3LineLabel(status) {
	return (
		{
			Enough: __("Enough", null, "Assembly Line"),
			Short: __("Short", null, "Assembly Line"),
			Over: __("Over", null, "Assembly Line"),
		}[status] || __("Not counted")
	);
}

class T3Assembly {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.busy = null;
		this.offline = false;
		this.scanQueue = []; // mã quét đến khi đang chờ máy chủ: không được mất (chạy lần lượt khi xong)
		this.reset();
		this.result.addEventListener("change", (event) => this.onChange(event));
		this.result.addEventListener("input", (event) => this.onInput(event));
	}

	get dialogOpen() {
		return Boolean(this.form); // biểu mẫu hỏng/thay, rẽ nhánh, R02 xác nhận giữ focus cho ô nhập của nó
	}

	reset() {
		this.asm = null; // ngữ cảnh kiểm đếm từ server (assembly.open/line/...)
		this.notice = null;
		this.form = null; // {kind: "damage"|"branch"|"confirm", ...}
	}

	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.scanQueue = [];
		this.reset();
		this.updatePlaceholder();
	}

	updatePlaceholder() {
		const text = this.asm
			? __("Scan the instrument code or the next Set ID...")
			: __("Scan Set ID...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	// ---- quét và gọi RPC ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus(true);
		if (this.station.isOffline()) return this.station.setOffline(true);
		if (this.busy) {
			if (this.scanQueue.length < T3_QUEUE_MAX) this.scanQueue.push(raw);
			return this.station.focus(true);
		}
		this.form = null;
		if (this.asm && this.asm.docstatus === 0 && t3Kind(raw) === "instrument") {
			await this.request(T3_LINE, { assembly: this.asm.assembly, raw }, (res) =>
				this.onLine(res)
			);
		} else {
			await this.request(T3_OPEN, { raw }, (res) => this.onOpen(res));
		}
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
		this.show();
		let response = null;
		let failure = null;
		const started = performance.now();
		try {
			response = await this.station.rpc(
				method,
				{ ...args, station: this.station.station, client_ts: pending.ts },
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
		if (!failure) this.markOnline();
		if (failure) this.failure(failure);
		else if (response && response.ok === false) this.reject(response.error, method);
		else onOk(response);
		this.station.focus(true);
		this.runQueuedScan();
	}

	runQueuedScan() {
		if (this.busy || !this.scanQueue.length) return;
		this.scan(this.scanQueue.shift());
	}

	markOnline() {
		if (!this.offline) return;
		this.offline = false;
		this.station.manualOffline = false;
		this.station.banner.hidden = true;
		this.station.root.dataset.offline = "0";
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
				reason: __("This account cannot count instruments at this station."),
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

	reject(error, method) {
		// lỗi của lần mở bộ (Set ID lạ, chưa rửa Đạt, thiếu BOM...) không giữ bản nháp cũ; lỗi dòng giữ để sửa tiếp
		if (method === T3_OPEN || T3_RESET_CODES.includes(error.code)) this.asm = null;
		this.notice = { variant: "error", ...error };
		this.show();
	}

	onOpen(res) {
		this.asm = res;
		this.notice = null;
		this.form = null;
		this.show();
	}

	onLine(res) {
		this.asm = res;
		this.notice = res.warning ? { variant: "warn", ...res.warning } : null;
		this.show();
	}

	// ---- thao tác trên màn ----
	line(code) {
		return this.asm && this.asm.lines.find((row) => row.instrument === code);
	}

	setQty(code, qty) {
		if (!this.asm || this.busy || this.offline || qty < 0) return;
		this.request(
			T3_LINE,
			{ assembly: this.asm.assembly, instrument: code, actual_qty: qty },
			(res) => this.onLine(res)
		);
	}

	onAction(action, button) {
		const data = (button && button.dataset) || {};
		const handlers = {
			retry: () => this.retry(),
			"t3-dec": () => this.step(data.instrument, -1),
			"t3-inc": () => this.step(data.instrument, 1),
			"t3-full": () => this.setQty(data.instrument, this.line(data.instrument).bom_qty),
			"t3-all": () => this.allOk(),
			"t3-damage": () => this.openForm({ kind: "damage", instrument: data.instrument }),
			"t3-disposition": () => this.setForm("disposition", data.value),
			"t3-save-damage": () => this.saveDamage(),
			"t3-branch": () => this.openForm({ kind: "branch", branch: "", reason: "" }),
			"t3-branch-pick": () => this.setForm("branch", data.value),
			"t3-branch-save": () => this.saveBranch(),
			"t3-confirm": () => this.openForm({ kind: "confirm", reason: "", pin: "" }),
			"t3-confirm-save": () => this.saveConfirm(),
			"t3-form-cancel": () => this.closeForm(),
			"t3-submit": () => this.submit(),
			"t3-next": () => this.goNext(),
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	step(code, delta) {
		const row = this.line(code);
		if (row) this.setQty(code, Math.max(0, (row.counted ? row.actual_qty : 0) + delta));
	}

	allOk() {
		if (!this.asm || this.busy || this.offline) return;
		this.request(T3_LINE, { assembly: this.asm.assembly, all_ok: 1 }, (res) =>
			this.onLine(res)
		);
	}

	openForm(form) {
		if (!this.asm || this.asm.docstatus !== 0) return;
		if (form.kind === "damage") {
			const row = this.line(form.instrument);
			Object.assign(form, {
				damaged: row.damaged_qty || 1,
				replaced: row.replaced_qty || 0,
				disposition: row.disposition || "",
				replacement: row.replacement_instrument || "",
				note: row.note || "",
				photo: row.photo || "",
				uploading: false,
			});
		}
		this.form = form;
		this.notice = null;
		this.show();
		const first = this.result.querySelector("[data-form]");
		if (first) first.focus();
	}

	setForm(field, value) {
		if (!this.form) return;
		this.form[field] = value;
		this.show();
	}

	closeForm() {
		this.form = null;
		this.show();
		this.station.focus(true);
	}

	blocked(notice) {
		this.notice = { variant: "error", ...notice };
		this.show();
	}

	saveDamage() {
		const form = this.form;
		if (!form || this.busy || form.uploading) return;
		const row = this.line(form.instrument);
		const damaged = Math.max(0, parseInt(form.damaged, 10) || 0);
		const replaced = Math.max(0, parseInt(form.replaced, 10) || 0);
		if (damaged > 0 && !form.disposition) {
			return this.blocked({
				title: __("Choose repair or disposal"),
				reason: __("A damaged instrument must go to repair or to disposal."),
				action: __("Tap Repair or Dispose, then save."),
			});
		}
		if (replaced > damaged) {
			return this.blocked({
				title: __("Quantity is not valid"),
				reason: __("The replaced quantity cannot exceed the damaged quantity."),
				action: __("Check the numbers, then save again."),
			});
		}
		const usable = Math.max(0, row.bom_qty - damaged + replaced);
		this.form = null;
		this.request(
			T3_LINE,
			{
				assembly: this.asm.assembly,
				instrument: form.instrument,
				actual_qty: usable,
				damaged_qty: damaged,
				replaced_qty: replaced,
				disposition: damaged ? form.disposition : "",
				replacement_instrument: replaced ? form.replacement || null : null,
				note: form.note || null,
				photo: form.photo || null,
			},
			(res) => this.onLine(res)
		);
	}

	saveBranch() {
		const form = this.form;
		if (!form || this.busy) return;
		if (!form.branch || !form.reason.trim()) {
			return this.blocked({
				title: __("Choose the branch and give the reason"),
				reason: __("Sending a set to repair or disposal needs a branch and a reason."),
				action: __("Tap Repair or Disposal, write the reason, then confirm."),
			});
		}
		this.form = null;
		this.request(
			T3_SUBMIT,
			{
				assembly: this.asm.assembly,
				branch: form.branch,
				branch_reason: form.reason.trim(),
			},
			(res) => this.onSubmitted(res)
		);
	}

	async saveConfirm() {
		const form = this.form;
		if (!form || this.busy) return;
		const pin = (form.pin || "").trim();
		if (!form.reason.trim() || !/^\d{6}$/.test(pin)) {
			return this.blocked({
				title: __("Reason and R02 PIN are required"),
				reason: __(
					"Packing with missing instruments needs a reason and the 6-digit PIN of R02."
				),
				action: __("Write the reason, enter the PIN, then confirm."),
			});
		}
		const version = this.station.sessionVersion;
		let proof = null;
		try {
			const res = await this.station.rpc(T3_VERIFY_PIN, {
				token: this.station.session.token,
				pin,
				client_ts: clientTs(),
			});
			if (version !== this.station.sessionVersion) return;
			if (res && res.ok && res.proof) proof = res.proof;
			else return this.blocked({ ...(res && res.error) });
		} catch (error) {
			if (!error.sessionEnded) this.failure(error);
			return;
		}
		form.pin = "";
		this.form = null;
		this.request(
			T3_CONFIRM,
			{ assembly: this.asm.assembly, reason: form.reason.trim(), reviewer_proof: proof },
			(res) => {
				this.asm = res;
				this.notice = {
					variant: "ok",
					title: __("Shortage confirmed by R02"),
					reason: __("Packing is unlocked once the count is recorded."),
					action: __("Record the count."),
				};
				this.show();
			}
		);
	}

	submit() {
		if (!this.asm || !this.asm.ready_to_submit || this.busy || this.offline) return;
		this.request(T3_SUBMIT, { assembly: this.asm.assembly }, (res) => this.onSubmitted(res));
	}

	onSubmitted(res) {
		this.asm = res;
		this.form = null;
		this.notice = null;
		this.show();
	}

	goNext() {
		const next = this.asm && this.asm.next_station;
		if (next) window.location.assign(`/app/station?station=${encodeURIComponent(next)}`);
	}

	async uploadFile(input) {
		const file = input.files && input.files[0];
		if (!file || !this.form || this.form.kind !== "damage") return;
		const version = this.station.sessionVersion;
		this.form.uploading = true;
		this.show();
		try {
			const body = new FormData();
			body.append("file", file, file.name);
			body.append("is_private", "1");
			body.append("folder", "Home");
			const response = await fetch("/api/method/upload_file", {
				method: "POST",
				headers: { Accept: "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token },
				body,
				credentials: "same-origin",
			});
			const data = await response.json().catch(() => ({}));
			if (version !== this.station.sessionVersion || !this.form) return;
			if (!response.ok || !data.message || !data.message.file_url) throw new Error("upload");
			this.form.photo = data.message.file_url;
			this.notice = { variant: "ok", title: __("Photo attached: {0}", [file.name]) };
		} catch (error) {
			if (version !== this.station.sessionVersion || !this.form) return;
			this.notice = {
				variant: "error",
				title: __("Photo could not be attached"),
				reason: __("The file {0} was not uploaded.", [file.name]),
				action: __("Check the connection and choose the photo again."),
			};
		} finally {
			if (this.form) this.form.uploading = false;
		}
		this.show();
	}

	onChange(event) {
		const target = event.target;
		if (target.id === "tc-t3-file") this.uploadFile(target);
		else if (target.dataset.form && this.form) this.form[target.dataset.form] = target.value;
	}

	onInput(event) {
		const target = event.target;
		if (target.dataset.form && this.form) this.form[target.dataset.form] = target.value;
	}

	// ---- trạng thái mạng ----
	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		if (this.offline && !this.asm) {
			return this.station.setState("offline", this.offlineHtml());
		}
		if (!this.asm && !this.notice && !this.busy) {
			return this.station.setState(
				"empty",
				`<div class="tc-t3"><p class="tc-empty">${esc(
					__("Scan the Set ID to count its instruments against the BOM.")
				)}</p></div>`
			);
		}
		let state = this.notice && this.notice.variant === "error" ? "error" : "result";
		if (this.busy && !this.asm) state = "loading";
		this.station.setState(
			state,
			`<div class="tc-t3">
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.asm ? this.asmHtml() : ""}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
		if (this.form) {
			const field = this.result.querySelector("[data-form]");
			if (field && this.form.focused !== true) {
				this.form.focused = true;
				field.focus();
			}
		}
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		const items = (notice.items || [])
			.map((item) => `<li>${esc(typeof item === "string" ? item : t3ItemText(item))}</li>`)
			.join("");
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(tcErrorTitle(notice))}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${items ? `<ul class="tc-alert-items">${items}</ul>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
			${tcGuideButton(notice)}
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
				reason: __("Counting instruments needs a network connection."),
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
		if (this.offline) html += this.offlineHtml();
		if (this.busy) {
			html += `<p class="tc-loading" role="status" aria-busy="true">${esc(
				__("Loading...")
			)}</p>`;
		}
		if (this.notice) {
			const standalone = !this.asm && this.notice.variant === "error";
			html += this.alertHtml(
				this.notice,
				this.notice.technical || standalone ? this.standardButtons() : ""
			);
		}
		return html;
	}

	gateHtml(gate) {
		let cls = "";
		let mark = "&#9675; ";
		let text = __("Pending", null, "Step Gate Result");
		if (gate.result === "Pass") {
			[cls, mark, text] = ["ok", "&#10003; ", __("Pass", null, "Step Gate Result")];
		} else if (gate.result === "Fail") {
			[cls, mark, text] = ["bad", "&#10005; ", __("Fail", null, "Step Gate Result")];
		}
		return `<div class="tc-gate${cls ? " tc-gate-" + cls : ""}">
			<small>${esc(t3GateLabel(gate.step))}</small>
			<b><span aria-hidden="true">${mark}</span>${esc(text)}</b>
		</div>`;
	}

	asmHtml() {
		return `${this.headHtml()}
			${this.parHtml()}
			${this.receiptHtml()}
			${this.linesHtml()}
			${this.formHtml()}
			${this.shortageHtml()}
			${this.lockHtml()}
			${this.barHtml()}`;
	}

	headHtml() {
		const asm = this.asm;
		const set = asm.set;
		return `<section class="tc-t4-block" aria-label="${esc(__("Set"))}">
			<div class="tc-res-head">
				<b class="tc-code">${esc(set.set_id)}</b>
				<span class="tc-badge">${esc(__(set.status, null, "Set Unit"))}</span>
				<span class="tc-tag">${esc(__("BOM v{0}", [asm.bom_version]))}</span>
				<span class="tc-tag">${esc(__("Cycle {0}", [asm.cycle_no]))}</span>
				${
					asm.docstatus === 1
						? `<span class="tc-badge ${
								asm.result === "Pass" ? "tc-badge-g" : "tc-badge-r"
						  }">${esc(
								asm.result === "Pass"
									? __("Assembly recorded")
									: __("Assembly failed")
						  )}</span>`
						: `<span class="tc-badge tc-badge-o">${esc(__("Draft count"))}</span>`
				}
			</div>
			<p class="tc-t4-setname">${esc(set.set_name)} · ${esc(
			__(set.method, null, "Instrument Set Type")
		)}</p>
			<div class="tc-gates" aria-label="${esc(__("Step gates"))}">${(asm.gates || [])
			.map((gate) => this.gateHtml(gate))
			.join("")}</div>
		</section>`;
	}

	parHtml() {
		const par = this.asm.par;
		if (!par || !["warn", "blocked", "override"].includes(par.state)) return "";
		const items = (par.instruments || []).map(
			(row) =>
				`${row.instrument_name} (${row.instrument}): ${__("{0} cycles left", [
					row.remaining,
				])}`
		);
		const left = par.remaining == null ? "" : __("{0} cycles left", [par.remaining]);
		return this.alertHtml({
			variant: "warn",
			title: __("Cycle limit is near"),
			reason: __("Set {0}: {1} of {2} cycles used. {3}", [
				this.asm.set.set_id,
				par.cycles_used,
				par.max_cycles,
				left,
			]),
			items,
			action: __(
				"Tell R02 so a replacement can be prepared; packing (T4) still checks the limit."
			),
		});
	}

	receiptHtml() {
		const notes = this.asm.receipt_notes || [];
		if (!notes.length) return "";
		return this.alertHtml({
			variant: "warn",
			title: __("Notes from reception"),
			items: notes.map((note) => (typeof note === "string" ? note : note.text || "")),
		});
	}

	photoHtml(url, alt) {
		return url
			? `<img class="tc-photo" src="${esc(url)}" alt="${esc(alt)}">`
			: `<span class="tc-photo tc-photo-empty">${esc(__("No photo"))}</span>`;
	}

	lineHtml(row) {
		const open = this.asm.docstatus === 0;
		const off = !open || this.busy || this.offline;
		const status = row.counted ? row.line_status : "";
		const cls = { Enough: " is-done", Short: " is-short", Over: " is-over" }[status] || "";
		let state = t3LineLabel(status);
		if (status === "Short") state += ` (-${row.missing_qty})`;
		if (status === "Over") state += ` (+${row.actual_qty - row.bom_qty})`;
		const marks =
			{ Enough: "&#10003; ", Short: "&#10005; ", Over: "! " }[status] || "&#9675; ";
		const damaged = row.damaged_qty
			? `<span class="tc-ins-state">${esc(
					__("Damaged {0} · replaced {1} · {2}", [
						row.damaged_qty,
						row.replaced_qty,
						__(row.disposition || "Repair", null, "Assembly Line"),
					])
			  )}</span>`
			: "";
		const par =
			row.par_state && row.par_state !== "ok"
				? `<span class="tc-ins-state tc-warn-text">${esc(
						__("Cycle limit is near")
				  )}</span>`
				: "";
		const code = esc(row.instrument);
		return `<div class="tc-ins${cls}" data-instrument="${code}">
			${this.photoHtml(row.thumbnail || row.image, row.instrument_name)}
			<span class="tc-ins-text">
				<span class="tc-ins-name">${esc(row.instrument_name)}</span>
				<span class="tc-ins-pos">${esc(
					__("Position {0} · BOM × {1} · {2}", [
						row.position,
						row.bom_qty,
						row.instrument,
					])
				)}</span>
				<span class="tc-ins-state"><span aria-hidden="true">${marks}</span>${esc(state)}</span>
				${damaged}${par}
				<span class="tc-t3-qty">
					<button type="button" class="tc-btn tc-btn-secondary" data-action="t3-dec"
						data-instrument="${code}" aria-label="${esc(__("Decrease"))}"${t3Disabled(off)}>&minus;</button>
					<b class="tc-t3-count" data-qty="${code}">${row.counted ? row.actual_qty : "-"}</b>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="t3-inc"
						data-instrument="${code}" aria-label="${esc(__("Increase"))}"${t3Disabled(off)}>+</button>
					<button type="button" class="tc-btn tc-btn-ok" data-action="t3-full"
						data-instrument="${code}"${t3Disabled(off)}>${esc(__("All present"))}</button>
					<button type="button" class="tc-btn tc-btn-warn" data-action="t3-damage"
						data-instrument="${code}"${t3Disabled(off)}>${esc(__("Damaged / replace"))}</button>
				</span>
			</span>
		</div>`;
	}

	linesHtml() {
		const asm = this.asm;
		const trays = (asm.tray_images || [])
			.map(
				(image) => `<figure class="tc-tray">
				<img src="${esc(image.image_url || image)}" alt="${esc(__("Arranged set photo"))}">
				<figcaption>${esc(__("Arranged set photo"))}</figcaption>
			</figure>`
			)
			.join("");
		const counted = asm.lines.filter((row) => row.counted).length;
		const open = asm.docstatus === 0 && !this.busy && !this.offline;
		return `<section class="tc-t4-block" aria-label="${esc(__("BOM Count"))}">
			<h3>${esc(__("Set components (BOM v{0})", [asm.bom_version]))}</h3>
			<div class="tc-bom${trays ? " has-tray" : ""}">
				${trays ? `<div>${trays}</div>` : ""}
				<div class="tc-inst">${asm.lines.map((row) => this.lineHtml(row)).join("")}</div>
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-ok" data-action="t3-all"${t3Disabled(!open)}>${esc(
			__("Confirm all components")
		)}</button>
				<span class="tc-hint">${esc(__("Counted {0}/{1} lines", [counted, asm.lines.length]))}</span>
			</div>
		</section>`;
	}

	formHtml() {
		const form = this.form;
		if (!form) return "";
		if (form.kind === "damage") return this.damageFormHtml(form);
		if (form.kind === "branch") return this.branchFormHtml(form);
		return this.confirmFormHtml(form);
	}

	chips(action, current, options) {
		return `<div class="tc-chips">${options
			.map(
				([value, label]) => `<button type="button" class="tc-chip" data-action="${action}"
					data-value="${value}" aria-pressed="${current === value ? "true" : "false"}">${esc(
					label
				)}</button>`
			)
			.join("")}</div>`;
	}

	damageFormHtml(form) {
		const row = this.line(form.instrument);
		return `<section class="tc-t4-block tc-t3-form" aria-label="${esc(
			__("Damaged / replace")
		)}">
			<h3>${esc(__("Damaged / replace"))}: ${esc(row.instrument_name)} (${esc(row.instrument)})</h3>
			<div class="tc-t4-row">
				<div class="tc-field">
					<label for="tc-t3-damaged">${esc(__("Damaged Quantity"))}</label>
					<input id="tc-t3-damaged" type="number" min="0" inputmode="numeric" data-form="damaged"
						value="${esc(form.damaged)}">
				</div>
				<div class="tc-field">
					<label for="tc-t3-replaced">${esc(__("Replaced from spare stock"))}</label>
					<input id="tc-t3-replaced" type="number" min="0" inputmode="numeric" data-form="replaced"
						value="${esc(form.replaced)}">
				</div>
			</div>
			<div class="tc-field">
				<label>${esc(__("Disposition"))}</label>
				${this.chips("t3-disposition", form.disposition, [
					["Repair", __("Repair", null, "Assembly Line")],
					["Dispose", __("Dispose", null, "Assembly Line")],
				])}
			</div>
			<div class="tc-field">
				<label for="tc-t3-note">${esc(__("Note"))}</label>
				<textarea id="tc-t3-note" rows="2" data-form="note">${esc(form.note)}</textarea>
			</div>
			<div class="tc-field">
				<label for="tc-t3-file">${esc(__("Photo of the damage"))}</label>
				<input id="tc-t3-file" type="file" accept="image/*" capture="environment"${t3Disabled(
					form.uploading
				)}>
				${form.photo ? `<p class="tc-t4-ok">&#10003; ${esc(__("Photo attached"))}</p>` : ""}
			</div>
			<p class="tc-hint">${esc(__("Usable instruments = BOM quantity − damaged + replaced."))}</p>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="t3-save-damage"${t3Disabled(
					this.busy || form.uploading
				)}>${esc(__("Save"))}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="t3-form-cancel">${esc(
					__("Cancel")
				)}</button>
			</div>
		</section>`;
	}

	branchFormHtml(form) {
		return `<section class="tc-t4-block tc-t3-form" aria-label="${esc(__("Damage Branch"))}">
			<h3>${esc(__("Set is damaged: send to repair or disposal"))}</h3>
			<p>${esc(
				__(
					"The set stops here and does not go to packing. The assembly is recorded as failed."
				)
			)}</p>
			${this.chips("t3-branch-pick", form.branch, [
				["Repair", __("Repair", null, "Assembly Record")],
				["Disposal", __("Disposal", null, "Assembly Record")],
			])}
			<div class="tc-field">
				<label for="tc-t3-branch-reason">${esc(__("Reason"))} *</label>
				<textarea id="tc-t3-branch-reason" rows="3" data-form="reason">${esc(form.reason)}</textarea>
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-danger" data-action="t3-branch-save"${t3Disabled(
					this.busy
				)}>${esc(__("Confirm: send the set away"))}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="t3-form-cancel">${esc(
					__("Cancel")
				)}</button>
			</div>
		</section>`;
	}

	confirmFormHtml(form) {
		return `<section class="tc-t4-block tc-t3-form" aria-label="${esc(
			__("R02 confirmation")
		)}">
			<h3>${esc(__("R02 confirms packing with missing instruments"))}</h3>
			<div class="tc-field">
				<label for="tc-t3-confirm-reason">${esc(__("Reason"))} *</label>
				<textarea id="tc-t3-confirm-reason" rows="3" data-form="reason">${esc(form.reason)}</textarea>
			</div>
			<div class="tc-field">
				<label for="tc-t3-pin">${esc(__("R02 PIN"))} *</label>
				<input id="tc-t3-pin" type="password" inputmode="numeric" maxlength="6" autocomplete="off"
					data-form="pin" value="${esc(form.pin)}">
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-danger" data-action="t3-confirm-save"${t3Disabled(
					this.busy
				)}>${esc(__("Confirm: pack with missing instruments"))}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="t3-form-cancel">${esc(
					__("Cancel")
				)}</button>
			</div>
		</section>`;
	}

	canConfirm() {
		const roles = (this.station.session && this.station.session.roles) || [];
		return roles.includes("TC R02");
	}

	shortageHtml() {
		const asm = this.asm;
		if (!asm.has_shortage || asm.docstatus === 1) return "";
		if (asm.shortage_confirmed) {
			return this.alertHtml({
				variant: "ok",
				title: __("Shortage confirmed by R02"),
				reason: __("Confirmed by {0}: {1}", [
					asm.shortage_confirmed_by,
					asm.shortage_reason,
				]),
				items: asm.shortage_items.map(t3ItemText),
			});
		}
		const button = this.canConfirm()
			? `<div class="tc-actions"><button type="button" class="tc-btn tc-btn-danger" data-action="t3-confirm"${t3Disabled(
					this.busy || this.offline
			  )}>${esc(__("R02 confirms: pack with missing instruments"))}</button></div>`
			: `<p class="tc-hint">${esc(
					__(
						"R02 signs in with the card at this station, scans the Set ID again and enters the PIN."
					)
			  )}</p>`;
		return this.alertHtml(
			{
				variant: "error",
				title: __("Missing instruments"),
				reason: __(
					"Packing is locked until the missing instruments are added or R02 confirms."
				),
				items: asm.shortage_items.map(t3ItemText),
				action: __(
					"Add the instruments from the spare stock, or ask R02 to confirm with the PIN."
				),
			},
			button
		);
	}

	lockHtml() {
		const asm = this.asm;
		if (!asm.pack_locked) {
			return this.alertHtml({
				variant: "ok",
				title: __("Packing: ready"),
				reason: __("Assembly is recorded. The set can go to packing."),
			});
		}
		const reasons = {
			LINES_NOT_COUNTED: __("Count every line first."),
			SHORTAGE_UNCONFIRMED: __("Missing instruments are not confirmed."),
			NOT_RECORDED: __("Record the count to unlock packing."),
			BRANCH: __("The set was sent to repair or disposal."),
			ASSEMBLY_FAILED: __("Assembly failed; the set must be assembled again."),
		};
		return `<div class="tc-t3-lock"><p><b><span aria-hidden="true">&#128274;</span> ${esc(
			__("Packing: locked")
		)}</b> · ${esc(reasons[asm.pack_lock_reason] || "")}</p></div>`;
	}

	barHtml() {
		const asm = this.asm;
		const missing = [];
		if (asm.docstatus === 0) {
			if (asm.uncounted.length)
				missing.push(__("{0} line(s) not counted", [asm.uncounted.length]));
			if (asm.has_shortage && !asm.shortage_confirmed) missing.push(__("R02 confirmation"));
		}
		const done = asm.docstatus === 1;
		const next = done && asm.next_station;
		return `<div class="tc-actionsbar">
			<p class="tc-missing">${esc(
				done
					? asm.result === "Pass"
						? __("Assembly recorded. Scan the next set.")
						: __("Assembly recorded as failed. Scan the next set.")
					: missing.length
					? __("Still needed: {0}", [missing.join(", ")])
					: __("Ready to record")
			)}</p>
			${
				done
					? next
						? `<button type="button" class="tc-btn tc-btn-primary" data-action="t3-next">${esc(
								__("Go to packing station {0}", [next])
						  )}</button>`
						: ""
					: `<button type="button" class="tc-btn tc-btn-primary" data-action="t3-submit"${t3Disabled(
							!asm.ready_to_submit || this.busy || this.offline
					  )}>${esc(__("Record the count"))}</button>
					<button type="button" class="tc-btn tc-btn-danger" data-action="t3-branch"${t3Disabled(
						this.busy || this.offline
					)}>${esc(__("Set is damaged: repair / disposal"))}</button>`
			}
		</div>`;
	}
}

function t3ItemText(item) {
	return `${item.instrument_name || item.instrument} (${item.instrument}) × ${item.missing_qty}`;
}
