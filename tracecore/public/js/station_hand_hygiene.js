/* global uuid4, clientTs, esc, tcErrorTitle, TcAudit */
// SCR-51 Phiếu vệ sinh tay theo cơ hội trên PDA (FEAT-061; UC-44; FR-M12-04, FR-M12-05, FR-M12-10; BRU-AUD-002/004;
// NFR-USAB-03, NFR-AVAIL-05; ADR-003, ADR-015). Mở từ màn phiếu giám sát (station_audit.js) khi mẫu được chọn là
// "Theo cơ hội". Mỗi cơ hội = 3 chạm: nghề nghiệp (chip, nhớ lại cho cơ hội sau) → thời điểm (nút sinh từ mục của mẫu) →
// hành động (chà cồn / rửa xà phòng / không thực hiện); chạm hành động là gửi ngay. Mất mạng: từng cơ hội và lệnh Ghi sổ
// xếp hàng IndexedDB (khóa = UUID cơ hội), phát lại theo thứ tự (`tracecore.v1.audit.record_opportunity`, rồi
// `submit_session`). Người được quan sát trùng người giám sát → alert-error inline, không lưu (BRU-AUD-004).

const HH_RECORD = "tracecore.v1.audit.record_opportunity";
const HH_SUBMIT = "tracecore.v1.audit.submit_session";
const HH_ACTIONS = ["Hand Rub", "Hand Wash", "Missed"];

// Tính tạm trên máy theo luật BRU-AUD-002 (kết quả chính thức do server tính khi ghi sổ)
const TcHygiene = {
	stats(rows) {
		const list = rows || [];
		const actioned = list.filter((row) => row.action !== "Missed").length;
		return {
			total: list.length,
			actioned,
			rate: list.length ? Math.round((actioned * 1000) / list.length) / 10 : null,
		};
	},

	actionLabel(action) {
		if (action === "Hand Rub") return __("Hand Rub");
		if (action === "Hand Wash") return __("Hand Wash");
		return __("Missed", null, "Hand Hygiene Opportunity");
	},
};

class HygieneView {
	constructor(form, template) {
		this.form = form;
		this.template = template;
		this.sessionUuid = uuid4();
		this.rows = [];
		this.role = "";
		this.moment = "";
		this.technique = false;
		this.glove = false;
		this.subject = "";
		this.form.notice = null;
		this.chain = Promise.resolve();
		this.submitKey = null;
		this.busy = false;
	}

	get station() {
		return this.form.station;
	}

	// ---- thao tác ----
	onAction(action, data) {
		const handlers = {
			"hh-role": () => {
				this.role = this.role === data.role ? "" : data.role;
			},
			"hh-moment": () => {
				this.moment = this.moment === data.moment ? "" : data.moment;
			},
			"hh-technique": () => {
				this.technique = !this.technique;
			},
			"hh-glove": () => {
				this.glove = !this.glove;
			},
			"hh-action": () => this.record(data.actionValue),
			"hh-submit": () => this.submit(),
		};
		if (!handlers[action]) return false;
		this.capture();
		this.form.notice = null;
		handlers[action]();
		if (action !== "hh-action" && action !== "hh-submit") this.form.show();
		return true;
	}

	capture() {
		const box = this.form.result.querySelector("#tc-hh-subject");
		if (box) this.subject = String(box.value || "").trim();
	}

	block(code, title, reason, action) {
		this.form.notice = { variant: "error", code, title, reason, action };
		this.form.show();
	}

	baseArgs() {
		return {
			station: this.station.station,
			audit_template: this.template.name,
			department: this.form.department,
			session_uuid: this.sessionUuid,
			mode: this.form.form.mode,
			location: this.form.form.location || "",
			started_at: this.form.form.started_at,
		};
	}

	record(action) {
		if (!HH_ACTIONS.includes(action)) return;
		const data = this.form.data() || {};
		if (!this.role || !this.moment) {
			return this.block(
				"AUDIT_OPPORTUNITY_INCOMPLETE",
				__("Profession and moment required"),
				__("The opportunity has no profession or no moment."),
				__("Tap the profession and the moment, then tap the action.")
			);
		}
		if (this.subject && this.subject === data.observer) {
			return this.block(
				"AUDIT_SELF_OBSERVATION",
				__("Cannot audit yourself"),
				__("The observed person is the observer."),
				__("Choose another observed person, or ask another auditor to observe you.")
			);
		}
		const row = {
			uuid: uuid4(),
			role: this.role,
			moment: this.moment,
			action,
			technique_ok: action !== "Missed" && this.technique ? 1 : 0,
			glove_instead: this.glove ? 1 : 0,
			subject: this.subject,
			ts: clientTs(),
			state: "pending",
		};
		this.rows.push(row);
		this.moment = ""; // thời điểm chọn lại cho cơ hội kế; nghề nghiệp giữ nguyên để cơ hội kế chỉ còn 2 chạm
		this.technique = false;
		this.glove = false;
		this.subject = "";
		this.form.notice = null;
		this.form.show();
		this.chain = this.chain.then(() => this.deliver(row));
	}

