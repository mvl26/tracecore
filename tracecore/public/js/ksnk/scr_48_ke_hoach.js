/* global tracecore, TcKsnk */
// SCR-48 Kế hoạch KSNK năm, văn bản nội bộ, họp Hội đồng (FEAT-058; UC-41; FR-M11-04..08; BRU-ICP-004/005; A-131).
// Ba tab (Kế hoạch năm / Văn bản nội bộ / Họp Hội đồng) giữ trong query string `tab`; năm kế hoạch dùng bộ lọc `year`.
// Trạng thái luôn có chữ (Quá hạn / Sắp tới hạn / Đang làm / Hoàn thành…), không chỉ màu. Lỗi chặn hiện alert-error
// inline theo thứ tự kết quả → lý do → hành động (design.md §6). R13 ghi sổ (duyệt) ngay trên màn.

const TC_PLAN_STATUS = "tracecore.v1.ksnk_plan.status";
const TC_PLAN_APPROVE = "tracecore.v1.ksnk_plan.approve_plan";
const TC_PLAN_AMEND = "tracecore.v1.ksnk_plan.make_amendment";
const TC_PLAN_ACTIVITY = "tracecore.v1.ksnk_plan.update_activity";
const TC_PLAN_TABS = ["plan", "documents", "meeting"];
const TC_PLAN_PROGRESS = ["Planned", "In Progress", "Completed"];
const TC_PLAN_UNIT = { Percentage: " %", "Rate per 1000": " ‰" };

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr48 = {
	badgeClass(key) {
		return (
			{
				completed: "is-pass",
				effective: "is-pass",
				Met: "is-pass",
				overdue: "is-fail",
				"Not met": "is-fail",
				due_soon: "is-warn",
				review: "is-warn",
				in_progress: "is-info",
			}[key] || "is-neutral"
		);
	},

	badgeHtml(key, label, esc) {
		return `<span class="tc-ksnk-badge ${TcKsnkScr48.badgeClass(key)}">${esc(
			label || "—"
		)}</span>`;
	},

	date(value) {
		if (!value) return "—";
		const [y, m, d] = String(value).slice(0, 10).split("-");
		return `${d}/${m}/${y}`;
	},

	vnd(value) {
		return String(Math.round(Number(value) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
	},

	num(value, kind) {
		if (value === null || value === undefined || value === "") return "—";
		const fixed = (Math.round(Number(value) * 10) / 10).toFixed(1).replace(/\.0$/, "");
		const [whole, frac] = fixed.split(".");
		const text = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (frac ? `,${frac}` : "");
		return text + (TC_PLAN_UNIT[kind] || "");
	},

	target(row) {
		const sign = { "Higher is better": "≥ ", "Lower is better": "≤ " }[row.direction] || "";
		return sign + TcKsnkScr48.num(row.target, row.kind);
	},

	tab(ctx) {
		const tab = (ctx.filters && ctx.filters.tab) || "";
		return TC_PLAN_TABS.includes(tab) ? tab : "plan";
	},

	planStatus(plan) {
		if (!plan) return { key: "neutral", label: __("No plan") };
		if (plan.docstatus === 1)
			return { key: "completed", label: __("Approved", null, "IC Plan") };
		return { key: "neutral", label: __("Draft, waiting for approval") };
	},

	headHtml(data, esc) {
		const plan = data.plan;
		const status = TcKsnkScr48.planStatus(plan);
		const years = [data.year - 1, data.year, data.year + 1]
			.map(
				(y) =>
					`<option value="${y}"${y === data.year ? " selected" : ""}>${esc(y)}</option>`
			)
			.join("");
		return (
			`<div class="tc-ksnk-filters"><h3 class="tc-ksnk-plan-title">${esc(
				__("Infection control plan {0}", [data.year])
			)}` +
			`${
				plan ? ` <code class="tc-ksnk-tag">${esc(plan.name)}</code>` : ""
			} ${TcKsnkScr48.badgeHtml(status.key, status.label, esc)}</h3>` +
			`<label>${esc(
				__("Plan year")
			)}<select class="form-control" data-filter="year">${years}</select></label></div>`
		);
	},

	tabsHtml(data, active, esc) {
		const labels = {
			plan: __("Annual plan"),
			documents: __("Internal documents"),
			meeting: __("Committee meetings"),
		};
		const counts = { documents: data.documents_attention || 0 };
		return (
			`<div class="tc-ksnk-tabs" role="tablist">` +
			TC_PLAN_TABS.map((key) => {
				const on = key === active;
				const count = counts[key]
					? ` <span class="tc-ksnk-count">${esc(counts[key])}</span>`
					: "";
				return (
					`<button type="button" role="tab" class="tc-ksnk-tab${
						on ? " is-active" : ""
					}" ` +
					`aria-selected="${on}" data-tab="${key}">${esc(labels[key])}${count}</button>`
				);
			}).join("") +
			`</div>`
		);
	},

	infoHtml(plan, esc) {
		const total = plan.activities_total || 0;
		const done = plan.activities_completed || 0;
		const pct = total ? Math.round((done / total) * 100) : 0;
		const approved = plan.docstatus === 1;
		const note = approved
			? `<div class="tc-ksnk-alert is-info">${esc(
					__(
						"An approved plan is not edited directly; changes go through an amendment (Amend) approved again by the committee chair."
					)
			  )}</div>`
			: "";
		const pending = plan.pending_amendment
			? `<p class="tc-ksnk-note">${esc(__("Amendment waiting for approval"))}: ` +
			  `<a href="/app/ic-annual-plan/${encodeURIComponent(
					plan.pending_amendment
			  )}"><code class="tc-ksnk-code">${esc(plan.pending_amendment)}</code></a></p>`
			: "";
		return (
			`<section class="tc-ksnk-card"><dl class="tc-ksnk-facts">` +
			`<div><dt>${esc(__("Prepared by"))}</dt><dd>${esc(plan.created_by)}</dd></div>` +
			`<div><dt>${esc(__("Approval (submit)"))}</dt><dd>${esc(
				approved
					? `${plan.approved_by}, ${TcKsnkScr48.date(plan.approved_on)}`
					: __("Not approved yet")
			)}</dd></div>` +
			`<div><dt>${esc(__("Budget", null, "IC Plan"))}</dt><dd>${esc(
				TcKsnkScr48.vnd(plan.total_budget_vnd)
			)} VND</dd></div>` +
			`<div><dt>${esc(__("Activity progress"))}</dt><dd>${esc(
				__("{0}/{1} completed", [done, total])
			)}` +
			`<span class="tc-ksnk-progress" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" ` +
			`aria-valuemax="100"><span style="width: ${pct}%"></span></span></dd></div>` +
			`</dl>${note}${pending}</section>`
		);
	},

	indicatorsHtml(plan, esc) {
		const rows = plan.indicators
			.map((row) => {
				const status = row.latest_status || "";
				return (
					`<tr><td>${esc(row.indicator_name)}</td>` +
					`<td class="is-num">${esc(TcKsnkScr48.num(row.baseline, row.kind))}</td>` +
					`<td class="is-num">${esc(TcKsnkScr48.target(row))}</td>` +
					`<td class="is-num">${esc(TcKsnkScr48.num(row.latest, row.kind))}${
						row.latest_period
							? ` <span class="tc-ksnk-note">(${esc(row.latest_period)})</span>`
							: ""
					}</td>` +
					`<td>${
						status ? TcKsnkScr48.badgeHtml(status, __(status), esc) : "—"
					}</td></tr>`
				);
			})
			.join("");
		const body = rows
			? `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("Indicator", null, "IC Plan")
			  )}</th>` +
			  `<th scope="col" class="is-num">${esc(__("Baseline", null, "IC Plan"))}</th>` +
			  `<th scope="col" class="is-num">${esc(__("Target", null, "IC Plan"))}</th>` +
			  `<th scope="col" class="is-num">${esc(__("Latest", null, "IC Plan"))}</th>` +
			  `<th scope="col">${esc(
					__("Status")
			  )}</th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-note">${esc(__("No indicator in this plan."))}</p>`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Indicators and targets"))} ` +
			`<code class="tc-ksnk-tag">IC Plan Indicator</code></h3>${body}</section>`
		);
	},

	progressCell(row, esc) {
		if (!row.can_update) return esc(row.evidence || "—");
		const options = TC_PLAN_PROGRESS.map(
			(s) =>
				`<option value="${esc(s)}"${s === row.status ? " selected" : ""}>${esc(
					__(s, null, "IC Plan")
				)}</option>`
		).join("");
		return (
			`<div class="tc-ksnk-inline" data-row="${esc(row.name)}">` +
			`<select class="form-control" data-field="status" aria-label="${esc(
				__("Status")
			)}">${options}</select>` +
			`<input class="form-control" data-field="evidence" value="${esc(
				row.evidence
			)}" aria-label="${esc(__("Evidence", null, "IC Plan"))}">` +
			`<button type="button" class="btn btn-default btn-sm" data-action="save-activity" ` +
			`data-row="${esc(row.name)}">${esc(__("Save"))}</button></div>`
		);
	},

	activitiesHtml(plan, esc) {
		const self = TcKsnkScr48;
		const rows = plan.activities
			.map(
				(row) =>
					`<tr><td>${esc(row.activity)}</td><td>${esc(row.measure_group)}</td>` +
					`<td>${esc(row.responsible)}</td><td>${esc(row.department || "—")}</td>` +
					`<td>${esc(self.date(row.due_date))}</td><td class="is-num">${esc(
						self.vnd(row.budget_vnd)
					)}</td>` +
					`<td>${self.badgeHtml(
						row.display_status,
						row.status_label,
						esc
					)}</td><td>${self.progressCell(row, esc)}</td></tr>`
			)
			.join("");
		const overdue = plan.overdue
			? ` ${self.badgeHtml("overdue", __("{0} overdue", [plan.overdue]), esc)}`
			: "";
		const body = rows
			? `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("Activity", null, "IC Plan")
			  )}</th>` +
			  `<th scope="col">${esc(__("Measure Group"))}</th><th scope="col">${esc(
					__("Responsible", null, "IC Plan")
			  )}</th>` +
			  `<th scope="col">${esc(__("Department"))}</th><th scope="col">${esc(
					__("Due Date", null, "IC Plan")
			  )}</th>` +
			  `<th scope="col" class="is-num">${esc(
					__("Budget", null, "IC Plan")
			  )}</th><th scope="col">${esc(__("Status"))}</th>` +
			  `<th scope="col">${esc(
					__("Evidence", null, "IC Plan")
			  )}</th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-note">${esc(__("No activity in this plan."))}</p>`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Activities", null, "IC Plan"))} ` +
			`<code class="tc-ksnk-tag">IC Plan Activity</code>${overdue}</h3>${body}` +
			`<div data-region="activity-alert"></div></section>`
		);
	},

	documentsHtml(data, esc) {
		const self = TcKsnkScr48;
		const label = (row) => {
			if (row.status_key === "overdue") return __("Review overdue");
			if (row.status_key === "review")
				return __("{0} days left", [Math.max(row.days_left || 0, 0)]);
			return __(row.status);
		};
		const rows = data.documents
			.map(
				(row) =>
					`<tr><td><a href="/app/ic-procedure-document/${encodeURIComponent(
						row.name
					)}">` +
					`<code class="tc-ksnk-code">${esc(row.name)}</code></a></td>` +
					`<td>${esc(row.doc_code)}</td><td>${esc(row.title)}</td><td>v${esc(
						row.version_no
					)}</td>` +
					`<td>${esc(self.date(row.review_due))}</td><td>${self.badgeHtml(
						row.status_key,
						label(row),
						esc
					)}</td></tr>`
			)
			.join("");
		const body = rows
			? `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("Code", null, "IC Plan")
			  )}</th>` +
			  `<th scope="col">${esc(
					__("Document Code", null, "IC Plan")
			  )}</th><th scope="col">${esc(__("Title", null, "IC Plan"))}</th>` +
			  `<th scope="col">${esc(__("Version", null, "IC Plan"))}</th><th scope="col">${esc(
					__("Review Due", null, "IC Plan")
			  )}</th>` +
			  `<th scope="col">${esc(
					__("Status")
			  )}</th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-note">${esc(__("No internal document yet."))}</p>`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Internal document register"))} ` +
			`<code class="tc-ksnk-tag">QTK-</code></h3>${body}` +
			`<p class="tc-ksnk-note">${esc(
				__(
					"Documents within 30 days of the review date move to Review needed and R01 is notified."
				)
			)}</p>${TcKsnk.recordActions({
				doctype: "IC Procedure Document",
				can_create: data.can_create_document !== false,
				create_label: __("Add document"),
			})}</section>`
		);
	},

	meetingHtml(data, esc) {
		const self = TcKsnkScr48;
		const m = data.meeting;
		const latest = m
			? `<h3>${esc(__("Latest committee meeting"))} <code class="tc-ksnk-tag">${esc(
					m.name
			  )} · ${esc(self.date(m.meeting_date))}</code></h3>` +
			  `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("Conclusion → follow-up task")
			  )}</th>` +
			  `<th scope="col">${esc(
					__("Responsible", null, "IC Plan")
			  )}</th><th scope="col">${esc(__("Due Date", null, "IC Plan"))}</th>` +
			  `<th scope="col">${esc(__("Status"))}</th></tr></thead><tbody>` +
			  m.resolutions
					.map(
						(r) =>
							`<tr><td>${esc(r.content)}</td><td>${esc(r.responsible)}</td>` +
							`<td>${esc(self.date(r.due_date))}</td><td>${self.badgeHtml(
								r.display_status,
								r.status_label,
								esc
							)}</td></tr>`
					)
					.join("") +
			  `</tbody></table>`
			: `<h3>${esc(__("Latest committee meeting"))}</h3><p class="tc-ksnk-note">${esc(
					__("No committee meeting recorded yet.")
			  )}</p>`;
		const open = (data.open_resolutions || []).length
			? `<h3>${esc(
					__("Open conclusions from previous meetings")
			  )}</h3><ul class="tc-ksnk-list">` +
			  data.open_resolutions
					.map(
						(r) =>
							`<li><code class="tc-ksnk-code">${esc(r.meeting)}</code> ${esc(
								r.content
							)} — ` + `${esc(r.responsible)}, ${esc(self.date(r.due_date))}</li>`
					)
					.join("") +
			  `</ul>`
			: "";
		// biên bản họp đã ghi sổ: xem form, Hủy/sửa đổi theo quyền, In
		const record = m
			? TcKsnk.recordActions({
					doctype: "IC Committee Meeting",
					name: m.name,
					docstatus: 1,
					can_write: !!data.can_write_meeting,
			  })
			: "";
		return `<section class="tc-ksnk-card">${latest}${record}${open}</section>`;
	},

	actionsHtml(data, readOnly, esc) {
		const plan = data.plan;
		const buttons = [];
		if (plan) {
			const printUrl =
				`/printview?doctype=${encodeURIComponent(
					"IC Annual Plan"
				)}&name=${encodeURIComponent(plan.name)}` +
				`&format=${encodeURIComponent("TC IC Annual Summary")}`;
			buttons.push(
				`<a class="btn btn-primary" href="${esc(
					printUrl
				)}" target="_blank" rel="noopener">${esc(__("Create year-end summary"))}</a>`,
				`<a class="btn btn-default" href="/app/query-report/${encodeURIComponent(
					"IC Annual Summary"
				)}?plan=${encodeURIComponent(plan.name)}">${esc(__("Summary (Excel)"))}</a>`
			);
		}
		if (plan && data.can_approve) {
			buttons.push(
				`<button type="button" class="btn btn-primary" data-action="approve" data-name="${esc(
					plan.name
				)}">${esc(__("Approve (submit)"))}</button>`
			);
		}
		if (plan) {
			// luôn có lối mở form kế hoạch: Nháp sửa/ghi sổ, đã ghi sổ xem hoặc Hủy/sửa đổi; R13 chỉ xem
			buttons.push(
				TcKsnk.recordActions(
					{
						doctype: "IC Annual Plan",
						name: plan.name,
						docstatus: plan.docstatus,
						can_write: !readOnly && !!data.can_write_plan,
						can_print: false,
					},
					false
				)
			);
		}
		if (plan && !readOnly && data.can_amend && !plan.pending_amendment) {
			buttons.push(
				`<button type="button" class="btn btn-default" data-action="amend" data-name="${esc(
					plan.name
				)}">${esc(__("Create amendment (Amend)"))}</button>`
			);
		}
		if (!readOnly && data.can_create_plan) {
			buttons.push(
				`<a class="btn btn-default" href="/app/ic-annual-plan/new">${esc(
					__("Create annual plan")
				)}</a>`
			);
		}
		if (!readOnly && data.can_record_meeting) {
			buttons.push(
				`<a class="btn btn-default" href="/app/ic-committee-meeting/new">${esc(
					__("Record meeting minutes")
				)}</a>`
			);
		}
		return (
			`<div class="tc-ksnk-filters tc-ksnk-actions" data-region="actions">${buttons.join(
				" "
			)}` +
			`<span class="tc-ksnk-note">${esc(
				__("Responsible people are reminded 7 days before the due date and when overdue.")
			)}</span></div><div data-region="actions-alert"></div>`
		);
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

	pageHtml(data, ctx) {
		const self = TcKsnkScr48;
		const esc = ctx.esc;
		const tab = self.tab(ctx);
		let body;
		if (tab === "documents") body = self.documentsHtml(data, esc);
		else if (tab === "meeting") body = self.meetingHtml(data, esc);
		else if (!data.plan)
			body = ctx.state("empty", __("No annual plan for {0} yet.", [data.year]));
		else
			body =
				self.infoHtml(data.plan, esc) +
				self.indicatorsHtml(data.plan, esc) +
				self.activitiesHtml(data.plan, esc);
		return (
			self.headHtml(data, esc) +
			self.tabsHtml(data, tab, esc) +
			body +
			self.actionsHtml(data, ctx.readOnly, esc)
		);
	},

	activityValues(el, rowName) {
		const box = el.querySelector(`.tc-ksnk-inline[data-row="${rowName}"]`);
		return {
			status: box.querySelector('[data-field="status"]').value,
			evidence: box.querySelector('[data-field="evidence"]').value,
		};
	},

	bind(el, ctx, data) {
		const self = TcKsnkScr48;
		const esc = ctx.esc;
		const show = (region, html) => {
			const target = el.querySelector(`[data-region="${region}"]`);
			if (target) target.innerHTML = html;
		};
		el.querySelectorAll("[data-tab]").forEach((button) => {
			button.addEventListener("click", () => {
				ctx.setFilters({ tab: button.dataset.tab });
				self.paint(el, ctx, data);
			});
		});
		const year = el.querySelector('[data-filter="year"]');
		if (year) {
			year.addEventListener("change", () => {
				ctx.setFilters({ year: year.value });
				self.render(el, ctx);
			});
		}
		el.querySelectorAll("[data-action]").forEach((button) => {
			button.addEventListener("click", () => {
				const action = button.dataset.action;
				if (action === "retry") {
					self.render(el, ctx);
					return;
				}
				button.disabled = true;
				const call = {
					approve: { method: TC_PLAN_APPROVE, args: { name: button.dataset.name } },
					amend: { method: TC_PLAN_AMEND, args: { name: button.dataset.name } },
					"save-activity": {
						method: TC_PLAN_ACTIVITY,
						args: Object.assign(
							{ plan: data && data.plan && data.plan.name, row: button.dataset.row },
							self.activityValues(el, button.dataset.row)
						),
						region: "activity-alert",
					},
				}[action];
				tracecore.desk_call({
					method: call.method,
					args: call.args,
					// Sửa đổi chỉ mở form bản mới (chưa lưu gì): không hiện "đã lưu"
					success: action === "amend" ? false : undefined,
					on_ok: (result) => {
						if (!ctx.isCurrent()) return;
						if (action === "amend") {
							frappe.set_route("Form", "IC Annual Plan", result.name);
							return;
						}
						self.render(el, ctx);
					},
					on_block: (error) => {
						button.disabled = false;
						show(call.region || "actions-alert", self.blockHtml(error, esc));
					},
					on_fail: () => {
						button.disabled = false;
					},
				});
			});
		});
	},

	paint(el, ctx, data) {
		el.innerHTML = TcKsnkScr48.pageHtml(data, ctx);
		TcKsnkScr48.bind(el, ctx, data);
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_PLAN_STATUS, {
				year: (ctx.filters && ctx.filters.year) || "",
			});
			if (!ctx.isCurrent()) return;
			TcKsnkScr48.paint(el, ctx, data);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
			TcKsnkScr48.bind(el, ctx, null);
		}
	},
};

window.TcKsnkScreens["ke-hoach"] = TcKsnkScr48;
window.TcKsnkScr48 = TcKsnkScr48;
