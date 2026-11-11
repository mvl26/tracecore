/* global tracecore, TcKsnk */
// SCR-62 Vệ sinh môi trường & cơ sở hạ tầng — view WEB trong Page tc-ksnk (FEAT-070; UC-54; FR-M15-01..07;
// BRU-ENV-001..003; A-148 f). Tab: Tổng quan · Vùng vệ sinh · Mẫu môi trường · Hạ tầng · Ngưỡng & kế hoạch. R01/R11 quyết
// định NC Environment của mẫu Không đạt (mở NC hoặc bỏ qua có lý do); R02 chỉ xem; R13 chỉ số liệu tổng hợp. Tạo/sửa
// vùng, ngưỡng, kế hoạch, mẫu trên Desk form. Lỗi chặn = alert inline (kết quả → lý do → hành động); trạng thái luôn có chữ.

const TC_ENV_OVERVIEW = "tracecore.v1.environment.overview";
const TC_ENV_OPEN_NC = "tracecore.v1.environment.open_nc";
const TC_ENV_DISMISS_NC = "tracecore.v1.environment.dismiss_nc";
const TC_ENV_TABS = ["overview", "zones", "samples", "infra", "limits"];

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr62 = {
	tab: "overview",

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

	month(value) {
		const [y, m] = String(value || "").split("-");
		return y && m ? `${m}/${y}` : "—";
	},

	num(value) {
		if (value === null || value === undefined || value === "") return "—";
		const [whole, frac] = String(Number(value)).split(".");
		const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
		return frac ? `${grouped},${frac}` : grouped;
	},

	pct(passed, total) {
		return total ? `${TcKsnkScr62.num(Math.round((passed * 1000) / total) / 10)} %` : "—";
	},

	badge(cls, label, esc) {
		return `<span class="tc-ksnk-badge is-${cls}">${esc(label)}</span>`;
	},

	resultBadge(result, esc) {
		if (result === "Pass") return TcKsnkScr62.badge("pass", `✓ ${__("Pass")}`, esc);
		if (result === "Fail") return TcKsnkScr62.badge("fail", `✕ ${__("Fail")}`, esc);
		return TcKsnkScr62.badge("neutral", __("No result"), esc);
	},

	desk(doctype, name, label, esc) {
		const slug = frappe.router.slug(doctype);
		return `<a href="/app/${slug}/${encodeURIComponent(
			name
		)}"><span class="tc-ksnk-code">${esc(label || name)}</span></a>`;
	},

	// Cờ quyền theo DocType do RPC trả (A-131); thiếu cờ = chỉ xem
	perm(data, doctype) {
		return ((data && data.perms) || {})[doctype] || {};
	},

	// Hàng thao tác của một mẫu đã ghi sổ: xem/hủy/sửa đổi theo quyền, In; thêm mẫu mới ở nút "Ghi kết quả"
	sampleActions(data, row, extra) {
		const perm = TcKsnkScr62.perm(data, "Environmental Sample");
		return TcKsnk.recordActions(
			{
				doctype: "Environmental Sample",
				name: row.name,
				docstatus: 1,
				can_write: perm.write,
				can_create: false,
				extra: extra || [],
			},
			false
		);
	},

	// POST @idempotent: khóa giữ nguyên khi bấm lại cùng dữ liệu (thử lại sau lỗi mạng)
	post(method, args, handlers) {
		const sig = JSON.stringify([method, args]);
		if (!TcKsnkScr62.pending || TcKsnkScr62.pending.sig !== sig)
			TcKsnkScr62.pending = { sig, key: TcKsnkScr62.uuid(), ts: TcKsnkScr62.iso() };
		const pending = TcKsnkScr62.pending;
		const handle = (result) => {
			TcKsnkScr62.pending = null;
			if (result && result.ok === false) return handlers.on_block(result.error || {});
			tracecore.saved_notice(handlers.success);
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
		const self = TcKsnkScr62;
		const tile = (cls, label, value) =>
			`<div class="tc-ksnk-kpi${cls ? ` is-${cls}` : ""}"><span>${esc(
				label
			)}</span><strong>${esc(value)}</strong></div>`;
		return (
			`<div class="tc-ksnk-kpis">` +
			tile(
				"pass",
				__("High-risk surfaces passed"),
				`${self.pct(k.high_risk_passed, k.high_risk_total)} (${k.high_risk_passed || 0}/${
					k.high_risk_total || 0
				})`
			) +
			tile(
				k.samples_failed ? "fail" : "",
				__("Environmental samples failed"),
				`${k.samples_failed || 0}/${k.samples_total || 0}`
			) +
			tile(
				k.samples_overdue ? "warn" : "",
				__("Samples behind plan"),
				k.samples_overdue || 0
			) +
			tile(
				k.infra_due_soon || k.infra_overdue ? "warn" : "",
				__("Infrastructure due in 7 days / overdue"),
				`${k.infra_due_soon || 0} / ${k.infra_overdue || 0}`
			) +
			`</div>`
		);
	},

	ratesHtml(data, esc) {
		const self = TcKsnkScr62;
		const rates = data.rates || {};
		const table = (title, rows) => {
			const body = (rows || [])
				.map(
					(r) =>
						`<tr><td>${esc(r.label || r.key)}</td><td class="is-num">${esc(
							self.num(r.passed)
						)}/${esc(self.num(r.total))}</td><td class="is-num">${esc(
							self.pct(r.passed, r.total)
						)}</td></tr>`
				)
				.join("");
			return `<section class="tc-ksnk-card"><h3>${esc(title)}</h3>${
				body
					? `<table class="tc-ksnk-table"><thead><tr><th>${esc(
							__("Group")
					  )}</th><th>${esc(__("Passed / audits"))}</th><th>${esc(
							__("Rate")
					  )}</th></tr></thead><tbody>${body}</tbody></table>`
					: `<p class="tc-ksnk-state is-empty">${esc(
							__("No posted cleaning audit linked to a zone this month.")
					  )}</p>`
			}</section>`;
		};
		const infra = (data.infra_by_category || [])
			.map(
				(r) =>
					`<tr><td>${esc(__(r.key))}</td><td class="is-num">${esc(
						self.num(r.on_time)
					)}/${esc(self.num(r.total))}</td><td class="is-num">${esc(
						self.pct(r.on_time, r.total)
					)}</td></tr>`
			)
			.join("");
		return (
			`<div class="tc-ksnk-cols"><div>${table(
				__("Pass rate by risk level"),
				rates.by_risk
			)}${table(__("Pass rate by department"), rates.by_department)}</div><div>${table(
				__("Pass rate by responsible party"),
				rates.by_party
			)}` +
			`<section class="tc-ksnk-card"><h3>${esc(
				__("Infrastructure inspected on time")
			)}</h3>${
				infra
					? `<table class="tc-ksnk-table"><thead><tr><th>${esc(
							__("Category")
					  )}</th><th>${esc(__("On time / systems"))}</th><th>${esc(
							__("Rate")
					  )}</th></tr></thead><tbody>${infra}</tbody></table>`
					: `<p class="tc-ksnk-state is-empty">${esc(
							__("No infrastructure inspection posted yet.")
					  )}</p>`
			}<p class="tc-ksnk-note">${esc(
				__("Surface disinfectant this month: {0} litres.", [
					self.num(data.chemicals_litres),
				])
			)}</p></section></div></div>`
		);
	},

	pendingHtml(data, esc) {
		const self = TcKsnkScr62;
		const rows = data.pending_nc || [];
		if (!rows.length) return "";
		return rows
			.map(
				(r) => `<div class="tc-ksnk-alert" role="alert" data-region="nc-${esc(r.name)}">
				<strong>${esc(
					__("{0} failed — {1}, {2}:", [
						r.name,
						r.environment_zone_name,
						__(r.sample_type),
					])
				)}</strong>
				<div>${esc(
					__("{0} {1} against {2}.", [
						self.num(r.result_value),
						r.unit || "",
						r.limit_applied,
					])
				)}</div>
				<div>${esc(
					__(
						"Infection control, R11 and the responsible party were notified; the zone stays flagged until a resample passes."
					)
				)}</div>
				<div class="tc-ksnk-actions">${self.sampleActions(data, r)}</div>
				${
					data.can_decide
						? `<div class="tc-ksnk-actions"><button type="button" class="btn btn-danger btn-sm" data-action="open-nc" data-name="${esc(
								r.name
						  )}">${esc(__("Open Environment NC"))}</button>
						<button type="button" class="btn btn-default btn-sm" data-action="dismiss-nc" data-name="${esc(
							r.name
						)}">${esc(__("No NC needed"))}</button>
						<a class="btn btn-default btn-sm" href="/app/environmental-sample/new?is_resample_of=${encodeURIComponent(
							r.name
						)}&environment_zone=${encodeURIComponent(r.environment_zone)}">${esc(
								__("Record resample")
						  )}</a></div>`
						: ""
				}
				<div data-region="nc-alert"></div></div>`
			)
			.join("");
	},

	samplesHtml(data, esc, limit) {
		const self = TcKsnkScr62;
		const rows = (data.samples || []).slice(0, limit || 200);
		const body = rows
			.map(
				(r) => `<tr><td>${self.desk("Environmental Sample", r.name, r.name, esc)}</td>
				<td>${esc(r.environment_zone_name || r.environment_zone)}</td><td>${esc(__(r.sample_type))}</td>
				<td>${esc(self.date(r.sampled_on))}</td><td class="is-num">${esc(
					`${self.num(r.result_value)} ${r.unit || ""}`
				)}</td>
				<td><span class="tc-ksnk-code">${esc(r.limit_applied || "")}</span></td>
				<td>${self.resultBadge(r.result, esc)}${
					r.is_resample_of
						? ` ${self.badge("info", __("Resample of {0}", [r.is_resample_of]), esc)}`
						: ""
				}</td><td>${self.sampleActions(data, r)}</td></tr>`
			)
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Environmental test results — month {0}", [self.month(data.month)])
		)} <span class="tc-ksnk-tag">Environmental Sample · XN-</span></h3>${
			body
				? `<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr><th>${esc(
						__("Code")
				  )}</th><th>${esc(__("Zone"))}</th><th>${esc(__("Sample Type"))}</th><th>${esc(
						__("Sampled On")
				  )}</th><th>${esc(__("Result"))}</th><th>${esc(
						__("Limit (snapshot)")
				  )}</th><th>${esc(__("Assessment"))}</th><th>${esc(
						__("Action")
				  )}</th></tr></thead><tbody>${body}</tbody></table></div>`
				: `<p class="tc-ksnk-state is-empty">${esc(
						__("No environmental sample posted this month.")
				  )}</p>`
		}<p class="tc-ksnk-note">${esc(
			__(
				"Limits are versioned configuration approved by the head of infection control; each sample keeps a snapshot of the limit in effect on its sampling date."
			)
		)}</p></section>`;
	},

	zonesHtml(data, esc) {
		const self = TcKsnkScr62;
		const body = (data.zones || [])
			.map(
				(r) => `<tr><td>${self.desk("Environment Zone", r.zone, r.area_name, esc)}</td>
				<td>${esc(r.department_name || r.department)}</td><td>${esc(r.risk_level)}</td>
				<td>${esc(
					r.responsible_party === "Outsourced Vendor"
						? r.supplier_name || r.supplier
						: __("Department")
				)}</td>
				<td class="is-num">${esc(`${r.done}/${r.required}`)}</td>
				<td>${
					r.short
						? self.badge("warn", `! ${__("Short")}`, esc)
						: self.badge("pass", `✓ ${__("Enough")}`, esc)
				}${
					r.awaiting_resample
						? ` ${self.badge("fail", `✕ ${__("Awaiting resample")}`, esc)}`
						: ""
				}</td></tr>`
			)
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Cleaning zones — audits this month")
		)} <span class="tc-ksnk-tag">Environment Zone · VV-</span></h3>${
			body
				? `<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr><th>${esc(
						__("Zone")
				  )}</th><th>${esc(__("Department"))}</th><th>${esc(
						__("Risk Level")
				  )}</th><th>${esc(__("Responsible Party"))}</th><th>${esc(
						__("Audits / minimum")
				  )}</th><th>${esc(
						__("Status")
				  )}</th></tr></thead><tbody>${body}</tbody></table></div>`
				: `<p class="tc-ksnk-state is-empty">${esc(__("No cleaning zone yet."))}</p>`
		}<div class="tc-ksnk-actions"><a class="btn btn-default btn-sm" href="/app/environment-zone/new">${esc(
			__("New zone")
		)}</a> <a class="btn btn-default btn-sm" href="/app/environment-risk-level">${esc(
			__("Risk levels")
		)}</a></div></section>`;
	},

	infraHtml(data, esc) {
		const self = TcKsnkScr62;
		const status = (r) =>
			r.status === "Overdue"
				? self.badge("fail", `✕ ${__("Overdue")}`, esc)
				: r.status === "Due Soon"
				? self.badge("warn", `! ${__("{0} days left", [r.days_left])}`, esc)
				: self.badge("pass", `✓ ${__("In date")}`, esc);
		const body = (data.infrastructure || [])
			.map(
				(r) => `<tr><td>${esc(r.title || r.template_code)}</td><td>${esc(
					r.area_name || r.zone
				)}</td>
				<td>${esc(self.date(r.last_on))}</td><td>${esc(self.date(r.next_due))}</td><td>${status(
					r
				)}</td></tr>`
			)
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(__("Infrastructure inspections"))}</h3>${
			body
				? `<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr><th>${esc(
						__("Item")
				  )}</th><th>${esc(__("Location"))}</th><th>${esc(__("Last"))}</th><th>${esc(
						__("Next Due")
				  )}</th><th>${esc(
						__("Status")
				  )}</th></tr></thead><tbody>${body}</tbody></table></div>`
				: `<p class="tc-ksnk-state is-empty">${esc(
						__("No infrastructure inspection posted yet.")
				  )}</p>`
		}<p class="tc-ksnk-alert is-info">${esc(
			__(
				"Reminder 7 days before the due date; the CSSD area keeps using the existing Environment Log (M9)."
			)
		)}</p></section>`;
	},

	limitsHtml(data, esc) {
		const self = TcKsnkScr62;
		const limits = (data.limits || [])
			.map(
				(r) => `<tr><td>${self.desk(
					"Environmental Limit",
					r.name,
					r.name,
					esc
				)}</td><td>${esc(r.title)}</td>
				<td>${esc(__(r.sample_type))}</td><td>${esc(r.applies_to_risk_level || __("All levels"))}</td>
				<td><span class="tc-ksnk-code">${esc(r.snapshot)}</span></td><td>${esc(
					self.date(r.effective_from)
				)}</td></tr>`
			)
			.join("");
		const plans = (data.plans || [])
			.map((p) =>
				(p.zones || [])
					.map(
						(z) => `<tr><td>${self.desk(
							"Sampling Plan",
							p.name,
							p.title,
							esc
						)}</td><td>${esc(__(p.sample_type))}</td>
					<td>${esc(z.environment_zone_name || z.environment_zone)}</td><td>${esc(
							__(p.frequency)
						)}</td><td>${esc(p.assignee_name || "")}</td><td>${esc(
							self.date(z.next_due)
						)}</td></tr>`
					)
					.join("")
			)
			.join("");
		const overdue = (data.overdue_samples || [])
			.map(
				(r) =>
					`<li>${esc(
						__("{0} — {1}: due {2}, {3} days late", [
							r.area_name || r.zone,
							__(r.sample_type),
							self.date(r.next_due),
							r.days_late,
						])
					)}</li>`
			)
			.join("");
		const drafts = data.limit_drafts
			? `<p class="tc-ksnk-alert is-warn">${esc(
					__(
						"{0} draft limit(s) — awaiting approval by the head of infection control.",
						[data.limit_drafts]
					)
			  )}</p>`
			: "";
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Limits in effect"))}</h3>${drafts}${
				limits
					? `<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr><th>${esc(
							__("Version")
					  )}</th><th>${esc(__("Title"))}</th><th>${esc(
							__("Sample Type")
					  )}</th><th>${esc(__("Risk Level"))}</th><th>${esc(
							__("Limit")
					  )}</th><th>${esc(
							__("Effective From")
					  )}</th></tr></thead><tbody>${limits}</tbody></table></div>`
					: `<p class="tc-ksnk-state is-empty">${esc(__("No approved limit yet."))}</p>`
			}<div class="tc-ksnk-actions"><a class="btn btn-default btn-sm" href="/app/environmental-limit">${esc(
				__("All limits")
			)}</a>${
				self.perm(data, "Environmental Limit").create
					? ` <a class="btn btn-default btn-sm" href="/app/environmental-limit/new">${esc(
							__("New limit")
					  )}</a>`
					: ""
			}</div></section>` +
			`<section class="tc-ksnk-card"><h3>${esc(__("Sampling plans"))}</h3>${
				overdue
					? `<div class="tc-ksnk-alert is-warn"><strong>${esc(
							__("Samples behind plan")
					  )}</strong><ul>${overdue}</ul></div>`
					: ""
			}${
				plans
					? `<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr><th>${esc(
							__("Plan")
					  )}</th><th>${esc(__("Sample Type"))}</th><th>${esc(
							__("Zone")
					  )}</th><th>${esc(__("Frequency"))}</th><th>${esc(
							__("Assignee")
					  )}</th><th>${esc(
							__("Next Due")
					  )}</th></tr></thead><tbody>${plans}</tbody></table></div>`
					: `<p class="tc-ksnk-state is-empty">${esc(
							__("No active sampling plan.")
					  )}</p>`
			}<div class="tc-ksnk-actions"><a class="btn btn-default btn-sm" href="/app/sampling-plan/new">${esc(
				__("New sampling plan")
			)}</a></div></section>`
		);
	},

	tabsHtml(esc) {
		const labels = {
			overview: __("Overview"),
			zones: __("Cleaning zones"),
			samples: __("Environmental samples"),
			infra: __("Infrastructure"),
			limits: __("Limits & sampling plans"),
		};
		return `<div class="tc-ksnk-tabs" role="tablist">${TC_ENV_TABS.map((key) => {
			const on = key === TcKsnkScr62.tab;
			return `<button type="button" role="tab" class="tc-ksnk-tab${
				on ? " is-active" : ""
			}" aria-selected="${on}" data-tab="${key}">${esc(labels[key])}</button>`;
		}).join("")}</div>`;
	},

	actionsHtml(esc) {
		return `<div class="tc-ksnk-actions">
			<a class="btn btn-primary" href="/app/environmental-sample/new">${esc(
				__("Record test result")
			)}</a>
			<a class="btn btn-default" href="/app/query-report/Environmental Hygiene">${esc(
				__("Monthly/quarterly environment report")
			)}</a></div>`;
	},

	pageHtml(data, esc) {
		const self = TcKsnkScr62;
		const filter = `<div class="tc-ksnk-filters"><label>${esc(
			__("Month")
		)} <input type="month" class="form-control" data-filter="month" value="${esc(
			data.month
		)}"></label></div>`;
		if (data.summary_only)
			return filter + self.kpisHtml(data, esc) + self.ratesHtml(data, esc);
		const body = {
			overview: () =>
				self.kpisHtml(data, esc) +
				self.pendingHtml(data, esc) +
				self.samplesHtml(data, esc, 10) +
				`<div class="tc-ksnk-cols"><div>${self.zonesHtml(
					data,
					esc
				)}</div><div>${self.infraHtml(data, esc)}</div></div>` +
				self.actionsHtml(esc),
			zones: () => self.zonesHtml(data, esc) + self.ratesHtml(data, esc),
			samples: () => self.pendingHtml(data, esc) + self.samplesHtml(data, esc),
			infra: () => self.infraHtml(data, esc),
			limits: () => self.limitsHtml(data, esc),
		}[self.tab];
		return filter + self.tabsHtml(esc) + body();
	},

	askReason(done) {
		frappe.prompt(
			[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
			(values) => done(values.reason),
			__("No non-conformance needed"),
			__("Confirm")
		);
	},

	bind(el, ctx) {
		const self = TcKsnkScr62;
		const month = el.querySelector('[data-filter="month"]');
		if (month)
			month.addEventListener("change", () => {
				ctx.setFilters({ month: month.value });
				self.render(el, ctx);
			});
		el.querySelectorAll("[data-tab]").forEach((button) =>
			button.addEventListener("click", () => {
				self.tab = button.dataset.tab;
				self.render(el, ctx);
			})
		);
		el.querySelectorAll('[data-action="open-nc"], [data-action="dismiss-nc"]').forEach(
			(button) =>
				button.addEventListener("click", () => {
					const box = button.closest("[data-region]");
					const alert = box && box.querySelector('[data-region="nc-alert"]');
					const handlers = {
						success: button.dataset.action === "open-nc" ? false : undefined, // mở NC tự báo mã NC
						on_ok: (result) => {
							if (result.incident)
								frappe.show_alert({
									message: __("Incident {0} opened.", [result.incident]),
									indicator: "green",
								});
							if (ctx.isCurrent()) self.render(el, ctx);
						},
						on_block: (error) => {
							if (alert) alert.innerHTML = self.blockHtml(error, ctx.esc);
						},
					};
					const sample = button.dataset.name;
					if (button.dataset.action === "open-nc")
						self.post(TC_ENV_OPEN_NC, { sample }, handlers);
					else
						self.askReason((reason) =>
							self.post(TC_ENV_DISMISS_NC, { sample, reason }, handlers)
						);
				})
		);
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_ENV_OVERVIEW, { month: ctx.filters.month || "" });
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr62.pageHtml(data, ctx.esc);
			TcKsnkScr62.bind(el, ctx);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkScreens["moi-truong"] = TcKsnkScr62;
window.TcKsnkScr62 = TcKsnkScr62;
