/* global uuid4, clientTs, esc, tcErrorTitle, HygieneView */
// SCR-52 Phiếu giám sát theo mục trên PDA (FEAT-060; UC-44; FR-M12-04, FR-M12-06, FR-M12-10; BRU-AUD-004/005; ADR-003, ADR-015).
// Page station, chức năng trạm AUDIT. Chọn mẫu + khoa một lần cho phiếu; mỗi mục một hàng với 3 nút chữ Đạt / Không /
// K. áp dụng (≥ 48 px, không chỉ màu; mục trọng yếu có nhãn chữ "Trọng yếu"); mục Không bắt buộc ghi chú; thanh kết quả
// tạm tính và nút Ghi sổ 56 px cố định dưới. Mất mạng: mẫu lấy từ snapshot của trạm, phiếu xếp hàng IndexedDB và gửi
// `tracecore.v1.audit.submit_session` (@idempotent, UUID phiếu làm X-Idempotency-Key) khi có mạng (NFR-AVAIL-05).
// Người giám sát = nhân viên của thẻ; trùng người được quan sát → alert-error inline, không lưu (BRU-AUD-004).

const AUD_CONTEXT = "tracecore.v1.audit.context";
const AUD_SUBMIT = "tracecore.v1.audit.submit_session";
const AUD_ANSWERS = ["Pass", "Fail", "N/A"];
// FEAT-062 (FR-M12-07, A-141 e): gói dự phòng gắn đợt thiết bị đang mở đúng loại
const AUD_BUNDLE_DEVICE = { VAP: "Ventilator", CLABSI: "Central Line", CAUTI: "Urinary Catheter" };

// Tính tạm trên máy theo đúng luật server (scoring.py); kết quả chính thức do server tính khi ghi sổ.
const TcAudit = {
	applicable(template, answers) {
		return (template.items || []).filter(
			(item) =>
				item.answer_type === "Pass/Fail" &&
				["Pass", "Fail"].includes(answers[item.item_code])
		);
	},

	provisional(template, answers) {
		const rows = TcAudit.applicable(template, answers);
		const critical = rows.some(
			(item) => item.is_critical && answers[item.item_code] === "Fail"
		);
		if (template.scoring_method === "All or None") {
			if (!rows.length) return { score: null, result: null, critical };
			return {
				score: null,
				result: rows.every((i) => answers[i.item_code] === "Pass") ? "Pass" : "Fail",
				critical,
			};
		}
		const total = rows.reduce((sum, item) => sum + Number(item.weight || 0), 0);
		if (!rows.length || total <= 0)
			return { score: null, result: critical ? "Fail" : null, critical };
		const passed = rows
			.filter((item) => answers[item.item_code] === "Pass")
			.reduce((sum, item) => sum + Number(item.weight || 0), 0);
		const score = Math.round((passed * 1000) / total) / 10;
		let result = "Pass";
		if (critical) result = "Fail";
		else if (
			template.pass_threshold !== null &&
			template.pass_threshold !== undefined &&
			template.pass_threshold !== ""
		)
			result = score >= Number(template.pass_threshold) ? "Pass" : "Fail";
		return { score, result, critical };
	},

	missing(template, answers) {
		return (template.items || [])
			.filter(
				(item) =>
					item.answer_type === "Pass/Fail" &&
					!AUD_ANSWERS.includes(answers[item.item_code])
			)
			.map((item) => item.item_code);
	},

	failWithoutNote(template, answers, notes) {
		return (template.items || [])
			.filter(
				(item) =>
					answers[item.item_code] === "Fail" &&
					!String(notes[item.item_code] || "").trim()
			)
			.map((item) => item.item_code);
	},

	resultLabel(state) {
		if (state.result === "Fail" && state.critical)
			return { cls: "r", label: __("Fail — critical item") };
		if (state.result === "Fail") return { cls: "r", label: __("Fail") };
		if (state.result === "Pass") return { cls: "g", label: __("Pass") };
		return { cls: "x", label: __("Not scored yet") };
	},

	number(value) {
		const rounded = Math.round(Number(value) * 10) / 10;
		const [whole, fraction] = rounded.toFixed(1).split(".");
		return whole + (fraction === "0" ? "" : `,${fraction}`);
	},
};