	opportunityArgs(row) {
		return {
			...this.baseArgs(),
			opportunity: JSON.stringify({
				uuid: row.uuid,
				subject_role: row.role,
				subject_employee: row.subject || "",
				moment: row.moment,
				action: row.action,
				technique_ok: row.technique_ok,
				glove_instead: row.glove_instead,
			}),
		};
	}

	drop(row) {
		this.rows = this.rows.filter((item) => item !== row);
	}

	async queueRow(row, args) {
		try {
			await this.station.queueCall(HH_RECORD, args, row.uuid, row.ts);
		} catch (error) {
			if (error.sessionEnded) return;
			this.drop(row);
			return this.block(
				"OFFLINE_STORE_FAILED",
				__("Could not keep the audit on this device"),
				__("The station storage is not available."),
				__("Post the audit when the connection returns, or call R10.")
			);
		}
		row.state = "queued";
		this.form.show();
	}

	async deliver(row) {
		const args = this.opportunityArgs(row);
		if (this.station.isOffline()) return this.queueRow(row, args);
		const version = this.station.sessionVersion;
		let response = null;
		try {
			response = await this.station.rpc(HH_RECORD, { ...args, client_ts: row.ts }, row.uuid);
		} catch (error) {
			if (error.sessionEnded || version !== this.station.sessionVersion) return;
			if (error.offline) return this.queueRow(row, args); // không có câu trả lời: giữ cơ hội, phát lại cùng khóa
			this.drop(row);
			return this.block(
				"SERVER_ERROR",
				__("Server error"),
				__("The server could not process the request ({0}).", [error.status || "?"]),
				__("Retry, or call R02 if it happens again.")
			);
		}
		if (version !== this.station.sessionVersion) return;
		if (response && response.ok === false) {
			this.drop(row);
			this.form.notice = { variant: "error", ...response.error };
			return this.form.show();
		}
		row.state = "sent";
		this.form.show();
	}

	async submit() {
		if (this.busy) return;
		if (!this.rows.length) {
			return this.block(
				"AUDIT_NO_OPPORTUNITY",
				__("No opportunity recorded"),
				__("The audit has no hand hygiene opportunity."),
				__("Record at least one opportunity before posting.")
			);
		}
		this.busy = true;
		this.form.show();
		await this.chain; // cơ hội đang gửi phải tới server trước lệnh Ghi sổ
		this.busy = false;
		if (!this.rows.length) return this.form.show();
		this.submitKey = this.submitKey || uuid4();
		this.submitTs = this.submitTs || clientTs();
		const args = {
			station: this.station.station,
			audit_template: this.template.name,
			department: this.form.department,
			session_uuid: this.sessionUuid,
		};
		if (this.station.isOffline()) return this.queueSubmit(args);
		const version = this.station.sessionVersion;
		this.busy = true;
		this.form.show();
		let response = null;
		let failure = null;
		try {
			response = await this.station.rpc(
				HH_SUBMIT,
				{ ...args, client_ts: this.submitTs },
				this.submitKey
			);
		} catch (error) {
			failure = error;
		}
		this.busy = false;
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		if (failure) {
			if (failure.offline) return this.queueSubmit(args);
			return this.block(
				"SERVER_ERROR",
				__("Server error"),
				__("The server could not process the request ({0}).", [failure.status || "?"]),
				__("Retry, or call R02 if it happens again.")
			);
		}
		if (response && response.ok === false) {
			this.form.notice = { variant: "error", ...response.error };
			return this.form.show();
		}
		const stats = TcHygiene.stats(this.rows);
		const rate =
			response.score_pct === null || response.score_pct === undefined
				? stats.rate
				: response.score_pct;
		this.form.done(
			__("Audit {0} posted", [response.name]),
			rate === null
				? __("Feedback was sent to the department.")
				: __(
						"Compliance {0} % over {1} opportunities. Feedback was sent to the department.",
						[TcAudit.number(rate), stats.total]
				  )
		);
	}

	async queueSubmit(args) {
		try {
			await this.station.queueCall(HH_SUBMIT, args, this.submitKey, clientTs());
		} catch (error) {
			if (error.sessionEnded) return;
			return this.block(
				"OFFLINE_STORE_FAILED",
				__("Could not keep the audit on this device"),
				__("The station storage is not available."),
				__("Post the audit when the connection returns, or call R10.")
			);
		}
		this.form.done(
			__("Audit kept on this device"),
			__("It is posted when the connection returns; the result is calculated by the server.")
		);
	}

