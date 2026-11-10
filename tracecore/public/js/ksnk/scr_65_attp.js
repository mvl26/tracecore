/* global tracecore */
// SCR-65 An toàn thực phẩm & truyền thông người bệnh — view WEB trong Page tc-ksnk (FEAT-073; UC-56; FR-M17-01..06;
// BRU-FS-001..002; A-131, A-151). R01/R11: sự cố nghi ngộ độc chờ quyết định (mở NC / điều tra ổ dịch hoặc bỏ qua có lý
// do), hạn khám sức khỏe người chế biến (chỉ Đủ/Không đủ), buổi truyền thông theo quý, kết quả giám sát bếp ăn theo đơn
// vị, mẫu thực phẩm; R01 ban hành / thu hồi tài liệu truyền thông, in QR (URL cố định theo mã). R13 chỉ số liệu tổng hợp.
// Ghi người chế biến, sự cố, buổi truyền thông trên Desk form. Lỗi chặn = alert inline; trạng thái luôn có chữ.

const TC_FS_OVERVIEW = "tracecore.v1.food_safety.overview";
const TC_FS_OPEN_NC = "tracecore.v1.food_safety.open_nc";
const TC_FS_DISMISS_NC = "tracecore.v1.food_safety.dismiss_nc";
const TC_FS_DISMISS_OUTBREAK = "tracecore.v1.food_safety.dismiss_outbreak";
const TC_FS_PREFILL = "tracecore.v1.food_safety.outbreak_prefill";
const TC_FS_PUBLISH = "tracecore.v1.food_safety.publish_material";
const TC_FS_WITHDRAW = "tracecore.v1.food_safety.withdraw_material";
const TC_FS_REPORT = "/app/query-report/Food Safety and Communication by Quarter";

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr65 = {
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

	num(value) {
		if (value === null || value === undefined || value === "") return "—";
		const [whole, frac] = String(Number(value)).split(".");
		const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
		return frac ? `${grouped},${frac}` : grouped;
	},

	badge(cls, label, esc) {
		return `<span class="tc-ksnk-badge is-${cls}">${esc(label)}</span>`;
	},

	opt(value, context) {
		return value ? __(value, null, context) : "—";
	},

	handlerBadge(r, esc) {
		const self = TcKsnkScr65;
		const state =
			r.state === "Overdue"
				? self.badge("fail", `✕ ${__("Overdue")}`, esc)
				: r.state === "Due Soon"
				? self.badge("warn", __("{0} days left", [r.days_left]), esc)
				: self.badge("pass", `✓ ${__("Valid", null, "Food Handler Health Check")}`, esc);
		const fit =
			r.fit_for_work === "Unfit"
				? ` ${self.badge("fail", __("Unfit", null, "Food Handler Health Check"), esc)}`
				: "";
		return state + fit;
	},

	resultBadge(result, esc) {
		const self = TcKsnkScr65;
		if (result === "Pass") return self.badge("pass", `✓ ${__("Pass")}`, esc);
		if (result === "Fail") return self.badge("fail", `✕ ${__("Fail")}`, esc);
		return self.badge("neutral", __("No result"), esc);
	},

	// POST @idempotent: khóa giữ nguyên khi bấm lại cùng dữ liệu (thử lại sau lỗi mạng)
	post(method, args, handlers) {
		const self = TcKsnkScr65;
		const sig = JSON.stringify([method, args]);
		if (!self.pending || self.pending.sig !== sig)
			self.pending = { sig, key: self.uuid(), ts: self.iso() };
		const pending = self.pending;
		const handle = (result) => {
			self.pending = null;
			if (result && result.ok === false) return handlers.on_block(result.error || {});
			handlers.on_ok(result || {});
		};
		frappe.call({
			method,
			args: { ...args, client_ts: pending.ts },
			headers: { "X-Idempotency-Key": pending.key },
			callback: (response) => handle(response.message),
			error: (xhr) => {
				const body = xhr && xhr.responseJSON && xhr.responseJSON.message;
				if (body && body.ok === false) return handle(body);
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

	kpisHtml(data, esc) {
		const k = data.kpis || {};
		const q = data.quarter || {};
		const tile = (cls, label, value) =>
			`<div class="tc-ksnk-kpi${cls ? ` is-${cls}` : ""}"><span>${esc(
				label
			)}</span><strong>${esc(value)}</strong></div>`;
		return (
			`<div class="tc-ksnk-kpis">` +
			tile(
				k.handlers_overdue ? "fail" : "",
				__("Food handlers overdue for a health check"),
				`${k.handlers_overdue || 0}/${k.handlers_total || 0}`
			) +
			tile(
				k.handlers_due_soon ? "warn" : "",
				__("Due within 30 days"),
				k.handlers_due_soon || 0
			) +
			tile(
				k.events_pending ? "fail" : "",
				__("Food poisoning events to decide"),
				k.events_pending || 0
			) +
			tile(
				"",
				__("Education sessions {0}", [q.label || ""]),
				`${q.sessions || 0} · ${q.attendees || 0}`
			) +
			`</div>`
		);
	},

	eventsHtml(data, esc) {
		const self = TcKsnkScr65;
		return (data.pending_events || [])
			.map((r) => {
				const actions = [];
				if (data.can_decide && r.nc_status === "Suggested")
					actions.push(
						`<button type="button" class="btn btn-danger btn-sm" data-action="open-nc" data-name="${esc(
							r.name
						)}">${esc(__("Open NC"))}</button>`,
						`<button type="button" class="btn btn-default btn-sm" data-action="dismiss-nc" data-name="${esc(
							r.name
						)}">${esc(__("No NC needed"))}</button>`
					);
				if (data.can_decide && r.outbreak_status === "Suggested") {
					if (data.outbreak_ready)
						actions.push(
							`<button type="button" class="btn btn-default btn-sm" data-action="open-outbreak" data-name="${esc(
								r.name
							)}">${esc(__("Open outbreak investigation"))}</button>`
						);
					actions.push(
						`<button type="button" class="btn btn-default btn-sm" data-action="dismiss-outbreak" data-name="${esc(
							r.name
						)}">${esc(__("No investigation needed"))}</button>`
					);
				}
				const outbreak =
					r.outbreak_status === "Suggested"
						? __("At or above {0} people: an outbreak investigation is suggested.", [
								r.threshold_applied,
						  ])
						: r.threshold_applied
						? ""
						: __("No people threshold set: only a non-conformance is suggested.");
				return `<div class="tc-ksnk-alert" role="alert" data-region="ev-${esc(r.name)}">
					<strong>${esc(__("{0} — suspected food poisoning:", [r.name]))}</strong>
					${esc(
						__("{0} people affected at {1} on {2}; suspected food: {3}.", [
							r.affected_count,
							r.location,
							self.date(r.event_date),
							r.suspected_food || "—",
						])
					)}
					<div>${esc(__("Infection control and the supervisors were notified."))} ${esc(outbreak)}</div>
					${actions.length ? `<div class="tc-ksnk-actions">${actions.join("")}</div>` : ""}
					<div data-region="ev-alert"></div></div>`;
			})
			.join("");
	},

	handlersHtml(data, esc) {
		const self = TcKsnkScr65;
		const rows = data.handlers || [];
		const body = rows.length
			? rows
					.map(
						(r) => `<tr><td>${esc(r.full_name)}</td><td>${esc(r.unit || "—")}</td>
				<td>${esc(self.date(r.checked_on))}</td><td>${esc(self.date(r.next_due))}</td>
				<td>${self.handlerBadge(r, esc)}</td></tr>`
					)
					.join("")
			: `<tr><td colspan="5">${esc(__("No health checks recorded yet."))}</td></tr>`;
		const overdue = (data.overdue_by_unit || [])
			.map(
				(group) =>
					`<li>${esc(group.unit)}: ${esc(
						group.handlers.map((h) => h.full_name).join(", ")
					)}</li>`
			)
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Food handler health checks")
		)} <span class="tc-ksnk-code">Food Handler Health Check · SKTP-</span></h3>
			<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Food Handler"))}</th><th>${esc(
			__("Unit")
		)}</th><th>${esc(__("Last check"))}</th><th>${esc(__("Next Check Due"))}</th><th>${esc(
			__("Status")
		)}</th></tr></thead><tbody>${body}</tbody></table>
			${
				overdue
					? `<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
							__("Overdue by unit")
					  )}</strong><ul>${overdue}</ul></div>`
					: ""
			}
			<p class="tc-ksnk-note">${esc(
				__(
					"Only the conclusion (fit or unfit) and the next due date are kept; there is no field for a diagnosis or test result."
				)
			)} <a href="/app/food-handler-health-check/new">${esc(
			__("Record a health check")
		)}</a></p>
			</section>`;
	},

	sessionsHtml(data, esc) {
		const self = TcKsnkScr65;
		const q = data.quarter || {};
		const rows = data.sessions || [];
		const body = rows.length
			? rows
					.map(
						(r) => `<tr><td>${esc(self.date(r.session_date))}</td><td>${esc(
							r.department_name || r.department || "—"
						)}</td>
				<td>${esc(self.opt(r.audience, "IC Education Session"))}</td><td>${esc(r.title)}</td>
				<td class="is-num">${esc(self.num(r.attendee_count))}</td></tr>`
					)
					.join("")
			: `<tr><td colspan="5">${esc(__("No education sessions recorded yet."))}</td></tr>`;
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Infection control education sessions")
		)} <span class="tc-ksnk-code">IC Education Session · GDS-</span></h3>
			<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Date"))}</th><th>${esc(
			__("Department")
		)}</th><th>${esc(__("Audience"))}</th><th>${esc(
			__("Subject")
		)}</th><th class="is-num">${esc(
			__("Attendees", null, "IC Education Session")
		)}</th></tr></thead><tbody>${body}</tbody></table>
			<p class="tc-ksnk-note">${esc(
				__("{0}: {1} sessions · {2} attendees", [
					q.label || "",
					q.sessions || 0,
					q.attendees || 0,
				])
			)} · <a href="${esc(TC_FS_REPORT)}">${esc(
			__("Quarterly report")
		)}</a> · <a href="/app/ic-education-session/new">${esc(
			__("Record a session")
		)}</a></p></section>`;
	},

	quarterHtml(data, esc) {
		const self = TcKsnkScr65;
		const q = data.quarter || {};
		const body = (q.rows || [])
			.map(
				(r) =>
					`<tr><td>${esc(self.opt(r.audience, "IC Education Session"))}</td><td>${esc(
						self.opt(r.topic)
					)}</td><td class="is-num">${esc(
						self.num(r.sessions)
					)}</td><td class="is-num">${esc(self.num(r.attendees))}</td></tr>`
			)
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("{0}: {1} sessions · {2} attendees", [
				q.label || "",
				q.sessions || 0,
				q.attendees || 0,
			])
		)}</h3>${
			body
				? `<table class="tc-ksnk-table"><thead><tr><th>${esc(
						__("Audience")
				  )}</th><th>${esc(__("Topic"))}</th><th class="is-num">${esc(
						__("Sessions")
				  )}</th><th class="is-num">${esc(
						__("Attendees", null, "IC Education Session")
				  )}</th></tr></thead><tbody>${body}</tbody></table>`
				: `<p class="tc-ksnk-state">${esc(__("No education sessions this quarter."))}</p>`
		}</section>`;
	},

	foodHtml(data, esc) {
		const self = TcKsnkScr65;
		const audits = (data.food_audits || [])
			.map(
				(r) => `<tr><td>${esc(r.unit || "—")}</td><td>${esc(self.date(r.last_date))}</td>
				<td>${self.resultBadge(r.last_result, esc)} ${esc(
					r.last_score === null || r.last_score === undefined
						? ""
						: `${self.num(r.last_score)} %`
				)}</td><td class="is-num">${esc(`${r.passed}/${r.total}`)}</td></tr>`
			)
			.join("");
		const samples = (data.food_samples || [])
			.map(
				(r) =>
					`<tr><td><span class="tc-ksnk-code">${esc(r.name)}</span></td><td>${esc(
						r.environment_zone_name || "—"
					)}</td><td>${esc(self.date(r.sampled_on))}</td><td class="is-num">${esc(
						`${self.num(r.result_value)} ${r.unit || ""}`
					)}</td><td>${self.resultBadge(r.result, esc)}</td></tr>`
			)
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(__("Kitchen and catering audits"))}</h3>
			${
				audits
					? `<table class="tc-ksnk-table"><thead><tr><th>${esc(
							__("Unit")
					  )}</th><th>${esc(__("Last audit"))}</th><th>${esc(
							__("Result")
					  )}</th><th class="is-num">${esc(
							__("Passed (90 days)")
					  )}</th></tr></thead><tbody>${audits}</tbody></table>`
					: `<p class="tc-ksnk-state">${esc(
							__("No food safety audit in the last 90 days.")
					  )}</p>`
			}
			<h3>${esc(__("Food samples"))}</h3>
			${
				samples
					? `<table class="tc-ksnk-table"><thead><tr><th>${esc(
							__("Code")
					  )}</th><th>${esc(__("Zone"))}</th><th>${esc(
							__("Sampled On")
					  )}</th><th class="is-num">${esc(__("Result Value"))}</th><th>${esc(
							__("Result")
					  )}</th></tr></thead><tbody>${samples}</tbody></table>`
					: `<p class="tc-ksnk-state">${esc(__("No food samples yet."))}</p>`
			}
			<div class="tc-ksnk-alert is-info" role="note">${esc(
				__(
					"Kitchen audits use the infection control audit template of type Food Safety; food samples are handled like environmental samples."
				)
			)} <a href="/app/audit-template?audit_type=Food%20Safety">${esc(
			__("Audit templates")
		)}</a> · <a
				href="/app/environmental-sample?sample_type=Food">${esc(__("Food samples"))}</a></div></section>`;
	},

	materialsHtml(data, esc) {
		const self = TcKsnkScr65;
		const rows = data.materials || [];
		const items = rows
			.map((r) => {
				const current = r.status === "Effective" || r.status === "Review Needed";
				const status = current
					? self.badge("pass", __("Current v{0}", [r.version_no]), esc)
					: r.status === "Draft"
					? self.badge("neutral", __("Draft"), esc)
					: self.badge("fail", __("Withdrawn"), esc);
				const note = current
					? __(
							"The QR code always opens the current version; print and post it in the ward."
					  ) + (r.issued_on ? ` ${__("Issued on {0}.", [self.date(r.issued_on)])}` : "")
					: r.status === "Draft"
					? __("Not issued — the QR code is not active yet.")
					: __("Withdrawn — the QR code shows that the document was withdrawn.");
				const actions = [];
				if (current)
					actions.push(
						`<button type="button" class="btn btn-default" data-action="print-qr" data-name="${esc(
							r.name
						)}">${esc(__("Print QR"))}</button>`
					);
				if (data.can_publish && r.status === "Draft")
					actions.push(
						`<button type="button" class="btn btn-primary" data-action="publish" data-name="${esc(
							r.name
						)}">${esc(__("Issue", null, "IC Procedure Document"))}</button>`
					);
				if (data.can_publish && current)
					actions.push(
						`<button type="button" class="btn btn-default" data-action="withdraw" data-name="${esc(
							r.name
						)}">${esc(__("Withdraw"))}</button>`
					);
				return `<div class="tc-ksnk-material" data-region="doc-${esc(r.name)}">
					<img class="tc-ksnk-qr" src="${esc(r.qr)}" alt="${esc(__("QR code of {0}", [r.title]))}">
					<div><strong>${esc(r.title)}</strong> ${status} <span class="tc-ksnk-code">${esc(
					r.doc_code
				)}</span><div>${esc(note)}</div><div data-region="doc-alert"></div></div>
					<div class="tc-ksnk-actions">${actions.join("")}</div></div>`;
			})
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Communication materials for patients and families")
		)}</h3>${
			items ||
			`<p class="tc-ksnk-state">${esc(
				__(
					"No communication material yet. Add one as a procedure document of type Communication Material."
				)
			)}</p>`
		}<p class="tc-ksnk-note"><a href="/app/ic-procedure-document/new?doc_type=Communication%20Material&status=Draft">${esc(
			__("New communication material")
		)}</a></p></section>`;
	},

	pageHtml(data, esc) {
		const self = TcKsnkScr65;
		if (data.summary_only) return self.kpisHtml(data, esc) + self.quarterHtml(data, esc);
		return (
			self.kpisHtml(data, esc) +
			self.eventsHtml(data, esc) +
			`<div class="tc-ksnk-cols"><div>${self.handlersHtml(data, esc)}${self.foodHtml(
				data,
				esc
			)}</div><div>${self.sessionsHtml(data, esc)}</div></div>` +
			self.materialsHtml(data, esc)
		);
	},

	askReason(title, done) {
		frappe.prompt(
			[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
			(values) => done(values.reason),
			title,
			__("Confirm")
		);
	},

	printQr(data, name) {
		const doc = (data.materials || []).find((row) => row.name === name);
		if (!doc) return;
		const esc = frappe.utils.escape_html;
		const win = window.open("", "_blank");
		if (!win) return;
		win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(
			doc.title
		)}</title><link rel="stylesheet" href="/assets/tracecore/css/tokens.css"></head>
			<body class="tc-ksnk-qr-print"><h1>${esc(doc.title)}</h1><img src="${esc(doc.qr)}" alt="">
			<p>${esc(__("Scan to read the current version"))}</p><p class="tc-ksnk-code">${esc(
			doc.url
		)}</p></body></html>`);
		win.document.close();
		win.focus();
		win.print();
	},

	async openOutbreak(name) {
		const prefill = await frappe.xcall(TC_FS_PREFILL, { event: name });
		frappe.new_doc("Outbreak Investigation", prefill);
	},

	bind(el, ctx, data) {
		const self = TcKsnkScr65;
		el.querySelectorAll("[data-action]").forEach((button) =>
			button.addEventListener("click", () => {
				const action = button.dataset.action;
				const name = button.dataset.name;
				const box = button.closest("[data-region]");
				const alert =
					box &&
					box.querySelector('[data-region="ev-alert"], [data-region="doc-alert"]');
				const handlers = {
					on_ok: (result) => {
						if (action === "open-nc" && result.result)
							frappe.show_alert({
								message: __("Incident {0} opened.", [result.result]),
								indicator: "green",
							});
						if (ctx.isCurrent()) self.render(el, ctx);
					},
					on_block: (error) => {
						if (alert) alert.innerHTML = self.blockHtml(error, ctx.esc);
					},
				};
				if (action === "retry") return self.render(el, ctx);
				if (action === "print-qr") return self.printQr(data, name);
				if (action === "open-outbreak") return self.openOutbreak(name);
				if (action === "open-nc")
					return self.post(TC_FS_OPEN_NC, { event: name }, handlers);
				if (action === "publish") return self.post(TC_FS_PUBLISH, { name }, handlers);
				if (action === "dismiss-nc")
					return self.askReason(__("No non-conformance needed"), (reason) =>
						self.post(TC_FS_DISMISS_NC, { event: name, reason }, handlers)
					);
				if (action === "dismiss-outbreak")
					return self.askReason(__("No outbreak investigation needed"), (reason) =>
						self.post(TC_FS_DISMISS_OUTBREAK, { event: name, reason }, handlers)
					);
				if (action === "withdraw")
					return self.askReason(__("Withdraw the document"), (reason) =>
						self.post(TC_FS_WITHDRAW, { name, reason }, handlers)
					);
			})
		);
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_FS_OVERVIEW, {});
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr65.pageHtml(data, ctx.esc);
			TcKsnkScr65.bind(el, ctx, data);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkScreens.attp = TcKsnkScr65;
window.TcKsnkScr65 = TcKsnkScr65;
