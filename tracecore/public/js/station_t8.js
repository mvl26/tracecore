/* global uuid4, clientTs, esc */
// Màn T8 quét sử dụng (SCR-37, FEAT-027, UC-13) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// TraceCoreStation giao cho T8Usage khi trạm là bước T8: ô quét luôn trên cùng; quét Cycle ID mở thẻ gói kèm form (mã bệnh
// nhân, mã ca mổ, phẫu thuật viên, phòng), xác nhận một chạm. Lỗi chặn (Đã dùng, Thu hồi, Quá hạn...) là alert-error
// inline (kết quả → lý do → hành động). Ca cấp cứu lưu không mã bệnh nhân và nhập bổ sung trong 24 giờ.

const T8_SCAN = "tracecore.v1.usage.scan";
const T8_CONFIRM = "tracecore.v1.usage.confirm";
const T8_PATIENT_CODE = "tracecore.v1.usage.set_patient_code";
const T8_FIELDS = ["patient_code", "surgery_code", "surgeon", "room", "department_reason"];
// giữ ca mổ và phòng cho gói kế tiếp của cùng ca (FR-M2-17.3); mã bệnh nhân không giữ lại
const T8_KEEP = ["surgery_code", "surgeon", "room"];

function t8Date(value) {
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
	return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

class T8Usage {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.offline = false;
		this.busy = null;
		this.card = null; // thẻ gói đang mở (usage.scan)
		this.notice = null;
		this.draft = {};
		this.emergency = false;
		this.waiting = []; // ca cấp cứu của phiên này còn chờ mã bệnh nhân: {usage, cycle_id}
		this.codeFor = null; // usage đang nhập mã bổ sung
		this.fieldError = null;
	}

	get dialogOpen() {
		return Boolean(this.card || this.codeFor); // form đang nhập giữ focus, ô quét không giành lại
	}

	// Hết phiên trạm (rút thẻ, idle 10 phút, đổi người): xóa gói đang mở, mã đã nhập và yêu cầu dở của người trước
	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.card = null;
		this.notice = null;
		this.draft = {};
		this.emergency = false;
		this.waiting = [];
		this.codeFor = null;
		this.fieldError = null;
		this.input.placeholder = __("Scan the Cycle ID of the pack to use...");
		this.input.setAttribute("aria-label", __("Scan the Cycle ID of the pack to use..."));
	}

	// ---- quét và gọi RPC ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline()) return this.station.setOffline(true);
		this.captureDraft();
		this.codeFor = null;
		await this.request(T8_SCAN, { raw, station: this.station.station }, (res) =>
			this.onScan(res)
		);
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
		if (!failure) this.markOnline();
		if (failure) this.failure(failure);
		else if (response && response.ok === false) this.reject(response.error);
		else onOk(response);
		this.station.focus();
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
				reason: __("This account cannot record the use of packs at this station."),
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
		// mã bị chặn do dữ liệu nhập (thiếu mã bệnh nhân, thiếu lý do khoa khác) giữ nguyên form để sửa
		const keep = ["PATIENT_CODE_REQUIRED", "DEPARTMENT_REASON_REQUIRED", "DATA_INCOMPLETE"];
		if (!keep.includes(error.code)) {
			this.card = null;
			this.codeFor = null;
		}
		this.fieldError = keep.includes(error.code) ? error.code : null;
		this.notice = { variant: "error", ...error };
		this.show();
	}

	onScan(res) {
		this.notice = null;
		this.fieldError = null;
		this.card = res.card;
		this.show();
		this.focusField(
			this.card.department_mismatch && !this.draft.department_reason
				? "department_reason"
				: "patient_code"
		);
	}

	confirm() {
		if (!this.card) return;
		this.captureDraft();
		const args = {
			cycle_id: this.card.cycle_id,
			station: this.station.station,
			patient_code: this.emergency ? "" : this.draft.patient_code || "",
			surgery_code: this.draft.surgery_code || "",
			surgeon: this.draft.surgeon || "",
			room: this.draft.room || "",
			emergency: this.emergency ? 1 : 0,
			department_reason: this.card.department_mismatch
				? this.draft.department_reason || ""
				: "",
		};
		const cycleId = this.card.cycle_id;
		const emergency = this.emergency;
		this.request(T8_CONFIRM, args, (res) => {
			T8_KEEP.forEach((name) => {
				this.draft[name] = this.draft[name] || "";
			});
			this.draft = Object.fromEntries(T8_KEEP.map((name) => [name, this.draft[name]]));
			this.card = null;
			this.emergency = false;
			if (emergency) this.waiting.push({ usage: res.usage, cycle_id: cycleId });
			this.notice = {
				variant: "ok",
				title: __("Pack {0} recorded as used", [cycleId]),
				reason: emergency
					? __("Enter the patient code within 24 hours.")
					: __("{0} pack(s) are linked to surgery {1}.", [
							(res.surgery_packs || []).length,
							this.draft.surgery_code,
					  ]),
				action: __("Scan the next pack of this surgery, or finish."),
			};
			this.show();
		});
	}

	submitPatientCode() {
		const box = this.result.querySelector("#tc-t8-late-code");
		const code = box ? box.value.trim() : "";
		if (!code) {
			this.fieldError = "PATIENT_CODE_REQUIRED";
			this.show();
			return this.focusField("late-code");
		}
		const usage = this.codeFor;
		this.request(
			T8_PATIENT_CODE,
			{ usage, patient_code: code, station: this.station.station },
			() => {
				this.waiting = this.waiting.filter((row) => row.usage !== usage);
				this.codeFor = null;
				this.fieldError = null;
				this.notice = {
					variant: "ok",
					title: __("Patient code saved"),
					reason: __(
						"The patient code is stored encrypted and shown with hidden characters."
					),
					action: __("Scan the next pack."),
				};
				this.show();
			}
		);
	}

	// ---- thao tác trên màn ----
	onAction(action, target) {
		const handlers = {
			retry: () => this.retry(),
			confirm: () => this.confirm(),
			cancel: () => {
				this.captureDraft();
				this.card = null;
				this.notice = null;
				this.fieldError = null;
				this.show();
			},
			"late-code": () => {
				this.codeFor = target && target.dataset ? target.dataset.usage : null;
				this.fieldError = null;
				this.show();
				this.focusField("late-code");
			},
			"late-submit": () => this.submitPatientCode(),
			"late-cancel": () => {
				this.codeFor = null;
				this.show();
				this.station.focus();
			},
			emergency: () => {
				this.captureDraft();
				this.emergency = !this.emergency;
				this.show();
			},
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	captureDraft() {
		T8_FIELDS.forEach((name) => {
			const box = this.result.querySelector(`#tc-t8-${name}`);
			if (box) this.draft[name] = box.value;
		});
	}

	focusField(name) {
		const box = this.result.querySelector(`#tc-t8-${name}`);
		if (box) box.focus();
	}

	// ---- trạng thái mạng ----
	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		if (this.offline && !this.card)
			return this.station.setState("offline", this.offlineHtml());
		const state = this.notice && this.notice.variant === "error" ? "error" : "result";
		this.station.setState(
			state,
			`<div class="tc-t8">
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.card ? this.cardHtml() : this.idleHtml()}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
	}

	updatePlaceholder() {
		const text = __("Scan the Cycle ID of the pack to use...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
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
				reason: __("Recording the use of packs needs a network connection."),
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
			const standalone = !this.card && this.notice.variant === "error";
			html += this.alertHtml(
				this.notice,
				this.notice.technical || standalone ? this.standardButtons() : ""
			);
		}
		return html;
	}

	fieldHtml(name, label, { required = false, error = false, type = "text", attrs = "" } = {}) {
		const value = esc(this.draft[name] || "");
		return `<div class="tc-field">
			<label for="tc-t8-${name}">${esc(label)}${required ? " *" : ""}</label>
			<input id="tc-t8-${name}" type="${type}" value="${value}" autocomplete="off" ${attrs}${
			error ? ' class="is-error" aria-invalid="true"' : ""
		}>
		</div>`;
	}

	cardHtml() {
		const card = this.card;
		const missing = (code) => this.fieldError === code;
		return `<section class="tc-t6-block" aria-label="${esc(__("Pack"))}">
			<div class="tc-res-head">
				<b class="tc-code">${esc(card.cycle_id)}</b>
				<span class="tc-badge tc-badge-g">${esc(__("Issued", null, "Pack"))}</span>
			</div>
			<dl class="tc-res-grid">
				<dt>${esc(__("Set ID"))}</dt><dd class="tc-mono">${esc(card.set_id)}</dd>
				<dt>${esc(__("Set Name"))}</dt><dd>${esc(card.set_name)}</dd>
				<dt>${esc(__("Use-by date"))}</dt><dd><b>${esc(t8Date(card.expiry))}</b></dd>
			</dl>
			${
				card.department_mismatch
					? this.alertHtml({
							variant: "warn",
							title: __("Pack belongs to another department"),
							reason: __("Pack {0} was issued to {1}, not to {2}.", [
								card.cycle_id,
								card.pack_department,
								card.scanner_department,
							]),
							action: __("Enter why this department uses the pack, then confirm."),
					  })
					: ""
			}
			${
				card.department_mismatch
					? this.fieldHtml(
							"department_reason",
							__("Why is this department using the pack?"),
							{
								required: true,
								error: missing("DEPARTMENT_REASON_REQUIRED"),
							}
					  )
					: ""
			}
			<div class="tc-field">
				<label><input type="checkbox" data-action="emergency"${this.emergency ? " checked" : ""}> ${esc(
			__("Emergency: enter the patient code within 24 hours")
		)}</label>
			</div>
			${
				this.emergency
					? ""
					: this.fieldHtml("patient_code", __("Patient code"), {
							required: true,
							error: missing("PATIENT_CODE_REQUIRED"),
							type: "password",
					  })
			}
			${this.fieldHtml("surgery_code", __("Surgery code"), {
				required: true,
				error: missing("DATA_INCOMPLETE"),
			})}
			${this.fieldHtml("surgeon", __("Surgeon"))}
			${this.fieldHtml("room", __("Room"))}
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="confirm">${esc(
					__("Confirm: record use of this pack")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="cancel">${esc(
					__("Cancel")
				)}</button>
			</div>
		</section>`;
	}

	idleHtml() {
		let html = `<p class="tc-empty">${esc(__("Scan the Cycle ID of the pack to use."))}</p>`;
		if (this.waiting.length) {
			html += `<section class="tc-t6-block">
				<h3>${esc(__("Emergency cases waiting for the patient code"))}</h3>
				${this.waiting.map((row) => this.waitingHtml(row)).join("")}
			</section>`;
		}
		return html;
	}

	waitingHtml(row) {
		if (this.codeFor === row.usage) {
			const error = this.fieldError === "PATIENT_CODE_REQUIRED";
			return `<div class="tc-field">
				<label for="tc-t8-late-code">${esc(__("Patient code"))} * <span class="tc-mono">${esc(
				row.cycle_id
			)}</span></label>
				<input id="tc-t8-late-code" type="password" autocomplete="off"${
					error ? ' class="is-error" aria-invalid="true"' : ""
				}>
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="late-submit">${esc(
					__("Save patient code")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="late-cancel">${esc(
					__("Cancel")
				)}</button>
			</div>`;
		}
		return `<div class="tc-actions">
			<span class="tc-mono">${esc(row.cycle_id)}</span>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="late-code" data-usage="${esc(
				row.usage
			)}">${esc(__("Enter patient code"))}</button>
		</div>`;
	}
}
