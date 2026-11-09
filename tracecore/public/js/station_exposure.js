/* global tcErrorTitle, tcGuideButton, uuid4, clientTs, esc, t8Encrypt */
// Màn báo phơi nhiễm nghề nghiệp (SCR-63, FEAT-071, UC-55, FR-M16-01, A-137 Q2) trên Page station, trạm chức năng
// EXPOSURE (PDA của khoa). Ba bước cố định: (1) loại + thời điểm, (2) hoạt động / thiết bị / nguồn (mã BN nguồn tùy
// chọn, ô mật khẩu, không hiện lại), (3) xác nhận và gửi. Không có ô kết quả xét nghiệm hay chẩn đoán (FR-M16-06).
// Mất mạng: báo cáo xếp hàng trên máy (IndexedDB) và gửi khi có mạng, cùng X-Idempotency-Key (NFR-AVAIL-05); mã BN
// chỉ vào hàng đợi khi mã hóa được bằng khóa công khai của site, nếu không thì bỏ mã và báo người dùng.
// Lỗi chặn = alert-error inline (kết quả → lý do → hành động).

const EXP_REPORT = "tracecore.v1.exposure.report";
const EXP_TYPES = [
	"Needlestick or Sharps",
	"Mucous Membrane Splash",
	"Non-intact Skin",
	"Respiratory",
	"Other",
];
const EXP_SOURCE = ["Yes", "No", "Unknown"];
const EXP_CONTEXT = "Occupational Exposure";

