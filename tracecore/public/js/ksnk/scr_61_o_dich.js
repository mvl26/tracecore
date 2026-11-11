/* global tracecore */
// SCR-61 Điều tra ổ dịch & khai báo bệnh truyền nhiễm — view WEB trong Page tc-ksnk (FEAT-069; UC-53, UC-50;
// FR-M14-09, .1, FR-M14-10, .1, FR-M13-13; BRU-MDR-004, BRU-MDR-005; A-150). R01: mở / Đã kiểm soát / kết thúc / hủy ổ
// dịch; R01, R11: gắn ca (M13/M14 hoặc mã BN), hành động kiểm soát (Incident CAPA), khai báo; R13: chỉ số liệu tổng hợp.
// Mã BN chỉ dạng che. Đường cong dịch: một ô = một ca, ký hiệu ✓ (Xác định) / ? (Nghi ngờ) / × (Loại trừ), không chỉ
// màu. Lỗi chặn = alert inline (kết quả → lý do → hành động).

const TC_OD_OVERVIEW = "tracecore.v1.outbreak.overview";
const TC_OD_CANDIDATES = "tracecore.v1.outbreak.candidates";
const TC_OD = "tracecore.v1.outbreak.";
const TC_OD_CONTEXT = "Outbreak Investigation";

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr61 = {
	uuid() {
		const bytes = crypto.getRandomValues(new Uint8Array(16));
		bytes[6] = (bytes[6] & 0x0f) | 0x40;
		bytes[8] = (bytes[8] & 0x3f) | 0x80;
		const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
		return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(
			16,
			20
		)}-${hex.slice(20)}`;
	},

	iso(date = new Date()) {
		const pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
		const offset = -date.getTimezoneOffset();
		return (
			`${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
			`T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
			`${offset >= 0 ? "+" : "-"}${pad(offset / 60)}:${pad(offset % 60)}`
		);
	},

	date(value) {
		if (!value) return "—";
		const [y, m, d] = String(value).slice(0, 10).split("-");
		return `${d}/${m}/${y}`;
	},

	datetime(value) {
		if (!value) return "—";
		const text = String(value);
		return `${TcKsnkScr61.date(text)} ${text.slice(11, 16)}`.trim();
	},

	// POST @idempotent: khóa giữ nguyên khi bấm lại cùng dữ liệu (thử lại sau lỗi mạng)
	post(method, args, handlers) {
		const sig = JSON.stringify([method, args]);
		if (!TcKsnkScr61.pending || TcKsnkScr61.pending.sig !== sig)
			TcKsnkScr61.pending = { sig, key: TcKsnkScr61.uuid(), ts: TcKsnkScr61.iso() };
		const pending = TcKsnkScr61.pending;
		const handle = (result) => {
			TcKsnkScr61.pending = null;
			if (result && result.ok === false) {
				handlers.on_block(result.error || {});
				return;
			}
			tracecore.saved_notice(handlers.success);
			handlers.on_ok(result || {});
		};
		frappe.call({
			method: TC_OD + method,
			args: { ...args, client_ts: pending.ts },
			headers: { "X-Idempotency-Key": pending.key },
			callback: (response) => handle(response.message),
			error: (xhr) => {
				const body = xhr && xhr.responseJSON && xhr.responseJSON.message;
				if (body && body.ok === false) return handle(body);
				handlers.on_fail && handlers.on_fail();
			},
		});
	},

	blockHtml(error, esc) {
		const e = error || {};
		return (
			`<div class="tc-ksnk-alert" role="alert"><strong>${esc(
				e.title || __("Not saved")
			)}</strong>` +
			`<div>${esc(e.reason || "")}</div><div>${esc(e.action || "")}</div></div>`
		);
	},

	badge(cls, text, esc) {
		return `<span class="tc-ksnk-badge ${cls}">${esc(text)}</span>`;
	},

	caseBadge(state, esc) {
		const map = {
			Confirmed: ["is-fail", __("Confirmed", null, TC_OD_CONTEXT)],
			Suspected: ["is-warn", __("Suspected", null, TC_OD_CONTEXT)],
			Excluded: ["is-neutral", __("Excluded", null, TC_OD_CONTEXT)],
		};
		const [cls, text] = map[state] || map.Suspected;
		return TcKsnkScr61.badge(cls, text, esc);
	},

	statusBadge(status, esc) {
		const cls =
			{ Investigating: "is-fail", Controlled: "is-warn", Ended: "is-pass" }[status] ||
			"is-neutral";
		return TcKsnkScr61.badge(cls, __(status, null, TC_OD_CONTEXT), esc);
	},

	actionBadge(state, esc) {
		const map = {
			Done: ["is-pass", __("Done")],
			Open: ["is-info", __("In progress")],
			Overdue: ["is-fail", __("Overdue")],
		};
		const [cls, text] = map[state] || map.Open;
		return TcKsnkScr61.badge(cls, text, esc);
	},

	remaining(minutes) {
		const m = Math.max(Number(minutes) || 0, 0);
		return __("{0} h {1} min left", [Math.floor(m / 60), m % 60]);
	},

	reportBadge(row, esc) {
		const self = TcKsnkScr61;
		switch (row.state) {
			case "Awaiting report":
				return self.badge("is-warn", self.remaining(row.remaining_minutes), esc);
			case "Overdue":
				return self.badge("is-fail", __("Overdue — not reported"), esc);
			case "Reference missing":
				return self.badge("is-warn", __("Report reference missing"), esc);
			case "Reported":
				return self.badge("is-pass", __("Reported"), esc);
			case "Reported late":
				return self.badge("is-fail", __("Reported late"), esc);
			case "Cancelled":
				return self.badge("is-neutral", __("Cancelled"), esc);
			default:
				return self.badge("is-neutral", __("No deadline configured"), esc);
		}
	},

	// --- cảnh báo cụm ca ----------------------------------------------------------------------------------------

	alertsHtml(data, esc) {
		const self = TcKsnkScr61;
		const rows = data.alerts || [];
		const config = data.rules_configured
			? ""
			: `<div class="tc-ksnk-alert is-info" role="note">${esc(
					__("No cluster alert threshold is configured, so no cluster is detected.")
			  )} <a href="${esc(data.rule_form)}">${esc(__("Set thresholds"))}</a></div>`;
		if (!rows.length) return config;
		return (
			config +
			rows
				.map(
					(a) => `<div class="tc-ksnk-alert is-warn" role="alert" data-alert="${esc(
						a.name
					)}">
					<strong>${esc(__("Cluster alert — {0}", [a.department_name || a.department]))}:</strong>
					${esc(
						__(
							"{0} cases of {1} in {2} days (threshold {3} cases / {2} days), {4} – {5}.",
							[
								a.case_count,
								a.key_label,
								a.window_days,
								a.min_cases,
								self.date(a.window_start),
								self.date(a.window_end),
							]
						)
					)}
					<div class="tc-ksnk-actions">
						${
							data.can_own
								? `<button type="button" class="btn btn-danger" data-action="open-from-alert" data-name="${esc(
										a.name
								  )}">${esc(__("Open outbreak investigation"))}</button>`
								: ""
						}
						${
							data.can_work
								? `<button type="button" class="btn btn-default" data-action="dismiss" data-name="${esc(
										a.name
								  )}">${esc(__("Mark as reviewed"))}</button>`
								: ""
						}
					</div></div>`
				)
				.join("")
		);
	},

	// --- danh sách, form mở ---------------------------------------------------------------------------------------

	listHtml(data, esc) {
		const self = TcKsnkScr61;
		const rows = data.summary || [];
		const current = data.current ? data.current.name : "";
		const body = rows
			.map(
				(r) => `<tr${r.name === current ? ' aria-current="true"' : ""}>
				<td class="tc-ksnk-code">${
					data.can_work
						? `<a href="/app/tc-ksnk/o-dich?outbreak=${encodeURIComponent(
								r.name
						  )}">${esc(r.name)}</a>`
						: esc(r.name)
				}</td>
				<td>${esc(r.title)}</td><td>${esc(r.organism_or_disease)}</td>
				<td>${esc(r.department_name || r.department)}</td><td>${esc(self.date(r.start_date))}</td>
				<td class="is-num">${esc(r.case_count)}</td><td class="is-num">${esc(r.days)}</td>
				<td>${self.statusBadge(r.status, esc)}</td></tr>`
			)
			.join("");
		const table = rows.length
			? `<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Code"))}</th><th>${esc(
					__("Title")
			  )}</th><th>${esc(__("Organism or Disease"))}</th><th>${esc(
					__("Department")
			  )}</th><th>${esc(__("Start Date"))}</th><th>${esc(__("Cases"))}</th><th>${esc(
					__("Days")
			  )}</th><th>${esc(__("Status"))}</th></tr></thead><tbody>${body}</tbody></table>`
			: `<p class="tc-ksnk-state">${esc(__("No outbreak investigation yet."))}</p>`;
		const add = data.can_own
			? `<div class="tc-ksnk-actions"><button type="button" class="btn btn-default" data-action="new">${esc(
					__("New outbreak investigation")
			  )}</button></div>`
			: "";
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Outbreak investigations")
		)} <span class="tc-ksnk-tag tc-ksnk-code">Outbreak Investigation · OD-</span></h3>${table}${add}</section>`;
	},

	openFormHtml(data, esc, show) {
		if (!data.can_own || !(show || data.prefill)) return "";
		const p = data.prefill || {};
		const department = p.department || "";
		const options = (data.departments || [])
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						row.name === department ? " selected" : ""
					}>${esc(row.label)}</option>`
			)
			.join("");
		const known = (data.departments || []).some((row) => row.name === department);
		const extra =
			department && !known
				? `<option value="${esc(department)}" selected>${esc(
						p.department_name || department
				  )}</option>`
				: "";
		const cases = p.cases
			? `<p class="tc-ksnk-note">${esc(
					__("{0} cases of the alert are linked when the investigation opens.", [
						p.cases.length,
					])
			  )}</p>`
			: "";
		return `<section class="tc-ksnk-card" data-region="open">
			<h3>${esc(__("Open outbreak investigation"))}${
			p.alert
				? ` <span class="tc-ksnk-tag tc-ksnk-code">${esc(p.alert)} · ${esc(
						p.source_label
				  )}</span>`
				: ""
		}</h3>
			<div class="tc-ksnk-form tc-ksnk-stack">
				<label>${esc(
					__("Title")
				)} *<input type="text" class="form-control" data-field="title" maxlength="140" value="${esc(
			p.title || ""
		)}"></label>
				<label>${esc(
					__("Organism or Disease")
				)} *<input type="text" class="form-control" data-field="organism_or_disease" maxlength="140" value="${esc(
			p.organism_or_disease || ""
		)}"></label>
				<label>${esc(__("Department"))} *<select class="form-control" data-field="department">
					<option value="">${esc(__("— Choose —"))}</option>${extra}${options}</select></label>
				<label>${esc(
					__("Start Date")
				)} *<input type="date" class="form-control" data-field="start_date" value="${esc(
			p.start_date || ""
		)}"></label>
				<label>${esc(
					__("Case Definition")
				)}<textarea class="form-control" data-field="case_definition" rows="3"></textarea></label>
			</div>${cases}
			<div data-region="open-alert"></div>
			<div class="tc-ksnk-actions">
				<button type="button" class="btn btn-primary" data-action="open">${esc(
					__("Open outbreak investigation")
				)}</button>
			</div></section>`;
	},

	// --- chi tiết ------------------------------------------------------------------------------------------------

	curveHtml(curve, esc) {
		const self = TcKsnkScr61;
		const days = (curve && curve.days) || [];
		if (!days.length)
			return `<p class="tc-ksnk-state">${esc(
				__("Link cases to draw the epidemic curve.")
			)}</p>`;
		const cell = (cls, mark, label) =>
			`<span class="tc-od-cell ${cls}" title="${esc(label)}">${mark}</span>`;
		const cols = days
			.map((day) => {
				const cells = [];
				for (let i = 0; i < day.excluded; i++)
					cells.push(cell("is-excluded", "×", __("Excluded case")));
				for (let i = 0; i < day.suspected; i++)
					cells.push(cell("is-suspected", "?", __("Suspected case")));
				for (let i = 0; i < day.confirmed; i++)
					cells.push(cell("is-confirmed", "✓", __("Confirmed case")));
				const total = day.confirmed + day.suspected + day.excluded;
				return `<div class="tc-od-day" role="listitem" aria-label="${esc(
					`${self.date(day.date)}: ${total}`
				)}"><div class="tc-od-stack">${cells.join("")}</div><span class="tc-od-axis">${esc(
					day.date.slice(8, 10)
				)}</span></div>`;
			})
			.join("");
		return `<div class="tc-od-curve" role="list">${cols}</div>
			<p class="tc-ksnk-note">${cell("is-confirmed", "✓", "")} ${esc(
			__("Confirmed case (one cell = one case)")
		)} &nbsp; ${cell("is-suspected", "?", "")} ${esc(__("Suspected case"))} &nbsp; ${cell(
			"is-excluded",
			"×",
			""
		)} ${esc(__("Excluded case"))} &nbsp; ${esc(
			__("Axis: onset date {0} – {1}", [self.date(curve.from), self.date(curve.to)])
		)}</p>`;
	},

	casesHtml(d, data, esc) {
		const self = TcKsnkScr61;
		const active = ["Investigating", "Controlled"].includes(d.status);
		const rows = (d.cases || [])
			.map(
				(c) => `<tr>
				<td class="tc-ksnk-code">${esc(c.ref || __("Patient code"))}</td>
				<td class="tc-ksnk-code">${esc(c.patient_code_masked || "—")}</td>
				<td>${esc(self.date(c.onset_date))}</td>
				<td>${self.caseBadge(c.state, esc)}${
					c.excluded_at_source
						? ` <span class="tc-ksnk-note">${esc(
								__("Case excluded in HAI surveillance")
						  )}</span>`
						: ""
				}</td>
				<td>${esc(c.label || "")}</td>
				<td>${
					active && data.can_work
						? `<button type="button" class="btn btn-link" data-action="remove-case" data-name="${esc(
								c.row
						  )}">${esc(__("Remove"))}</button>`
						: ""
				}</td></tr>`
			)
			.join("");
		const table = rows
			? `<table class="tc-ksnk-table"><thead><tr><th>${esc(
					__("Case / isolate")
			  )}</th><th>${esc(__("Patient Code"))}</th><th>${esc(__("Onset"))}</th><th>${esc(
					__("Status")
			  )}</th><th>${esc(
					__("Organism or Infection")
			  )}</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-state">${esc(__("No case linked yet."))}</p>`;
		const buttons =
			active && data.can_work
				? `<div class="tc-ksnk-actions">
				<button type="button" class="btn btn-default" data-action="add-source">${esc(
					__("Link cases from M13/M14")
				)}</button>
				<button type="button" class="btn btn-default" data-action="add-manual">${esc(
					__("Add case by patient code")
				)}</button></div>`
				: "";
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Cases linked to the outbreak")
		)}</h3>${table}${buttons}</section>`;
	},

	actionsHtml(d, data, esc) {
		const self = TcKsnkScr61;
		const active = ["Investigating", "Controlled"].includes(d.status);
		const rows = (d.actions || [])
			.map(
				(a) => `<tr><td>${esc(a.description)}</td><td>${esc(
					a.responsible_name || a.responsible || ""
				)}</td>
				<td>${esc(self.date(a.due_date))}</td><td>${self.actionBadge(a.state, esc)}</td>
				<td class="tc-ksnk-code"><a href="/app/incident-capa/${encodeURIComponent(a.incident)}">${esc(
					a.incident
				)}</a></td></tr>`
			)
			.join("");
		const table = rows
			? `<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Action"))}</th><th>${esc(
					__("Responsible")
			  )}</th><th>${esc(__("Due"))}</th><th>${esc(__("Status"))}</th><th>${esc(
					__("Incident")
			  )}</th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-state">${esc(__("No control action yet."))}</p>`;
		const incidents = (d.incidents || [])
			.map(
				(i) =>
					`<li><span class="tc-ksnk-code">${esc(i.incident)}</span> ${self.badge(
						i.closed ? "is-pass" : "is-neutral",
						__(i.status || "New"),
						esc
					)}${i.open_reason ? ` — ${esc(i.open_reason)}` : ""}</li>`
			)
			.join("");
		const buttons =
			active && data.can_work
				? `<div class="tc-ksnk-actions">
				<button type="button" class="btn btn-default" data-action="add-action">${esc(
					__("Add control action")
				)}</button>
				<button type="button" class="btn btn-default" data-action="link-nc">${esc(
					__("Link existing incident")
				)}</button></div>`
				: "";
		return `<section class="tc-ksnk-card"><h3>${esc(__("Control actions"))}</h3>${table}${
			incidents ? `<ul class="tc-ksnk-todos">${incidents}</ul>` : ""
		}${buttons}</section>`;
	},

	detailHtml(data, esc) {
		const self = TcKsnkScr61;
		const d = data.current;
		if (!d) return "";
		const info = [
			[
				__("Opened by"),
				`${d.opened_by_name || d.opened_by || "—"}, ${self.date(d.opened_at)}`,
			],
			[__("Detected By"), __(d.source || "")],
			[__("Organism or Disease"), d.organism_or_disease],
			[
				__("Departments"),
				[
					d.department_name,
					...(d.departments || []).filter((x) => x !== d.department),
				].join(", "),
			],
		]
			.map(
				([label, value]) =>
					`<div><span class="tc-ksnk-note">${esc(label)}</span><div>${esc(
						value
					)}</div></div>`
			)
			.join("");
		const active = ["Investigating", "Controlled"].includes(d.status);
		const ended = d.status === "Ended";
		const footer = `<div class="tc-ksnk-actions" data-region="footer">
			${
				data.can_own && d.status === "Investigating"
					? `<button type="button" class="btn btn-default" data-action="controlled">${esc(
							__("Mark as controlled")
					  )}</button>`
					: ""
			}
			${
				data.can_own && active
					? `<button type="button" class="btn btn-success" data-action="end">${esc(
							__("End outbreak")
					  )}</button>`
					: ""
			}
			<a class="btn btn-default" target="_blank" rel="noopener" href="${esc(
				data.print_outbreak + encodeURIComponent(d.name)
			)}">${esc(__("Export outbreak report form"))}</a>
			${
				data.can_own && active
					? `<button type="button" class="btn btn-link" data-action="cancel-outbreak">${esc(
							__("Cancel entry")
					  )}</button>`
					: ""
			}
			<span class="tc-ksnk-note">${esc(
				__("Only R01 opens and ends an outbreak investigation.")
			)}</span></div>`;
		const closing = ended
			? `<div class="tc-ksnk-alert is-info" role="note"><strong>${esc(
					__("Ended on {0}", [self.date(d.end_date)])
			  )}</strong><div>${esc(d.summary || "")}</div>${
					d.external_report_ref
						? `<div>${esc(__("External report"))}: <span class="tc-ksnk-code">${esc(
								d.external_report_ref
						  )}</span></div>`
						: ""
			  }</div>`
			: "";
		return `<section class="tc-ksnk-card" data-region="detail" data-name="${esc(d.name)}">
			<h3>${esc(d.title)} <span class="tc-ksnk-tag tc-ksnk-code">${esc(
			d.name
		)} · SCR-61 · UC-53</span> ${self.statusBadge(d.status, esc)}</h3>
			<div class="tc-ksnk-kpis tc-od-info">${info}</div>
			${
				d.case_definition
					? `<p><span class="tc-ksnk-note">${esc(__("Case Definition"))}:</span> ${esc(
							d.case_definition
					  )}</p>`
					: ""
			}
			<h4>${esc(__("Epidemic curve by onset date"))}</h4>${self.curveHtml(d.curve, esc)}
			${closing}</section>
			<div data-region="detail-alert"></div>
			<div class="tc-ksnk-cols"><div>${self.casesHtml(d, data, esc)}</div><div>${self.actionsHtml(
			d,
			data,
			esc
		)}</div></div>${footer}`;
	},

	// --- khai báo ------------------------------------------------------------------------------------------------

	reportsHtml(data, esc) {
		const self = TcKsnkScr61;
		const missing = (data.missing_groups || []).length
			? `<div class="tc-ksnk-alert is-warn" role="alert">${esc(
					__("No reporting deadline is configured for disease group {0}.", [
						data.missing_groups.join(", "),
					])
			  )} <a href="${esc(data.settings_form)}">${esc(__("IC Program Settings"))}</a></div>`
			: "";
		const note = `<div class="tc-ksnk-alert is-info" role="note">${esc(
			__(
				"The reporting deadline follows the configured disease group A/B/C (awaiting confirmation of the current regulation — OQ-V12-03). Report on the national surveillance system; TraceCore only tracks whether it was reported."
			)
		)}</div>`;
		if (!data.can_work) {
			const counts = Object.entries(data.report_summary || {})
				.map(([state, n]) => `<li>${esc(__(state))}: <strong>${esc(n)}</strong></li>`)
				.join("");
			return `<section class="tc-ksnk-card"><h3>${esc(
				__("Notifiable communicable diseases")
			)}</h3>${
				counts
					? `<ul class="tc-ksnk-todos">${counts}</ul>`
					: `<p class="tc-ksnk-state">${esc(__("No report."))}</p>`
			}${note}</section>`;
		}
		const rows = (data.reports || [])
			.map(
				(r) => `<tr>
				<td class="tc-ksnk-code">${esc(r.name)}</td><td class="tc-ksnk-code">${esc(
					r.patient_code_masked || "—"
				)}</td>
				<td>${esc(r.disease_name || r.disease)}</td><td>${esc(r.disease_group || "")}</td>
				<td>${esc(r.department_name || r.department)}</td>
				<td>${esc(self.datetime(r.diagnosed_on))}</td><td>${esc(self.datetime(r.due_by))}</td>
				<td>${self.reportBadge(r, esc)}${
					r.report_ref ? ` <span class="tc-ksnk-code">${esc(r.report_ref)}</span>` : ""
				}</td>
				<td>${
					r.state !== "Reported" &&
					r.state !== "Reported late" &&
					r.state !== "Cancelled"
						? `<button type="button" class="btn btn-link" data-action="reported" data-name="${esc(
								r.name
						  )}">${esc(__("Record as reported"))}</button>`
						: ""
				}${
					data.can_cancel_report && r.state !== "Cancelled"
						? `<button type="button" class="btn btn-link" data-action="cancel-report" data-name="${esc(
								r.name
						  )}">${esc(__("Cancel entry"))}</button>`
						: ""
				}</td></tr>`
			)
			.join("");
		const table = rows
			? `<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Code"))}</th><th>${esc(
					__("Patient Code")
			  )}</th><th>${esc(__("Disease"))}</th><th>${esc(__("Group"))}</th><th>${esc(
					__("Department")
			  )}</th><th>${esc(__("Diagnosed On"))}</th><th>${esc(__("Due By"))}</th><th>${esc(
					__("Status")
			  )}</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-state">${esc(__("No report."))}</p>`;
		const diseases = (data.diseases || [])
			.map(
				(row) =>
					`<option value="${esc(row.name)}">${esc(
						`${row.disease_name} (${row.disease_group})`
					)}</option>`
			)
			.join("");
		const departments = (data.departments || [])
			.map((row) => `<option value="${esc(row.name)}">${esc(row.label)}</option>`)
			.join("");
		const form = `<div class="tc-ksnk-form" data-region="report-form">
			<label>${esc(
				__("Department")
			)} *<select class="form-control" data-field="department"><option value="">${esc(
			__("— Choose —")
		)}</option>${departments}</select></label>
			<label>${esc(
				__("Patient Code")
			)} *<input type="text" class="form-control" data-field="patient_code" autocomplete="off" maxlength="64"></label>
			<label>${esc(
				__("Disease")
			)} *<select class="form-control" data-field="disease"><option value="">${esc(
			__("— Choose —")
		)}</option>${diseases}</select></label>
			<label>${esc(
				__("Diagnosed On")
			)} *<input type="datetime-local" class="form-control" data-field="diagnosed_on"></label>
			<button type="button" class="btn btn-primary" data-action="create-report">${esc(
				__("Record notifiable case")
			)}</button></div>
			<p class="tc-ksnk-note">${esc(
				__(
					"The patient code is encrypted and shown masked. Do not enter the patient name."
				)
			)} <a href="${esc(data.disease_form)}">${esc(
			__("Communicable disease list")
		)}</a></p>`;
		return `<section class="tc-ksnk-card" data-region="reports"><h3>${esc(
			__("Notifiable communicable diseases")
		)} <span class="tc-ksnk-tag tc-ksnk-code">Notifiable Disease Report · KB-</span></h3>
			${missing}${table}${form}<div data-region="report-alert"></div>${note}</section>`;
	},

	pageHtml(data, esc, showForm) {
		const self = TcKsnkScr61;
		return (
			`<div data-region="alerts">${self.alertsHtml(data, esc)}</div>` +
			self.openFormHtml(data, esc, showForm) +
			self.detailHtml(data, esc) +
			self.listHtml(data, esc) +
			self.reportsHtml(data, esc)
		);
	},

	// --- thao tác ------------------------------------------------------------------------------------------------

	values(region) {
		const out = {};
		region.querySelectorAll("[data-field]").forEach((input) => {
			out[input.dataset.field] = input.value;
		});
		return out;
	},

	act(el, ctx, method, args, alertRegion, done) {
		const self = TcKsnkScr61;
		self.post(method, args, {
			on_ok: (result) => {
				if (!ctx.isCurrent()) return;
				const warn = (result.warnings || []).join(" ");
				if (warn) frappe.show_alert({ message: warn, indicator: "orange" });
				if (done) done(result);
				else self.render(el, ctx);
			},
			on_block: (error) => {
				const region = el.querySelector(alertRegion);
				if (region) region.innerHTML = self.blockHtml(error, ctx.esc);
			},
		});
	},

	// đổi ổ dịch đang xem / cảnh báo đang mở mà không rời Page (tham số ngoài bộ lọc chung của shell)
	go(el, ctx, params) {
		const query = new URLSearchParams();
		Object.entries(params || {}).forEach(([key, value]) => value && query.set(key, value));
		const qs = query.toString();
		window.history.replaceState(null, "", `/app/tc-ksnk/o-dich${qs ? `?${qs}` : ""}`);
		TcKsnkScr61.render(el, ctx);
	},

	prompt(fields, title, done) {
		frappe.prompt(fields, done, title, __("Confirm"));
	},

	async pickCase(el, ctx, outbreak) {
		const self = TcKsnkScr61;
		const [hai, iso] = await Promise.all([
			ctx.get(TC_OD_CANDIDATES, { outbreak, source_type: "HAI Case" }),
			ctx.get(TC_OD_CANDIDATES, { outbreak, source_type: "Microbiology Isolate" }),
		]);
		const map = {};
		const label = (row) =>
			`${row.name} · ${row.patient_code_masked || ""} · ${self.date(row.date)} · ${__(
				row.label || ""
			)}`;
		(hai.rows || []).forEach((row) => (map[label(row)] = ["HAI Case", row.name]));
		(iso.rows || []).forEach((row) => (map[label(row)] = ["Microbiology Isolate", row.name]));
		const options = Object.keys(map);
		if (!options.length) {
			frappe.show_alert({
				message: __("No unlinked HAI case or isolate of these departments."),
				indicator: "orange",
			});
			return;
		}
		self.prompt(
			[
				{
					fieldname: "item",
					fieldtype: "Select",
					label: __("Case / isolate"),
					options,
					reqd: 1,
				},
			],
			__("Link cases from M13/M14"),
			(v) => {
				const [source_type, ref] = map[v.item];
				self.act(
					el,
					ctx,
					"add_case",
					{ outbreak, source_type, ref },
					'[data-region="detail-alert"]'
				);
			}
		);
	},

	bind(el, ctx, data) {
		const self = TcKsnkScr61;
		const on = (selector, handler) =>
			el
				.querySelectorAll(selector)
				.forEach((node) => node.addEventListener("click", handler));
		const outbreak = data && data.current ? data.current.name : "";
		on('[data-action="new"]', () => {
			el.innerHTML = self.pageHtml(data, ctx.esc, true);
			self.bind(el, ctx, data);
		});
		on('[data-action="open-from-alert"]', (event) =>
			self.go(el, ctx, { alert: event.currentTarget.dataset.name })
		);
		on('[data-action="dismiss"]', (event) =>
			self.prompt(
				[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
				__("Mark as reviewed (no investigation)"),
				(v) =>
					self.act(
						el,
						ctx,
						"dismiss_alert",
						{ alert: event.currentTarget.dataset.name, reason: v.reason },
						'[data-region="alerts"]'
					)
			)
		);
		on('[data-action="open"]', () => {
			const form = el.querySelector('[data-region="open"]');
			const values = self.values(form);
			const alert = (data.prefill && data.prefill.alert) || "";
			self.act(
				el,
				ctx,
				"open_outbreak",
				{
					...values,
					cluster_alert: alert,
					organism: (data.prefill && data.prefill.organism) || "",
					// A-151 Q1: mở từ bản ghi nguồn của module khác (sự cố nghi ngộ độc thực phẩm)
					source: (!alert && data.prefill && data.prefill.source) || "",
					source_doctype: (!alert && data.prefill && data.prefill.source_doctype) || "",
					source_name: (!alert && data.prefill && data.prefill.source_name) || "",
				},
				'[data-region="open-alert"]',
				(result) => self.go(el, ctx, { outbreak: result.outbreak.name })
			);
		});
		on('[data-action="add-source"]', () => self.pickCase(el, ctx, outbreak));
		on('[data-action="add-manual"]', () =>
			self.prompt(
				[
					{
						fieldname: "patient_code",
						fieldtype: "Data",
						label: __("Patient Code"),
						reqd: 1,
					},
					{
						fieldname: "onset_date",
						fieldtype: "Date",
						label: __("Onset Date"),
						reqd: 1,
					},
					{
						fieldname: "case_status",
						fieldtype: "Select",
						label: __("Case Status"),
						options: data.case_states,
						default: "Suspected",
					},
				],
				__("Add case by patient code"),
				(v) =>
					self.act(
						el,
						ctx,
						"add_case",
						{ outbreak, source_type: "Manual", ...v },
						'[data-region="detail-alert"]'
					)
			)
		);
		on('[data-action="remove-case"]', (event) =>
			self.prompt(
				[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
				__("Remove case from the outbreak"),
				(v) =>
					self.act(
						el,
						ctx,
						"remove_case",
						{ outbreak, row: event.currentTarget.dataset.name, reason: v.reason },
						'[data-region="detail-alert"]'
					)
			)
		);
		on('[data-action="add-action"]', () =>
			self.prompt(
				[
					{
						fieldname: "description",
						fieldtype: "Small Text",
						label: __("Action"),
						reqd: 1,
					},
					{
						fieldname: "responsible",
						fieldtype: "Link",
						options: "User",
						label: __("Responsible"),
						reqd: 1,
					},
					{ fieldname: "due_date", fieldtype: "Date", label: __("Due Date"), reqd: 1 },
				],
				__("Add control action"),
				(v) =>
					self.act(
						el,
						ctx,
						"add_action",
						{ outbreak, ...v },
						'[data-region="detail-alert"]'
					)
			)
		);
		on('[data-action="link-nc"]', () =>
			self.prompt(
				[
					{
						fieldname: "incident",
						fieldtype: "Link",
						options: "Incident CAPA",
						label: __("Incident"),
						reqd: 1,
					},
				],
				__("Link existing incident"),
				(v) =>
					self.act(
						el,
						ctx,
						"link_nc",
						{ outbreak, ...v },
						'[data-region="detail-alert"]'
					)
			)
		);
		on('[data-action="controlled"]', () =>
			self.act(el, ctx, "set_controlled", { outbreak }, '[data-region="detail-alert"]')
		);
		on('[data-action="end"]', () => {
			const open = ((data.current && data.current.incidents) || []).filter((i) => !i.closed);
			const fields = [
				{ fieldname: "summary", fieldtype: "Text", label: __("Summary"), reqd: 1 },
				{ fieldname: "end_date", fieldtype: "Date", label: __("End Date"), reqd: 1 },
				{
					fieldname: "external_report_ref",
					fieldtype: "Data",
					label: __("External Report Reference"),
				},
				...open.map((i) => ({
					fieldname: `reason_${i.row}`,
					fieldtype: "Small Text",
					label: __("Why incident {0} stays open", [i.incident]),
				})),
			];
			self.prompt(fields, __("End outbreak"), (v) => {
				const reasons = {};
				open.forEach((i) => {
					if (v[`reason_${i.row}`]) reasons[i.row] = v[`reason_${i.row}`];
				});
				self.act(
					el,
					ctx,
					"end_outbreak",
					{
						outbreak,
						summary: v.summary,
						end_date: v.end_date,
						external_report_ref: v.external_report_ref || "",
						open_reasons: JSON.stringify(reasons),
					},
					'[data-region="detail-alert"]'
				);
			});
		});
		on('[data-action="cancel-outbreak"]', () =>
			self.prompt(
				[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
				__("Cancel this outbreak investigation"),
				(v) =>
					self.act(
						el,
						ctx,
						"cancel_outbreak",
						{ outbreak, reason: v.reason },
						'[data-region="detail-alert"]',
						() => self.go(el, ctx, {})
					)
			)
		);
		on('[data-action="create-report"]', () => {
			const form = el.querySelector('[data-region="report-form"]');
			self.act(el, ctx, "create_report", self.values(form), '[data-region="report-alert"]');
		});
		on('[data-action="reported"]', (event) =>
			self.prompt(
				[
					{
						fieldname: "reported_on",
						fieldtype: "Datetime",
						label: __("Reported On"),
						reqd: 1,
					},
					{ fieldname: "report_ref", fieldtype: "Data", label: __("Report Reference") },
				],
				__("Record as reported"),
				(v) =>
					self.act(
						el,
						ctx,
						"record_reported",
						{ report: event.currentTarget.dataset.name, ...v },
						'[data-region="report-alert"]'
					)
			)
		);
		on('[data-action="cancel-report"]', (event) =>
			self.prompt(
				[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
				__("Cancel this report"),
				(v) =>
					self.act(
						el,
						ctx,
						"cancel_report",
						{ report: event.currentTarget.dataset.name, reason: v.reason },
						'[data-region="report-alert"]'
					)
			)
		);
		on('[data-action="retry"]', () => self.render(el, ctx));
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		const params = new URLSearchParams(window.location.search);
		try {
			const data = await ctx.get(TC_OD_OVERVIEW, {
				outbreak: params.get("outbreak") || "",
				alert: params.get("alert") || "",
				source_doctype: params.get("source_doctype") || "",
				source_name: params.get("source_name") || "",
			});
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr61.pageHtml(data, ctx.esc, false);
			TcKsnkScr61.bind(el, ctx, data);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
			TcKsnkScr61.bind(el, ctx, null);
		}
	},
};

window.TcKsnkScreens["o-dich"] = TcKsnkScr61;
window.TcKsnkScr61 = TcKsnkScr61;