class AuditForm {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.clearSession();
	}

	get dialogOpen() {
		return Boolean(this.template); // phiếu đang chấm giữ focus trong form, ô quét không giành lại
	}

	clearSession() {
		this.context = null;
		this.contextFailed = null;
		this.loading = false;
		this.busy = null;
		this.offline = false;
		this.template = null;
		this.hygiene = null; // FEAT-061: màn vệ sinh tay theo cơ hội (SCR-51) khi mẫu là "Theo cơ hội"
		this.department = "";
		this.form = {};
		this.answers = {};
		this.notes = {};
		this.notice = null;
		this.pending = null; // phiếu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.updatePlaceholder();
	}

	updatePlaceholder() {
		const text = __("Choose a template and a department to start an audit");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	// màn phiếu không có mã để quét: nhắc chọn trên màn
	scan(raw) {
		this.input.value = "";
		if (!String(raw || "").trim()) return this.station.focus();
		this.notice = {
			variant: "info",
			title: __("Nothing to scan on this screen"),
			reason: __("Audits are filled by tapping the buttons below."),
			action: __("Choose a template and a department."),
		};
		this.show();
	}

	data() {
		if (this.station.isOffline()) {
			const snap = this.station.offlineData;
			return snap && snap.function === "AUDIT" ? snap : null;
		}
		return this.context;
	}

	async loadContext() {
		const station = this.station;
		if (this.loading || !station.session || station.isOffline()) return;
		const version = station.sessionVersion;
		this.loading = true;
		this.contextFailed = null;
		try {
			const res = await station.rpcRead(AUD_CONTEXT, {
				station: station.station,
				client_ts: clientTs(),
			});
			if (version !== station.sessionVersion) return;
			if (res && res.ok !== false) this.context = res;
			else this.contextFailed = station.failureCause(null, res);
		} catch (error) {
			if (error.sessionEnded) return;
			this.contextFailed = station.failureCause(error);
		} finally {
			this.loading = false;
		}
		if (version === station.sessionVersion) this.show();
	}

	// ---- thao tác ----
	onAction(action, target) {
		const data = target && target.dataset ? target.dataset : {};
		const handlers = {
			"aud-template": () => this.pickTemplate(data.template),
			"aud-department": () => {
				this.department = data.department;
				this.show();
			},
			"aud-role": () => {
				this.form.subject_role = this.form.subject_role === data.role ? "" : data.role;
				this.show();
			},
			// FEAT-062: chọn đợt thiết bị cho phiếu gói dự phòng
			"aud-episode": () => {
				this.form.device_episode =
					this.form.device_episode === data.episode ? "" : data.episode;
				this.notice = null;
				this.show();
			},
			// FEAT-070: chọn vùng vệ sinh cho phiếu VSMT/hạ tầng
			"aud-zone": () => {
				this.form.environment_zone =
					this.form.environment_zone === data.zone ? "" : data.zone;
				this.notice = null;
				this.show();
			},
			"aud-mode": () => {
				this.form.mode = this.form.mode === "Unannounced" ? "Announced" : "Unannounced";
				this.show();
			},
			"aud-answer": () => this.answer(data.item, data.answer),
			"aud-submit": () => this.submit(),
			"aud-cancel": () => {
				this.template = null;
				this.hygiene = null;
				this.answers = {};
				this.notes = {};
				this.notice = null;
				this.show();
			},
			retry: () => this.retry(),
		};
		if (!handlers[action]) {
			// FEAT-061: nút của màn vệ sinh tay (hh-*)
			return Boolean(this.hygiene && this.hygiene.onAction(action, data));
		}
		this.captureNotes();
		handlers[action]();
		return true;
	}

	// mẫu chấm theo mục (SCR-52) và mẫu "Theo cơ hội" (SCR-51, FEAT-061)
	allTemplates(data) {
		return [
			...((data && data.templates) || []),
			...((data && data.opportunity_templates) || []),
		];
	}

	pickTemplate(name) {
		const data = this.data();
		this.template = this.allTemplates(data).find((row) => row.name === name) || null;
		this.hygiene =
			this.template &&
			this.template.scoring_method === "By Opportunity" &&
			typeof HygieneView !== "undefined"
				? new HygieneView(this, this.template)
				: null;
		this.answers = {};
		this.notes = {};
		this.notice = null;
		this.form = { mode: "Announced", started_at: clientTs() };
		this.show();
	}

	answer(code, value) {
		if (!AUD_ANSWERS.includes(value)) return;
		this.answers[code] = this.answers[code] === value ? undefined : value;
		this.notice = null;
		this.show();
	}

	captureNotes() {
		this.result.querySelectorAll("[data-aud-note]").forEach((box) => {
			this.notes[box.dataset.audNote] = box.value;
		});
		const subject = this.result.querySelector("#tc-aud-subject");
		if (subject) this.form.subject_employee = subject.value.trim();
		const location = this.result.querySelector("#tc-aud-location");
		if (location) this.form.location = location.value;
		const nextDue = this.result.querySelector("#tc-aud-next-due"); // FEAT-070
		if (nextDue) this.form.next_due = nextDue.value;
	}

	block(code, title, reason, action, items) {
		this.notice = { variant: "error", code, title, reason, action, items };
		this.show();
	}

	submit() {
		const data = this.data() || {};
		if (!this.template || !this.department) {
			return this.block(
				"AUDIT_CONTEXT_MISSING",
				__("Template and department required"),
				__("The audit has no template or no department."),
				__("Choose the template and the department, then post again.")
			);
		}
		if (this.form.subject_employee && this.form.subject_employee === data.observer) {
			return this.block(
				"AUDIT_SELF_OBSERVATION",
				__("Cannot audit yourself"),
				__("The observed person is the observer."),
				__("Choose another observed person, or ask another auditor to observe you.")
			);
		}
		// FEAT-062 (FR-M12-07): gói VAP/CLABSI/CAUTI phải gắn đợt thiết bị đang mở
		if (this.bundleDevice() && !this.form.device_episode) {
			return this.block(
				"AUDIT_EPISODE_REQUIRED",
				__("Device episode required"),
				__("A bundle audit must be linked to the patient's open device episode."),
				__("Choose the device episode above, then post the audit.")
			);
		}
		// FEAT-070 (FR-M15-02): phiếu VSMT/hạ tầng của khoa đã khai báo vùng phải gắn vùng
		if (this.zoneAudit() && this.departmentZones(data).length && !this.form.environment_zone) {
			return this.block(
				"ENV_ZONE_REQUIRED",
				__("Zone required"),
				__("This department has cleaning zones; this audit is not linked to a zone."),
				__("Choose the zone you audited, then post the audit.")
			);
		}
		const missing = TcAudit.missing(this.template, this.answers);
		if (missing.length) {
			return this.block(
				"AUDIT_ANSWER_MISSING",
				__("Items not answered"),
				__("{0} item(s) have no answer.", [missing.length]),
				__("Choose Pass, Fail or N/A for every item, then post the audit."),
				missing
			);
		}
		const noNote = TcAudit.failWithoutNote(this.template, this.answers, this.notes);
		if (noNote.length) {
			return this.block(
				"AUDIT_FAIL_NOTE_REQUIRED",
				__("Note required for failed items"),
				__("Failed items {0} have no note.", [noNote.join(", ")]),
				__("Add a short note to each failed item.")
			);
		}
		const args = {
			station: this.station.station,
			audit_template: this.template.name,
			department: this.department,
			mode: this.form.mode,
			subject_role: this.form.subject_role || "",
			subject_employee: this.form.subject_employee || "",
			location: this.form.location || "",
			started_at: this.form.started_at,
			device_episode: this.form.device_episode || "", // FEAT-062
			environment_zone: this.form.environment_zone || "", // FEAT-070
			next_due: this.form.next_due || "", // FEAT-070
			answers: JSON.stringify(
				(this.template.items || [])
					.filter((item) => this.answers[item.item_code] || this.notes[item.item_code])
					.map((item) => ({
						item_code: item.item_code,
						answer: this.answers[item.item_code] || "",
						note: this.notes[item.item_code] || "",
					}))
			),
		};
		if (
			!this.pending ||
			this.pending.sig !==
				args.answers +
					args.department +
					args.audit_template +
					args.device_episode +
					args.environment_zone
		) {
			const key = uuid4();
			this.pending = {
				sig:
					args.answers +
					args.department +
					args.audit_template +
					args.device_episode +
					args.environment_zone,
				key,
				ts: clientTs(),
			};
		}
		args.session_uuid = this.pending.key;
		if (this.station.isOffline()) return this.queue(args);
		return this.send(args);
	}

	async queue(args) {
		try {
			await this.station.queueCall(AUD_SUBMIT, args, this.pending.key, this.pending.ts);
		} catch (error) {
			if (error.sessionEnded) return;
			return this.block(
				"OFFLINE_STORE_FAILED",
				__("Could not keep the audit on this device"),
				__("The station storage is not available."),
				__("Post the audit when the connection returns, or call R10.")
			);
		}
		this.done(
			__("Audit kept on this device"),
			__("It is posted when the connection returns; the result is calculated by the server.")
		);
	}

	async send(args) {
		if (this.busy) return;
		const version = this.station.sessionVersion;
		this.busy = AUD_SUBMIT;
		this.show();
		let response = null;
		let failure = null;
		try {
			response = await this.station.rpc(
				AUD_SUBMIT,
				{ ...args, client_ts: this.pending.ts },
				this.pending.key
			);
		} catch (error) {
			failure = error;
		}
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		this.busy = null;
		if (failure) {
			if (failure.offline) return this.queue(args); // không có câu trả lời: giữ phiếu, phát lại cùng key
			this.pending = null;
			return this.block(
				"SERVER_ERROR",
				__("Server error"),
				__("The server could not process the request ({0}).", [failure.status || "?"]),
				__("Retry, or call R02 if it happens again.")
			);
		}
		if (response && response.ok === false) {
			this.notice = { variant: "error", ...response.error };
			return this.show();
		}
		const label = TcAudit.resultLabel({
			result: response.result,
			critical: response.critical_failed,
		});
		this.done(
			__("Audit {0} posted: {1}", [response.name, label.label]),
			response.score_pct === null || response.score_pct === undefined
				? __("Feedback was sent to the department.")
				: __("Score {0} %. Feedback was sent to the department.", [
						TcAudit.number(response.score_pct),
				  ])
		);
	}

	done(title, reason) {
		this.pending = null;
		this.hygiene = null;
		this.template = null;
		this.answers = {};
		this.notes = {};
		this.notice = { variant: "ok", title, reason, action: __("Start the next audit.") };
		this.show();
	}

	retry() {
		this.notice = null;
		if (!this.context) this.loadContext();
		this.show();
	}

	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- vẽ ----
	show() {
		this.updatePlaceholder();
		const data = this.data();
		if (!data && !this.station.isOffline() && !this.contextFailed) this.loadContext();
		let body;
		if (!data && this.station.isOffline()) body = this.offlineHtml();
		else if (!data && this.contextFailed)
			body = this.alertHtml({ variant: "error", title: this.contextFailed });
		else if (!data)
			body = `<p class="tc-loading" role="status" aria-busy="true">${esc(
				__("Loading...")
			)}</p>`;
		else if (!this.template) body = this.startHtml(data);
		else if (this.hygiene) body = this.hygiene.html(data);
		else body = this.formHtml(data);
		const state = this.notice && this.notice.variant === "error" ? "error" : "result";
		this.station.setState(
			state,
			`<div class="tc-aud">${this.offline ? this.offlineHtml() : ""}${
				this.notice ? this.alertHtml(this.notice) : ""
			}${body}</div>`
		);
	}

	alertHtml(notice) {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		const items = (notice.items || []).map((item) => `<li>${esc(item)}</li>`).join("");
		const title = typeof tcErrorTitle === "function" ? tcErrorTitle(notice) : notice.title;
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(title)}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${items ? `<ul class="tc-alert-items">${items}</ul>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
		</div>`;
	}

	offlineHtml() {
		const ready = Boolean(this.data());
		return this.alertHtml({
			variant: "info",
			title: __(
				"Offline — audits are kept on this device and posted when the connection returns."
			),
			reason: ready
				? ""
				: __("No template was loaded on this device before the connection was lost."),
		});
	}

	startHtml(data) {
		const templates = this.allTemplates(data)
			.map(
				(row) =>
					`<button type="button" class="tc-btn tc-btn-secondary tc-aud-choice" data-action="aud-template" data-template="${esc(
						row.name
					)}">${esc(row.title)} <span class="tc-mono">${esc(row.name)}</span></button>`
			)
			.join("");
		const departments = (data.departments || [])
			.map(
				(row) =>
					`<button type="button" class="tc-btn ${
						row.name === this.department ? "tc-btn-primary" : "tc-btn-secondary"
					} tc-aud-choice" data-action="aud-department" data-department="${esc(
						row.name
					)}" aria-pressed="${row.name === this.department}">${
						row.name === this.department ? "&#10003; " : ""
					}${esc(row.department_name || row.name)}</button>`
			)
			.join("");
		if (!templates)
			return `<p class="tc-empty">${esc(
				__("No approved audit template. Ask R01 to approve one.")
			)}</p>`;
		return `<section class="tc-t6-block"><h3>${esc(
			__("Department")
		)}</h3><div class="tc-aud-choices">${departments}</div></section>
			<section class="tc-t6-block"><h3>${esc(__("Audit template"))}</h3>${
			this.department
				? `<div class="tc-aud-choices">${templates}</div>`
				: `<p class="tc-hint">${esc(__("Choose the department first."))}</p>`
		}</section>`;
	}

	// FEAT-062: loại thiết bị của mẫu gói đang chấm (null nếu mẫu không phải gói thiết bị)
	bundleDevice() {
		const template = this.template || {};
		return template.audit_type === "Prevention Bundle"
			? AUD_BUNDLE_DEVICE[template.bundle_type] || null
			: null;
	}

	episodeHtml(data) {
		const device = this.bundleDevice();
		if (!device) return "";
		const rows = (data.episodes || []).filter(
			(row) => row.department === this.department && row.device_type === device
		);
		const chips = rows
			.map((row) => {
				const chosen = this.form.device_episode === row.name;
				return `<button type="button" class="tc-btn ${
					chosen ? "tc-btn-primary" : "tc-btn-secondary"
				} tc-aud-choice" data-action="aud-episode" data-episode="${esc(
					row.name
				)}" aria-pressed="${chosen}">${
					chosen ? "&#10003; " : ""
				}<span class="tc-mono">${esc(row.patient_code_masked || "")}</span> · ${esc(
					__(row.device_type)
				)} · <span class="tc-mono">${esc(row.name)}</span></button>`;
			})
			.join("");
		return `<section class="tc-t6-block"><h3>${esc(__("Device episode"))}</h3>${
			chips
				? `<div class="tc-aud-choices">${chips}</div>`
				: `<p class="tc-hint">${esc(
						__(
							"No open {0} episode in this department. Open the episode on the census screen first.",
							[__(device).toLowerCase()]
						)
				  )}</p>`
		}</section>`;
	}

	// FEAT-070: phiếu vệ sinh môi trường / cơ sở hạ tầng gắn vùng vệ sinh của khoa
	zoneAudit() {
		const type = (this.template || {}).audit_type;
		return type === "Environmental Hygiene" || type === "Infrastructure";
	}

	departmentZones(data) {
		return ((data && data.zones) || []).filter((row) => row.department === this.department);
	}

	zoneHtml(data) {
		if (!this.zoneAudit()) return "";
		const chips = this.departmentZones(data)
			.map((row) => {
				const chosen = this.form.environment_zone === row.name;
				return `<button type="button" class="tc-btn ${
					chosen ? "tc-btn-primary" : "tc-btn-secondary"
				} tc-aud-choice" data-action="aud-zone" data-zone="${esc(
					row.name
				)}" aria-pressed="${chosen}">${chosen ? "&#10003; " : ""}${esc(
					row.area_name
				)} · ${esc(row.risk_level || "")}${
					row.awaiting_resample ? ` · ${esc(__("Awaiting resample"))}` : ""
				}</button>`;
			})
			.join("");
		const due =
			this.template.audit_type === "Infrastructure"
				? `<label class="tc-field">${esc(
						__("Next inspection due (empty = template interval)")
				  )}<input id="tc-aud-next-due" type="date" value="${esc(
						this.form.next_due || ""
				  )}"></label>`
				: "";
		return `<section class="tc-t6-block"><h3>${esc(__("Cleaning zone"))}</h3>${
			chips
				? `<div class="tc-aud-choices">${chips}</div>`
				: `<p class="tc-hint">${esc(__("This department has no cleaning zone."))}</p>`
		}${due}</section>`;
	}

	itemHtml(item) {
		const value = this.answers[item.item_code];
		const button = (answer, label, icon) => {
			const on = value === answer;
			return `<button type="button" class="tc-btn tc-aud-answer${
				on ? " is-on" : ""
			}" data-answer-kind="${answer}" data-action="aud-answer" data-item="${esc(
				item.item_code
			)}" data-answer="${answer}" aria-pressed="${on}">${icon}${esc(label)}</button>`;
		};
		const scored = item.answer_type === "Pass/Fail";
		return `<div class="tc-aud-item${item.is_critical ? " is-critical" : ""}">
			<p class="tc-aud-question">${esc(item.question)}${
			item.is_critical
				? ` <span class="tc-badge tc-badge-r">${esc(__("Critical"))}</span>`
				: ""
		}</p>
			${item.guidance ? `<p class="tc-hint">${esc(item.guidance)}</p>` : ""}
			${
				scored
					? `<div class="tc-aud-answers">${button(
							"Pass",
							__("Pass"),
							"&#10003; "
					  )}${button("Fail", __("Fail"), "&#10005; ")}${button(
							"N/A",
							__("N/A", null, "Audit Answer"),
							""
					  )}</div>`
					: ""
			}
			${
				value === "Fail" || !scored
					? `<label class="tc-field">${esc(
							value === "Fail" ? __("Note (required)") : __("Note")
					  )}
				<input type="text" data-aud-note="${esc(item.item_code)}" value="${esc(
							this.notes[item.item_code] || ""
					  )}"></label>`
					: ""
			}
		</div>`;
	}

	formHtml(data) {
		const template = this.template;
		const department =
			(data.departments || []).find((row) => row.name === this.department) || {};
		const state = TcAudit.provisional(template, this.answers);
		const label = TcAudit.resultLabel(state);
		const roles = (data.professions || [])
			.map(
				(role) =>
					`<button type="button" class="tc-btn ${
						this.form.subject_role === role ? "tc-btn-primary" : "tc-btn-secondary"
					} tc-aud-chip" data-action="aud-role" data-role="${esc(role)}" aria-pressed="${
						this.form.subject_role === role
					}">${esc(__(role))}</button>`
			)
			.join("");
		const method =
			template.scoring_method === "All or None" ? __("all-or-none") : __("weighted score");
		return `<section class="tc-aud-head">
				<h3>${esc(template.title)} <span class="tc-mono">${esc(template.name)}</span></h3>
				<p>${esc(department.department_name || this.department)} · ${esc(
			__("Observer: {0}", [data.observer_name || data.observer || ""])
		)}</p>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="aud-mode" aria-pressed="${
					this.form.mode === "Unannounced"
				}">${esc(
			this.form.mode === "Unannounced" ? __("Unannounced") : __("Announced")
		)}</button>
				<label class="tc-field">${esc(__("Location"))}<input id="tc-aud-location" type="text" value="${esc(
			this.form.location || ""
		)}"></label>
				<div class="tc-aud-choices">${roles}</div>
				<label class="tc-field">${esc(
					__("Observed employee ID (optional)")
				)}<input id="tc-aud-subject" type="text" value="${esc(
			this.form.subject_employee || ""
		)}"></label>
			</section>
			${this.episodeHtml(data)}
			${this.zoneHtml(data)}
			<section class="tc-aud-items">${(template.items || [])
				.map((item) => this.itemHtml(item))
				.join("")}</section>
			<div class="tc-aud-footer">
				<p>${esc(__("Result ({0})", [method]))}: <span class="tc-badge tc-badge-${label.cls}">${esc(
			label.label
		)}</span>${state.score === null ? "" : ` <b>${esc(TcAudit.number(state.score))} %</b>`}</p>
				<button type="button" class="tc-btn tc-btn-primary tc-aud-post" data-action="aud-submit"${
					this.busy ? " disabled" : ""
				}>${esc(this.busy ? __("Posting...") : __("Post audit"))}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="aud-cancel">${esc(
					__("Cancel")
				)}</button>
			</div>`;
	}
}

window.AuditForm = AuditForm;
window.TcAudit = TcAudit;