function expLocalInput(date = new Date()) {
	const pad = (n) => String(n).padStart(2, "0");
	return (
		`${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
		`T${pad(date.getHours())}:${pad(date.getMinutes())}`
	);
}

// giá trị ô datetime-local (giờ máy) → ISO 8601 có offset (client_ts của ADR-003)
function expIso(value) {
	const date = value ? new Date(value) : new Date();
	return clientTs(Number.isNaN(date.getTime()) ? new Date() : date);
}

class ExposureReport {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.offline = false;
		this.busy = false;
		this.pending = null;
		this.notice = null;
		this.done = null;
		this.form = this.blankForm();
		this.updatePlaceholder();
		station.listen(this.result, "input", (event) => this.onInput(event));
		station.listen(this.result, "change", (event) => this.onInput(event));
	}

	blankForm() {
		return {
			step: 1,
			exposure_type: "",
			occurred_at: expLocalInput(),
			activity: "",
			device: "",
			source_known: "Unknown",
			source_patient_code: "",
		};
	}

	get dialogOpen() {
		return false;
	}

	clearSession() {
		this.pending = null;
		this.busy = false;
		this.notice = null;
		this.done = null;
		this.form = this.blankForm();
		this.updatePlaceholder();
	}

	updatePlaceholder() {
		const text = __("Report an exposure: choose the type below");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	// màn này không cần quét; mã quét nhầm thì bỏ qua, giữ ô quét có focus
	scan() {
		this.input.value = "";
		this.station.focus();
	}

	onInput(event) {
		const target = event.target;
		const field = target && target.dataset && target.dataset.field;
		if (!field || !this.station.session) return;
		this.form[field] = target.value;
	}

	onAction(action, button) {
		const handlers = {
			"exp-type": () => this.chooseType(button.dataset.value),
			"exp-source": () => this.chooseSource(button.dataset.value),
			"exp-next": () => this.next(),
			"exp-back": () => this.back(),
			"exp-send": () => this.send(),
			"exp-new": () => this.restart(),
			retry: () => this.retry(),
		};
		if (!handlers[action]) return false;
		handlers[action]();
		return true;
	}

	chooseType(value) {
		if (!EXP_TYPES.includes(value)) return;
		this.form.exposure_type = value;
		this.notice = null;
		this.show();
	}

	chooseSource(value) {
		if (!EXP_SOURCE.includes(value)) return;
		this.form.source_known = value;
		if (value !== "Yes") this.form.source_patient_code = "";
		this.show();
	}

	stepError() {
		if (this.form.step === 1 && !this.form.exposure_type)
			return {
				title: __("Exposure type is required"),
				reason: __("The report needs the type of exposure."),
				action: __("Choose one of the types, then continue."),
			};
		if (
			this.form.step === 1 &&
			new Date(this.form.occurred_at) > new Date(Date.now() + 5 * 60000)
		)
			return {
				title: __("Exposure time is in the future"),
				reason: __("The exposure time is later than now."),
				action: __("Check the date and time of the exposure, then continue."),
			};
		return null;
	}

	next() {
		const error = this.stepError();
		if (error) {
			this.notice = { variant: "error", ...error };
			return this.show();
		}
		this.notice = null;
		this.form.step = Math.min(3, this.form.step + 1);
		this.show();
	}

	back() {
		this.notice = null;
		this.form.step = Math.max(1, this.form.step - 1);
		this.show();
	}

	restart() {
		this.done = null;
		this.notice = null;
		this.pending = null;
		this.form = this.blankForm();
		this.show();
	}

	args() {
		const form = this.form;
		return {
			station: this.station.station,
			exposure_type: form.exposure_type,
			occurred_at: expIso(form.occurred_at),
			activity: form.activity.trim(),
			device: form.device.trim(),
			source_known: form.source_known,
			source_patient_code:
				form.source_known === "Yes" ? form.source_patient_code.trim() : "",
		};
	}

	// ---- gửi: trực tuyến qua station.rpc; mất mạng → hàng đợi trên máy ----
	async send() {
		if (this.busy || !this.station.session) return;
		const args = this.args();
		const sig = JSON.stringify(args);
		if (!this.pending || this.pending.sig !== sig)
			this.pending = { sig, args, key: uuid4(), ts: clientTs() };
		const pending = this.pending;
		if (this.offline) return this.queue(pending);
		const version = this.station.sessionVersion;
		this.busy = true;
		this.show();
		let response = null;
		let failure = null;
		try {
			response = await this.station.rpc(
				EXP_REPORT,
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
		if (response && response.ok === false) {
			this.notice = { variant: "error", ...response.error };
			return this.show();
		}
		this.done = { ...(response.exposure || {}), queued: false };
		this.notice = null;
		this.show();
	}

	async queue(pending) {
		const { source_patient_code: code, ...rest } = pending.args; // mã rõ không bao giờ vào IndexedDB
		const queued = { ...rest };
		let dropped = false;
		const key = this.station.offlineData && this.station.offlineData.patient_key;
		if (code) {
			if (key && window.crypto && crypto.subtle && typeof t8Encrypt === "function")
				queued.source_patient_code_enc = await t8Encrypt(key, code);
			else dropped = true;
		}
		try {
			await this.station.queueCall(EXP_REPORT, queued, pending.key, pending.ts);
		} catch (error) {
			if (error.sessionEnded) return;
			this.notice = {
				variant: "error",
				title: __("Could not keep the report on this device"),
				reason: __("The station storage is not available."),
				action: __("Report the exposure to the infection control team by phone now."),
			};
			return this.show();
		}
		this.pending = null;
		this.done = { queued: true, dropped, exposure_type: pending.args.exposure_type };
		this.notice = null;
		this.show();
	}

	retry() {
		this.station.manualOffline = false;
		if (!navigator.onLine) return this.station.setOffline(true);
		this.station.setOffline(false);
		this.notice = null;
		if (this.pending) return this.send();
		this.show();
	}

	failure(error) {
		if (error.status >= 400 && error.status < 500) this.pending = null;
		this.notice = {
			variant: "error",
			technical: true,
			title: error.status === 403 ? __("Not permitted") : __("Server error"),
			reason:
				error.status === 403
					? __("This account cannot report an exposure at this station.")
					: __("The server could not process the request ({0}).", [error.status || "?"]),
			action: __("Retry, or report the exposure to the infection control team by phone."),
		};
		this.show();
	}

	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		if (this.busy) return this.station.renderLoading();
		if (this.done) return this.station.setState("result", this.doneHtml());
		const failed = this.notice && this.notice.variant === "error";
		const blank = this.form.step === 1 && !this.form.exposure_type;
		// mất mạng vẫn điền và gửi được (xếp hàng trên máy), nên trạng thái offline vẫn hiện biểu mẫu
		const state = this.offline ? "offline" : failed ? "error" : blank ? "empty" : "result";
		this.station.setState(
			state,
			`<div class="tc-linen tc-exposure">
				${this.offline ? this.offlineHtml() : ""}
				<div data-region="notice">${this.notice ? this.alertHtml(this.notice) : ""}</div>
				${this.stepsHtml()}
				${this.stepHtml()}
			</div>`
		);
	}

	offlineHtml() {
		return `<div class="tc-alert tc-alert-info" role="status">
			<p class="tc-alert-title">${esc(__("Station offline"))}</p>
			<p class="tc-alert-reason">${esc(
				__("The report is kept on this device and sent when the connection returns.")
			)}</p>
		</div>`;
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(tcErrorTitle(notice))}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
			${tcGuideButton(notice)}
			${
				notice.technical
					? `<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
							__("Retry")
					  )}</button></div>`
					: buttons
			}
		</div>`;
	}

	stepsHtml() {
		const labels = [__("Type and time"), __("Circumstances"), __("Confirm")];
		const chips = labels
			.map((label, index) => {
				const number = index + 1;
				const current = number === this.form.step;
				return `<li class="tc-exp-chip${current ? " is-current" : ""}"${
					current ? ' aria-current="step"' : ""
				}>${number} ${esc(label)}</li>`;
			})
			.join("");
		return `<ol class="tc-exp-steps" aria-label="${esc(__("Report steps"))}">${chips}</ol>`;
	}

	stepHtml() {
		if (this.form.step === 1) return this.typeHtml();
		if (this.form.step === 2) return this.circumstanceHtml();
		return this.confirmHtml();
	}

	optionHtml(action, value, label, chosen) {
		return `<button type="button" class="tc-btn tc-btn-secondary tc-exp-option${
			chosen ? " is-chosen" : ""
		}" data-action="${action}" data-value="${esc(value)}" aria-pressed="${chosen}">${
			chosen ? '<span aria-hidden="true">&#10003; </span>' : ""
		}${esc(label)}</button>`;
	}

	typeHtml() {
		const options = EXP_TYPES.map((type) =>
			this.optionHtml(
				"exp-type",
				type,
				__(type, null, EXP_CONTEXT),
				this.form.exposure_type === type
			)
		).join("");
		return `<section class="tc-t6-block" aria-label="${esc(__("Exposure type"))}">
			<h2 class="tc-exp-title">${esc(__("Step 1: type of exposure"))}</h2>
			<div class="tc-exp-options">${options}</div>
			<div class="tc-field">
				<label for="tc-exp-time">${esc(__("When did it happen?"))}</label>
				<input id="tc-exp-time" type="datetime-local" data-field="occurred_at" max="${esc(
					expLocalInput()
				)}" value="${esc(this.form.occurred_at)}">
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="exp-next"${
					this.form.exposure_type ? "" : " disabled"
				}>${esc(__("Continue"))}</button>
			</div>
		</section>`;
	}

	circumstanceHtml() {
		const sources = EXP_SOURCE.map((value) =>
			this.optionHtml(
				"exp-source",
				value,
				__(value, null, EXP_CONTEXT),
				this.form.source_known === value
			)
		).join("");
		return `<section class="tc-t6-block" aria-label="${esc(__("Circumstances"))}">
			<h2 class="tc-exp-title">${esc(__("Step 2: what happened"))}</h2>
			<div class="tc-field">
				<label for="tc-exp-activity">${esc(__("What were you doing?"))}</label>
				<input id="tc-exp-activity" type="text" autocomplete="off" maxlength="140" data-field="activity" value="${esc(
					this.form.activity
				)}">
			</div>
			<div class="tc-field">
				<label for="tc-exp-device">${esc(__("Device or object"))}</label>
				<input id="tc-exp-device" type="text" autocomplete="off" maxlength="140" data-field="device" value="${esc(
					this.form.device
				)}">
			</div>
			<p class="tc-exp-question">${esc(__("Is the source patient known?"))}</p>
			<div class="tc-exp-options tc-exp-inline">${sources}</div>
			${
				this.form.source_known === "Yes"
					? `<div class="tc-field">
				<label for="tc-exp-code">${esc(__("Source patient code (optional)"))}</label>
				<input id="tc-exp-code" type="password" autocomplete="off" maxlength="64" data-field="source_patient_code" value="${esc(
					this.form.source_patient_code
				)}">
				<p class="tc-t6-hint">${esc(
					__("The code is encrypted and shown masked; do not enter the patient name.")
				)}</p>
			</div>`
					: ""
			}
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-secondary" data-action="exp-back">${esc(
					__("Back")
				)}</button>
				<button type="button" class="tc-btn tc-btn-primary" data-action="exp-next">${esc(
					__("Continue")
				)}</button>
			</div>
		</section>`;
	}

	confirmHtml() {
		const form = this.form;
		const row = (label, value) =>
			`<div class="tc-exp-row"><dt>${esc(label)}</dt><dd>${esc(value || "-")}</dd></div>`;
		return `<section class="tc-t6-block" aria-label="${esc(__("Confirm"))}">
			<h2 class="tc-exp-title">${esc(__("Step 3: check and send"))}</h2>
			<dl class="tc-exp-summary">
				${row(__("Exposure Type"), __(form.exposure_type, null, EXP_CONTEXT))}
				${row(__("Occurred At"), frappe.datetime.str_to_user(form.occurred_at.replace("T", " ")))}
				${row(__("Activity"), form.activity)}
				${row(__("Device"), form.device)}
				${row(
					__("Source Known"),
					__(form.source_known, null, EXP_CONTEXT) +
						(form.source_known === "Yes" && form.source_patient_code
							? " · " + __("patient code entered")
							: "")
				)}
			</dl>
			<p class="tc-t6-hint">${esc(
				__("The head of infection control and the supervisor are notified at once.")
			)}</p>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-secondary" data-action="exp-back">${esc(
					__("Back")
				)}</button>
				<button type="button" class="tc-btn tc-btn-primary tc-exp-send" data-action="exp-send">${esc(
					__("Send report")
				)}</button>
			</div>
		</section>`;
	}

	procedureHtml(procedure) {
		if (!procedure)
			return `<p class="tc-alert-action">${esc(
				__(
					"Follow the first-aid steps of the hospital and call the infection control team now."
				)
			)}</p>`;
		const link = procedure.file
			? ` <a href="${esc(procedure.file)}" target="_blank" rel="noopener">${esc(
					__("Open")
			  )}</a>`
			: "";
		return `<p class="tc-alert-action">${esc(__("First-aid procedure"))}: ${esc(
			procedure.title
		)}${link}</p>`;
	}

	doneHtml() {
		const done = this.done;
		const notice = done.queued
			? {
					variant: "info",
					title: __("Report kept on this device"),
					reason: done.dropped
						? __(
								"It is sent when the connection returns. The patient code was not kept: tell the supervisor."
						  )
						: __("It is sent when the connection returns."),
					action: __("Do first aid now and call the infection control team."),
			  }
			: {
					variant: "ok",
					title: __("Exposure {0} reported", [done.name]),
					reason: __(
						"The head of infection control and the supervisor have been notified."
					),
					action: "",
			  };
		return `<div class="tc-linen tc-exposure">
			${this.alertHtml(notice, done.queued ? "" : this.procedureHtml(done.procedure))}
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="exp-new">${esc(
					__("Report another exposure")
				)}</button>
			</div>
		</div>`;
	}
}
