/* global tracecore */
// SCR-53 Báo cáo tuân thủ & phản hồi khoa (FEAT-060; UC-45; FR-M12-08, FR-M12-09, FR-M12-11, FR-M12-14; BRU-AUD-005).
// Tổng hợp từ phiếu đã ghi sổ trong kỳ (tracecore.v1.audit.compliance_board): thẻ số, bảng theo mẫu × khoa với nhãn cỡ
// mẫu ("Chưa đủ cỡ mẫu", "Không tính"), phiếu gần đây, đề nghị mở NC (R01/R11: Mở NC / Bỏ qua có lý do). Xuất Excel/PDF
// qua Script Report "Compliance by Department". Trạng thái luôn có chữ, không chỉ màu. R13 chỉ thấy tổng hợp.

const TC_AUD_BOARD = "tracecore.v1.audit.compliance_board";
const TC_AUD_OPEN_NC = "tracecore.v1.audit.open_nc";
const TC_AUD_DISMISS_NC = "tracecore.v1.audit.dismiss_nc";
const TC_AUD_REPORT = "Compliance by Department";
const TC_AUD_TYPES = [
	"Hand Hygiene",
	"Standard Precautions - PPE",
	"Prevention Bundle",
	"Environmental Hygiene",
	"Infrastructure",
	"Outsourced Service",
	"Food Safety",
	"Quality Self-Assessment",
	"Other",
];
const TC_AUD_PROFESSIONS = [
	"Doctor",
	"Nurse",
	"Midwife",
	"Technician",
	"Orderly",
	"Student",
	"Other",
];

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr53 = {
	number(value) {
		if (value === null || value === undefined) return "—";
		const rounded = Math.round(Number(value) * 10) / 10;
		const [whole, fraction] = Math.abs(rounded).toFixed(1).split(".");
		return (rounded < 0 ? "-" : "") + whole + (fraction === "0" ? "" : `,${fraction}`);
	},

	percent(value) {
		return value === null || value === undefined
			? __("Not calculated")
			: `${TcKsnkScr53.number(value)} %`;
	},

	// FR-M12-11: dưới cỡ mẫu tối thiểu → nhãn chữ kèm n; mẫu số 0 → Không tính (BRU-RPT-001)
	noteBadge(row) {
		if (row.sample_note === "Not calculated")
			return { cls: "is-neutral", label: __("Not calculated") };
		if (row.sample_note === "Insufficient sample")
			return {
				cls: "is-neutral",
				label: __("Insufficient sample (n = {0}, needs {1})", [
					row.scored,
					row.min_sample,
				]),
			};
		return { cls: "", label: __("n = {0}", [row.scored]) };
	},

	resultBadge(row) {
		if (row.result === "Fail" && row.critical_failed)
			return { cls: "is-fail", label: __("Fail — critical item") };
		if (row.result === "Fail") return { cls: "is-fail", label: __("Fail") };
		if (row.result === "Pass") return { cls: "is-pass", label: __("Pass") };
		return { cls: "is-neutral", label: __("Not scored") };
	},

	month(filters) {
		return (filters.period || frappe.datetime.get_today().slice(0, 7)).slice(0, 7);
	},

	range(period) {
		const [year, month] = period.split("-").map(Number);
		const last = new Date(year, month, 0).getDate();
		return {
			from_date: `${period}-01`,
			to_date: `${period}-${String(last).padStart(2, "0")}`,
		};
	},

	badge(info, esc) {
		return info.cls
			? `<span class="tc-ksnk-badge ${info.cls}">${esc(info.label)}</span>`
			: esc(info.label);
	},

	cardsHtml(data, esc) {
		const cards = data.cards || {};
		const card = (cls, title, value, sub) =>
			`<div class="tc-ksnk-kpi ${cls}"><span>${esc(title)}</span><b>${esc(
				value
			)}</b><small>${esc(sub)}</small></div>`;
		return (
			`<div class="tc-ksnk-kpis">` +
			card(
				"is-warn",
				__("Pass rate, whole hospital"),
				TcKsnkScr53.percent(cards.pass_rate),
				__("{0}/{1} audits passed", [cards.passed || 0, cards.scored || 0])
			) +
			card(
				"is-info",
				__("Audits posted"),
				String(cards.posted || 0),
				__("{0} departments", [cards.departments || 0])
			) +
			card(
				"is-fail",
				__("Audits with a failed critical item"),
				String(cards.critical || 0),
				__("Non-conformance suggested")
			) +
			card(
				"is-pass",
				__("Feedback sent to departments"),
				cards.feedback_pct === null || cards.feedback_pct === undefined
					? "—"
					: `${cards.feedback_pct} %`,
				"FR-M12-08"
			) +
			`</div>`
		);
	},

	rowsHtml(data, esc) {
		const self = TcKsnkScr53;
		const body = (data.rows || [])
			.map(
				(row) =>
					`<tr><td><code class="tc-ksnk-code">${esc(row.template_code)}</code> ${esc(
						row.template_title || ""
					)}</td>` +
					`<td>${esc(row.department)}</td><td class="is-num">${esc(row.sessions)}</td>` +
					`<td class="is-num">${esc(row.passed)}</td><td class="is-num">${esc(
						self.percent(row.pass_rate)
					)}</td>` +
					`<td class="is-num">${esc(
						row.avg_score === null ? "—" : `${self.number(row.avg_score)} %`
					)}</td>` +
					`<td class="is-num">${esc(row.critical_failed)}</td><td>${self.badge(
						self.noteBadge(row),
						esc
					)}</td></tr>`
			)
			.join("");
		if (!body)
			return `<div class="tc-ksnk-state is-empty">${esc(
				__("No posted audit in this period.")
			)}</div>`;
		return (
			`<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(__("Template"))}</th>` +
			`<th scope="col">${esc(__("Department"))}</th><th scope="col" class="is-num">${esc(
				__("Audits")
			)}</th>` +
			`<th scope="col" class="is-num">${esc(
				__("Passed")
			)}</th><th scope="col" class="is-num">${esc(__("Pass Rate"))}</th>` +
			`<th scope="col" class="is-num">${esc(
				__("Average Score")
			)}</th><th scope="col" class="is-num">${esc(__("Critical Failed"))}</th>` +
			`<th scope="col">${esc(__("Note"))}</th></tr></thead><tbody>${body}</tbody></table>` +
			`<p class="tc-ksnk-note">${esc(
				__(
					"Pass rate = audits passed / audits with a result, from posted audits only. A failed critical item fails the audit whatever the score."
				)
			)}</p>`
		);
	},

	// FEAT-061 (FR-M12-05, BRU-AUD-002): tuân thủ vệ sinh tay theo cơ hội, theo nghề nghiệp và thời điểm; tỷ lệ đúng kỹ thuật
	// tách riêng; nhãn cỡ mẫu bằng chữ do server dựng
	hygieneHtml(hygiene, esc) {
		if (!hygiene || !hygiene.total) return "";
		const table = (title, rows, label) =>
			`<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(title)}</th>` +
			`<th scope="col" class="is-num">${esc(__("Opportunities"))}</th>` +
			`<th scope="col" class="is-num">${esc(__("With Action"))}</th>` +
			`<th scope="col" class="is-num">${esc(__("Compliance Rate"))}</th>` +
			`<th scope="col" class="is-num">${esc(__("Technique Rate"))}</th>` +
			`<th scope="col">${esc(__("Result"))}</th></tr></thead><tbody>` +
			rows
				.map(
					(row) =>
						`<tr><td>${esc(label(row))}</td><td class="is-num">${esc(
							row.total
						)}</td>` +
						`<td class="is-num">${esc(row.actioned)}</td>` +
						`<td class="is-num">${esc(TcKsnkScr53.percent(row.rate))}</td>` +
						`<td class="is-num">${esc(
							row.technique_rate === null || row.technique_rate === undefined
								? "—"
								: TcKsnkScr53.percent(row.technique_rate)
						)}</td><td>${esc(row.rate_label || "")}</td></tr>`
				)
				.join("") +
			`</tbody></table>`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(
				__("Hand hygiene compliance by opportunity")
			)}</h3>` +
			table(__("Observed Profession"), hygiene.profession || [], (row) =>
				__(row.key || "Other")
			) +
			table(__("Moment"), hygiene.moment || [], (row) => __("Moment {0}", [row.key])) +
			`<p class="tc-ksnk-note">${esc(
				__(
					"Compliance = opportunities with a hand rub or hand wash / all opportunities. Correct technique is counted apart and excludes opportunities not done."
				)
			)}</p></section>`
		);
	},

	recentHtml(data, esc) {
		const self = TcKsnkScr53;
		const body = (data.recent || [])
			.map(
				(row) =>
					`<tr><td><a href="/app/audit-session/${esc(
						row.name
					)}"><code class="tc-ksnk-code">${esc(row.name)}</code></a></td>` +
					`<td>${esc(row.department)}</td><td>${esc(
						row.template_title || row.template_code
					)}</td>` +
					`<td class="is-num">${esc(
						row.score_pct === null ? "—" : `${self.number(row.score_pct)} %`
					)}</td>` +
					`<td>${self.badge(self.resultBadge(row), esc)}</td></tr>`
			)
			.join("");
		if (!body)
			return `<div class="tc-ksnk-state is-empty">${esc(__("No audit to show."))}</div>`;
		return (
			`<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
				__("Audit Session")
			)}</th>` +
			`<th scope="col">${esc(__("Department"))}</th><th scope="col">${esc(
				__("Template")
			)}</th>` +
			`<th scope="col" class="is-num">${esc(__("Score"))}</th><th scope="col">${esc(
				__("Result")
			)}</th></tr></thead>` +
			`<tbody>${body}</tbody></table>`
		);
	},

	pendingHtml(data, esc, dismissing) {
		if (!data.can_decide) return "";
		const items = (data.pending || [])
			.map((row) => {
				const failed = (row.failed_items || [])
					.map((item) => `"${item.question}"${item.note ? ` (${item.note})` : ""}`)
					.join("; ");
				const reason =
					dismissing === row.name
						? `<label>${esc(
								__("Reason for not opening a non-conformance")
						  )}<input class="form-control" data-reason="${esc(
								row.name
						  )}"></label><button type="button" class="btn btn-default btn-sm" data-action="dismiss-confirm" data-session="${esc(
								row.name
						  )}">${esc(__("Confirm"))}</button>`
						: "";
				return (
					`<div class="tc-ksnk-alert is-error" role="alert"><b><code class="tc-ksnk-code">${esc(
						row.name
					)}</code> — ${esc(row.department)}:</b> ${esc(
						__("critical items failed: {0}", [failed])
					)}` +
					`<div class="tc-ksnk-actions"><button type="button" class="btn btn-danger btn-sm" data-action="open-nc" data-session="${esc(
						row.name
					)}">${esc(__("Open NC"))}</button>` +
					`<button type="button" class="btn btn-default btn-sm" data-action="dismiss" data-session="${esc(
						row.name
					)}">${esc(__("Dismiss (with reason)"))}</button></div>${reason}</div>`
				);
			})
			.join("");
		return (
			`<section class="tc-ksnk-card"><h3>${esc(
				__("Suggested non-conformances")
			)} <code class="tc-ksnk-code">Incident CAPA · Compliance</code></h3>` +
			(items ||
				`<div class="tc-ksnk-state is-empty">${esc(
					__("No audit waits for a decision.")
				)}</div>`) +
			`<div class="tc-ksnk-alert is-info" role="status">${esc(
				__(
					"Feedback (score and failed items) is sent to the head and network members of the department on posting."
				)
			)}</div></section>`
		);
	},

	filtersHtml(filters, esc) {
		const select = (key, values, label) =>
			`<label>${esc(
				label
			)}<select class="form-control" data-filter="${key}"><option value="">${esc(
				__("All")
			)}</option>` +
			values
				.map(
					(v) =>
						`<option value="${esc(v)}"${filters[key] === v ? " selected" : ""}>${esc(
							__(v)
						)}</option>`
				)
				.join("") +
			`</select></label>`;
		return (
			`<div class="tc-ksnk-filters">${select(
				"audit_type",
				TC_AUD_TYPES,
				__("Audit Type")
			)}` +
			`<label>${esc(
				__("Period")
			)}<input type="month" class="form-control" data-filter="period" value="${esc(
				TcKsnkScr53.month(filters)
			)}"></label>` +
			`${select("profession", TC_AUD_PROFESSIONS, __("Observed Profession"))}` +
			`<button type="button" class="btn btn-default" data-action="export">${esc(
				__("Export Excel / PDF")
			)}</button></div>`
		);
	},

	call(method, args) {
		return new Promise((resolve) => {
			tracecore.desk_call({
				method,
				args,
				success: method === TC_AUD_OPEN_NC ? false : undefined, // mở NC tự báo mã NC vừa tạo
				on_ok: (result) => resolve(result),
				on_block: (error) => resolve({ ok: false, error }),
				on_fail: () =>
					resolve({
						ok: false,
						error: { title: __("Not saved"), reason: "", action: __("Retry.") },
					}),
			});
		});
	},

	async render(el, ctx, state = {}) {
		const self = TcKsnkScr53;
		const esc = ctx.esc;
		const filters = ctx.filters;
		const local = (state.filters = state.filters || { audit_type: "", profession: "" });
		el.innerHTML = ctx.state("loading");
		let data;
		try {
			data = await ctx.get(TC_AUD_BOARD, {
				...self.range(self.month(filters)),
				audit_type: local.audit_type || undefined,
				profession: local.profession || undefined,
			});
		} catch (error) {
			if (ctx.isCurrent()) el.innerHTML = ctx.state("error", (error && error.message) || "");
			return;
		}
		if (!ctx.isCurrent()) return;
		const error = state.error
			? `<div class="tc-ksnk-alert is-error" role="alert"><b>${esc(
					state.error.title || ""
			  )}</b> ${esc(state.error.reason || "")} ${esc(state.error.action || "")}</div>`
			: "";
		el.innerHTML =
			error +
			self.filtersHtml({ ...local, period: filters.period }, esc) +
			self.cardsHtml(data, esc) +
			`<section class="tc-ksnk-card"><h3>${esc(
				__("Compliance by template and department")
			)}</h3>${self.rowsHtml(data, esc)}</section>` +
			self.hygieneHtml(data.hand_hygiene, esc) +
			`<div class="tc-ksnk-grid">` +
			`<section class="tc-ksnk-card"><h3>${esc(__("Recent audits"))}</h3>${self.recentHtml(
				data,
				esc
			)}</section>` +
			self.pendingHtml(data, esc, state.dismissing) +
			`</div>`;
		const rerender = (next = {}) => self.render(el, ctx, { filters: local, ...next });
		el.onchange = (event) => {
			const input = event.target.closest("[data-filter]");
			if (!input) return;
			if (input.dataset.filter === "period") ctx.setFilters({ period: input.value });
			else local[input.dataset.filter] = input.value;
			rerender();
		};
		el.onclick = async (event) => {
			const button = event.target.closest("[data-action]");
			if (!button) return;
			const action = button.dataset.action;
			const session = button.dataset.session;
			if (action === "retry") return rerender();
			if (action === "export")
				return frappe.set_route("query-report", TC_AUD_REPORT, {
					...self.range(self.month(filters)),
					audit_type: local.audit_type,
					profession: local.profession,
				});
			if (action === "dismiss") return rerender({ dismissing: session });
			let res = null;
			if (action === "open-nc") res = await self.call(TC_AUD_OPEN_NC, { session });
			if (action === "dismiss-confirm") {
				const box = el.querySelector(`[data-reason="${session}"]`);
				res = await self.call(TC_AUD_DISMISS_NC, {
					session,
					reason: box ? box.value : "",
				});
			}
			if (!res || !ctx.isCurrent()) return;
			if (res.ok === false)
				return rerender({
					error: res.error,
					dismissing: action === "dismiss-confirm" ? session : null,
				});
			if (res.incident)
				frappe.show_alert({
					message: __("Non-conformance {0} opened", [res.incident]),
					indicator: "green",
				});
			rerender();
		};
	},
};

window.TcKsnkScreens["tuan-thu"] = TcKsnkScr53;
window.TcKsnkScr53 = TcKsnkScr53;