	// ---- vẽ ----
	chip(role) {
		const on = this.role === role;
		return `<button type="button" class="tc-btn ${
			on ? "tc-btn-primary" : "tc-btn-secondary"
		} tc-aud-chip" data-action="hh-role" data-role="${esc(role)}" aria-pressed="${on}">${
			on ? "&#10003; " : ""
		}${esc(__(role))}</button>`;
	}

	momentButton(item) {
		const on = this.moment === item.moment;
		return `<button type="button" class="tc-btn tc-hh-moment${
			on ? " is-on" : ""
		}" data-action="hh-moment" data-moment="${esc(
			item.moment
		)}" aria-pressed="${on}" aria-label="${esc(
			__("Moment {0}: {1}", [item.moment, item.label])
		)}">${esc(item.moment)}</button>`;
	}

	actionButton(action) {
		const icon = { "Hand Rub": "&#10003; ", "Hand Wash": "&#10003; ", Missed: "&#10005; " }[
			action
		];
		return `<button type="button" class="tc-btn tc-hh-action" data-action-kind="${esc(
			action
		)}" data-action="hh-action" data-action-value="${esc(action)}"${
			this.busy ? " disabled" : ""
		}>${icon}${esc(TcHygiene.actionLabel(action))}</button>`;
	}

	recentHtml() {
		const items = this.rows
			.slice(-5)
			.reverse()
			.map(
				(row) =>
					`<li class="tc-hh-row" data-kind="${esc(row.action)}"><span>${esc(
						__(row.role)
					)} · ${esc(__("Moment {0}", [row.moment]))}${
						row.state === "queued"
							? ` <span class="tc-badge tc-badge-x">${esc(
									__("Waiting to sync")
							  )}</span>`
							: ""
					}</span><b>${esc(TcHygiene.actionLabel(row.action))}</b></li>`
			)
			.join("");
		return items
			? `<section class="tc-t6-block"><h3>${esc(
					__("Just recorded")
			  )}</h3><ul class="tc-hh-recent">${items}</ul></section>`
			: "";
	}

	html(data) {
		const form = this.form;
		const stats = TcHygiene.stats(this.rows);
		const department =
			(data.departments || []).find((row) => row.name === form.department) || {};
		const moments = this.template.moments || [];
		const chosen = moments.find((item) => item.moment === this.moment);
		const roles = (data.professions || []).map((role) => this.chip(role)).join("");
		const post = this.busy
			? __("Posting...")
			: __("Post audit ({0} opportunities)", [stats.total]);
		return `<section class="tc-aud-head">
				<h3>${esc(__("Hand hygiene"))} <span class="tc-mono">${esc(this.template.name)}</span></h3>
				<p>${esc(department.department_name || form.department)} · ${esc(
			__("Observer: {0}", [data.observer_name || data.observer || ""])
		)}</p>
				<p class="tc-hh-counter">${esc(__("Opportunities"))}: <b class="tc-mono">${
			stats.total
		}</b> · ${esc(__("Compliance"))}: <b class="tc-mono">${
			stats.rate === null
				? esc(__("Not calculated"))
				: `${esc(TcAudit.number(stats.rate))} %`
		}</b></p>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="aud-cancel">${esc(
					__("Cancel")
				)}</button>
			</section>
			<section class="tc-t6-block"><h3>${esc(
				__("Observed profession")
			)}</h3><div class="tc-aud-choices">${roles}</div></section>
			<section class="tc-t6-block"><h3>${esc(__("Moment"))}</h3>
				<div class="tc-hh-moments">${moments.map((item) => this.momentButton(item)).join("")}</div>
				<p class="tc-hint">${esc(chosen ? chosen.label : __("Tap one moment, then tap the action."))}</p>
			</section>
			<section class="tc-hh-actions">${HH_ACTIONS.map((action) => this.actionButton(action)).join(
				""
			)}</section>
			<section class="tc-t6-block">
				<div class="tc-aud-choices">
					<button type="button" class="tc-btn tc-btn-secondary tc-aud-chip" data-action="hh-technique" aria-pressed="${
						this.technique
					}">${this.technique ? "&#10003; " : ""}${esc(__("Correct Technique"))}</button>
					<button type="button" class="tc-btn tc-btn-secondary tc-aud-chip" data-action="hh-glove" aria-pressed="${
						this.glove
					}">${this.glove ? "&#10003; " : ""}${esc(
			__("Gloves Instead of Hand Hygiene")
		)}</button>
				</div>
				<label class="tc-field">${esc(
					__("Observed employee ID (optional)")
				)}<input id="tc-hh-subject" type="text" value="${esc(this.subject)}"></label>
			</section>
			${this.recentHtml()}
			<div class="tc-aud-footer">
				<button type="button" class="tc-btn tc-btn-primary tc-aud-post" data-action="hh-submit"${
					this.busy ? " disabled" : ""
				}>${esc(post)}</button>
			</div>`;
	}
}

window.HygieneView = HygieneView;
window.TcHygiene = TcHygiene;
