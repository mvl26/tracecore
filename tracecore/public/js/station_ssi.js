/* global uuid4, clientTs, esc, tcErrorTitle, tcGuideButton */
// SCR-57 (PDA) Theo dõi NKVM sau ra viện (FEAT-064; UC-49 bước 4–5; FR-M13-08, 08.1; BRU-HAI-005; ADR-014; A-147 k).
// Page station, chức năng trạm SSI_FOLLOWUP (R11, R01). Danh sách lần theo dõi đến hạn / quá hạn (mã BN che); chạm một
// dòng → 3 nút kết quả lớn (Âm tính / Nghi ngờ NKVM / Không liên lạc được) + ghi chú → Lưu: ≤ 3 chạm. Chỉ online: dữ
// liệu người bệnh không lưu trên máy; mất mạng → trạng thái offline, không xếp hàng.

const SSI_LIST = "tracecore.v1.hai.ssi_followups";
const SSI_RECORD = "tracecore.v1.hai.ssi_record";
const SSI_CTX = "Surgical Surveillance"; // context dịch giá trị Select
const SSI_RESULTS = [
	["Negative", "Negative"],
	["SSI suspected", "SSI suspected"],
	["Unreachable", "Unreachable"],
];

class SsiFollowupStation {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		station.listen(this.result, "input", (event) => this.onInput(event));
		this.clearSession();
	}

	clearSession() {
		this.context = null;
		this.failed = null;
		this.loading = false;
		this.busy = false;
		this.offline = false;
		this.form = null; // {surveillance, row, result, note}
		this.notice = null;
		this.pending = null;
		this.updatePlaceholder();
	}

	get dialogOpen() {
		return Boolean(this.form);
	}

	updatePlaceholder() {
		const text = __("Choose a follow-up below");
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

	async load() {
		const station = this.station;
		if (this.loading || !station.session || station.isOffline()) return;
		const version = station.sessionVersion;
		this.loading = true;
		this.failed = null;
		this.show();
		try {
			const res = await station.rpcRead(SSI_LIST, {
				station: station.station,
				client_ts: clientTs(),
			});
			if (version !== station.sessionVersion) return;
			if (res && res.ok !== false) this.context = res;
			else this.failed = station.failureCause(null, res);
		} catch (error) {
			if (error.sessionEnded) return;
			this.failed = station.failureCause(error);
		} finally {
			this.loading = false;
		}
		if (version === station.sessionVersion) this.show();
	}

	onInput(event) {
		const target = event.target;
		if (this.form && target && target.dataset && target.dataset.ssi === "note")
			this.form.note = target.value;
	}

	onAction(action, button) {
		const data = (button && button.dataset) || {};
		const handlers = {
			"ssi-open": () => {
				this.form = {
					surveillance: data.surveillance,
					row: data.row,
					result: "",
					note: "",
				};
				this.notice = null;
				this.show();
			},
			"ssi-result": () => {
				if (this.form) this.form.result = data.value;
				this.show();
			},
			"ssi-save": () => this.save(),
			"ssi-cancel": () => {
				this.form = null;
				this.notice = null;
				this.show();
			},
			retry: () => this.retry(),
		};
		if (!handlers[action]) return false;
		handlers[action]();
		return true;
	}

	block(notice) {
		this.notice = { variant: "error", ...notice };
		this.show();
	}

	async save() {
		const form = this.form;
		if (!form || this.busy || !this.station.session) return;
		if (!form.result)
			return this.block({
				code: "SSI_VALUE_INVALID",
				title: __("Result missing"),
				reason: __("Choose the result of the follow-up."),
				action: __("Tap one of the result buttons, then save."),
			});
		if (this.station.isOffline())
			return this.block({
				code: "OFFLINE",
				title: __("Station offline"),
				reason: __("Follow-up results are not kept on this device."),
				action: __("Reconnect, then save again."),
			});
		const args = {
			station: this.station.station,
			surveillance: form.surveillance,
			row: form.row,
			result: form.result,
			note: form.note || null,
		};
		const sig = JSON.stringify(args);
		if (!this.pending || this.pending.sig !== sig)
			this.pending = { sig, key: uuid4(), ts: clientTs() };
		const pending = this.pending;
		const version = this.station.sessionVersion;
		this.busy = true;
		this.show();
		let res = null;
		let failure = null;
		try {
			res = await this.station.rpc(
				SSI_RECORD,
				{ ...args, client_ts: pending.ts },
				pending.key
			);
		} catch (error) {
			failure = error;
		}
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		this.busy = false;
		if (failure) {
			if (failure.status >= 400 && failure.status < 500) this.pending = null;
			return this.block({
				technical: true,
				title: failure.status === 403 ? __("Not permitted") : __("Server error"),
				reason:
					failure.status === 403
						? __("This account cannot record surgical site infection follow-ups.")
						: __("The server could not process the request ({0}).", [
								failure.status || "?",
						  ]),
				action: __("Retry, or tell the infection control supervisor."),
			});
		}
		this.pending = null;
		if (res && res.ok === false) return this.block(res.error || {});
		this.context = res;
		this.form = null;
		this.notice = { variant: "ok", title: __("Follow-up recorded"), reason: "", action: "" };
		this.show();
	}

	retry() {
		this.station.manualOffline = false;
		if (!navigator.onLine) return this.station.setOffline(true);
		this.station.setOffline(false);
		this.notice = null;
		if (this.form && this.pending) return this.save();
		this.context = null;
		this.load();
	}

	show() {
		this.updatePlaceholder();
		const station = this.station;
		if (station.isOffline())
			return station.setState(
				"offline",
				this.alertHtml({
					variant: "info",
					title: __("Station offline"),
					reason: __(
						"Follow-ups need the network: patient data is not kept on this device."
					),
					action: __("Reconnect, then open the screen again."),
				})
			);
		if (!this.context && !this.loading && !this.failed) return this.load();
		if (this.loading || this.busy) return station.renderLoading();
		if (!this.context)
			return station.setState(
				"error",
				this.alertHtml({ variant: "error", technical: true, ...(this.failed || {}) })
			);
		const failed = this.notice && this.notice.variant === "error";
		const body = this.form ? this.formHtml() : this.listHtml();
		if (!this.form && !(this.context.due || []).length)
			return station.setState(
				"empty",
				`${this.notice ? this.alertHtml(this.notice) : ""}<p class="tc-empty">${esc(
					__("No follow-up due today.")
				)}</p>`
			);
		station.setState(
			failed ? "error" : "result",
			`<div class="tc-linen tc-ssi"><div data-region="notice">${
				this.notice ? this.alertHtml(this.notice) : ""
			}</div>${body}</div>`
		);
	}

	listHtml() {
		const rows = (this.context.due || [])
			.map(
				(row) => `<li class="tc-cen-episode">
				<p><span class="tc-mono">${esc(row.patient_code_masked || "")}</span> · ${esc(
					row.group_name || row.procedure_group || ""
				)}</p>
				<p class="tc-hint">${esc(
					__("Due {0} · {1}{2}", [
						frappe.datetime.str_to_user(row.due_date),
						__(row.method, null, SSI_CTX),
						row.is_final ? ` · ${__("last follow-up")}` : "",
					])
				)}</p>
				<button type="button" class="tc-btn tc-btn-primary" data-action="ssi-open" data-surveillance="${esc(
					row.name
				)}" data-row="${esc(row.row)}">${esc(__("Record result"))}</button>
			</li>`
			)
			.join("");
		return `<section class="tc-t6-block" aria-label="${esc(__("Follow-ups due"))}">
			<h2 class="tc-exp-title">${esc(__("Follow-ups due"))}</h2>
			<ul class="tc-cen-episodes">${rows}</ul>
			<p class="tc-hint">${esc(
				__("The patient code is shown masked. Do not enter the patient name.")
			)}</p>
		</section>`;
	}

	formHtml() {
		const form = this.form;
		const row = (this.context.due || []).find((item) => item.row === form.row) || {};
		const options = SSI_RESULTS.map(([value, label]) => {
			const chosen = form.result === value;
			return `<button type="button" class="tc-btn tc-btn-secondary tc-exp-option${
				chosen ? " is-chosen" : ""
			}" data-action="ssi-result" data-value="${esc(value)}" aria-pressed="${chosen}">${
				chosen ? '<span aria-hidden="true">&#10003; </span>' : ""
			}${esc(__(label, null, SSI_CTX))}</button>`;
		}).join("");
		return `<section class="tc-t6-block" aria-label="${esc(__("Record follow-up result"))}">
			<h2 class="tc-exp-title">${esc(__("Record follow-up result"))} <span class="tc-mono">${esc(
			row.patient_code_masked || ""
		)}</span></h2>
			<p class="tc-hint">${esc(row.group_name || "")} · ${esc(__(row.method || "", null, SSI_CTX))}</p>
			<div class="tc-aud-choices">${options}</div>
			<div class="tc-field"><label for="tc-ssi-note">${esc(__("Note"))}</label>
				<textarea id="tc-ssi-note" class="tc-input" data-ssi="note">${esc(
					form.note || ""
				)}</textarea></div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="ssi-save">${esc(
					__("Save")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="ssi-cancel">${esc(
					__("Cancel")
				)}</button>
			</div>
		</section>`;
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
}

window.SsiFollowupStation = SsiFollowupStation;
