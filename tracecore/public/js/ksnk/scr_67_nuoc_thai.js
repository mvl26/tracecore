/* global tracecore, TcKsnk */
// SCR-67 Nước thải y tế — view WEB trong Page tc-ksnk (FEAT-095; UC-58; FR-M15-08..13; BRU-ENV-003..006; A-153 §3.4).
// 3 khối: thẻ GPMT hiện hành + Cần xử lý; lưới lịch điểm × kỳ 12 tháng; bảng đợt gần nhất từng điểm. Ghi đợt, GPMT, điểm
// trên Desk form (thông số tự nạp theo GPMT tại ngày lấy mẫu). R01 mở NC / bỏ qua có lý do, "Cập nhật GPMT" = phiên bản
// mới; R11 ghi đợt; R02 chỉ xem; R13 chỉ thẻ tóm tắt. Lỗi chặn = alert inline (kết quả → lý do → hành động); trạng thái
// luôn có chữ, không chỉ màu.

const TC_WW_OVERVIEW = "tracecore.v1.wastewater.overview";
const TC_WW_NEW_VERSION = "tracecore.v1.wastewater.new_permit_version";
const TC_WW_OPEN_NC = "tracecore.v1.wastewater.open_nc";
const TC_WW_DISMISS_NC = "tracecore.v1.wastewater.dismiss_nc";
const TC_WW_REPORT = "/app/query-report/Wastewater Monitoring Summary";

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr67 = {
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

	perm(data, doctype) {
		return ((data && data.perms) || {})[doctype] || {};
	},

	desk(doctype, name, label, esc) {
		return `<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(
			name
		)}"><span class="tc-ksnk-code">${esc(label || name)}</span></a>`;
	},

	newRoundUrl(point, remonitorOf) {
		let url = `/app/wastewater-monitoring/new?wastewater_point=${encodeURIComponent(
			point || ""
		)}`;
		if (remonitorOf) url += `&is_remonitor_of=${encodeURIComponent(remonitorOf)}`;
		return url;
	},

	// Trạng thái ô lịch (FR-M15-09): chữ + ký hiệu, màu chỉ là phụ
	cellHtml(cell, esc) {
		const self = TcKsnkScr67;
		const map = {
			done: ["pass", `✓ ${__("Monitored")}`],
			fail: ["fail", `✕ ${__("Failed")}`],
			miss: ["warn", `! ${__("Missing parameters")}`],
			due: ["info", __("Due")],
			over: ["fail", `✕ ${__("Overdue")}`],
			future: ["neutral", __("Not yet due")],
			na: ["neutral", __("Not applicable")],
			none: ["neutral", __("No permit")],
		};
		const [cls, label] = map[cell.status] || map.none;
		let note = "";
		if (cell.status === "due" && cell.days_left !== null && cell.days_left !== undefined)
			note = __("{0} days left", [cell.days_left]);
		else if (cell.status === "na") note = __("automatic monitoring");
		else if (cell.missing && cell.missing.length && cell.status !== "done")
			note = __("missing {0}", [cell.missing.join(", ")]);
		else if (cell.date) note = __("sampled {0}", [self.date(cell.date)]);
		return `${self.badge(cls, label, esc)}${
			note ? `<small class="tc-ksnk-note">${esc(note)}</small>` : ""
		}`;
	},

	kpisHtml(data, esc) {
		const k = data.kpis || {};
		const tile = (cls, label, value) =>
			`<div class="tc-ksnk-kpi${cls ? ` is-${cls}` : ""}"><span>${esc(
				label
			)}</span><strong>${esc(value)}</strong></div>`;
		return (
			`<div class="tc-ksnk-kpis">` +
			tile("", __("Periodic monitoring points"), k.points || 0) +
			tile(
				k.on_time < k.total_periods ? "warn" : "pass",
				__("Periods monitored on time in {0}", [data.year]),
				`${k.on_time || 0}/${k.total_periods || 0}`
			) +
			tile(k.overdue ? "fail" : "", __("Periods overdue"), k.overdue || 0) +
			tile(
				k.flagged ? "fail" : "",
				__("Points exceeded – awaiting re-monitoring"),
				k.flagged || 0
			) +
			tile(
				"",
				__("Days left in current period"),
				k.days_left_period === null || k.days_left_period === undefined
					? "—"
					: k.days_left_period
			) +
			`</div>`
		);
	},

	permitHtml(data, esc) {
		const self = TcKsnkScr67;
		const canPermit = self.perm(data, "Wastewater Permit").create;
		const permits = data.permits || [];
		if (!permits.length)
			return `<section class="tc-ksnk-card"><h3>${esc(
				__("Environmental permit in effect")
			)}</h3><p class="tc-ksnk-state is-empty">${esc(
				__(
					"No approved environmental permit yet. Monitoring schedule and limits come from the hospital's environmental permit."
				)
			)}</p>${
				canPermit
					? `<div class="tc-ksnk-actions"><a class="btn btn-primary btn-sm" href="/app/wastewater-permit/new">${esc(
							__("Declare permit")
					  )}</a> <a class="btn btn-default btn-sm" href="/app/wastewater-point/new">${esc(
							__("New point")
					  )}</a></div>`
					: `<p class="tc-ksnk-note">${esc(
							__("Ask the head of infection control (R01) to declare the permit.")
					  )}</p>`
			}</section>`;
		const cards = permits
			.map((p) => {
				const expiry = p.expiring
					? self.badge(
							p.days_to_expiry < 0 ? "fail" : "warn",
							p.days_to_expiry < 0
								? `✕ ${__("Expired")}`
								: `! ${__("{0} days left", [p.days_to_expiry])}`,
							esc
					  )
					: self.badge("pass", `✓ ${__("In effect")}`, esc);
				return `<div class="tc-ksnk-permit">
				<h4>${self.desk("Wastewater Permit", p.name, p.name, esc)} ${expiry}${
					p.previous
						? ` <span class="tc-ksnk-note">${esc(__("Previous version"))}: ${self.desk(
								"Wastewater Permit",
								p.previous,
								p.previous,
								esc
						  )}</span>`
						: ""
				}</h4>
				<dl class="tc-ksnk-dl">
					<dt>${esc(__("Permit No"))}</dt><dd><span class="tc-ksnk-code">${esc(p.permit_no)}</span></dd>
					<dt>${esc(__("Standard · Column"))}</dt><dd>${esc(`${p.standard} · ${p.standard_column}`)}</dd>
					<dt>${esc(__("Effective From"))}</dt><dd>${esc(self.date(p.effective_from))}</dd>
					<dt>${esc(__("Valid Until"))}</dt><dd>${esc(self.date(p.valid_until))}</dd>
					<dt>${esc(__("Issuing Authority"))}</dt><dd>${esc(p.issuing_authority || "—")}</dd>
					<dt>${esc(__("Factor Note"))}</dt><dd>${esc(p.factor_note || "—")}</dd>
				</dl>${
					canPermit
						? `<div class="tc-ksnk-actions"><button type="button" class="btn btn-default btn-sm" data-action="new-version" data-name="${esc(
								p.name
						  )}">${esc(__("Update permit (new version)"))}</button></div>
						<div data-region="permit-alert"></div>`
						: ""
				}</div>`;
			})
			.join("");
		const drafts = data.drafts
			? `<p class="tc-ksnk-alert is-warn">${esc(
					__(
						"{0} draft permit version(s) — awaiting approval by the head of infection control.",
						[data.drafts]
					)
			  )}</p>`
			: "";
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Environmental permit in effect")
		)}</h3>${drafts}${cards}</section>`;
	},

	attentionHtml(data, esc) {
		const self = TcKsnkScr67;
		const create = self.perm(data, "Wastewater Monitoring").create;
		const items = [];
		(data.flagged || []).forEach((f) => {
			const decide = data.can_decide && f.nc_status === "Suggested";
			items.push(`<div class="tc-ksnk-alert" role="alert" data-region="nc-${esc(
				f.monitoring
			)}">
				<strong>${esc(
					`${f.point} · ${f.point_name} — ${__("Exceeded – awaiting re-monitoring")}`
				)}</strong>
				<div>${esc(
					__("Round {0} sampled {1}: {2} exceeded the permit limits.", [
						f.monitoring,
						self.date(f.sampled_on),
						(f.failed || []).join(", ") || "—",
					])
				)}</div>
				<div>${esc(
					f.nc_name
						? __("Non-conformance {0} is open.", [f.nc_name])
						: __("Infection control, R11 and the responsible person were notified.")
				)}</div>
				<div class="tc-ksnk-actions">${
					decide
						? `<button type="button" class="btn btn-danger btn-sm" data-action="open-nc" data-name="${esc(
								f.monitoring
						  )}">${esc(__("Open Environment NC"))}</button>
						<button type="button" class="btn btn-default btn-sm" data-action="dismiss-nc" data-name="${esc(
							f.monitoring
						)}">${esc(__("No NC needed"))}</button>`
						: ""
				}${
				create
					? ` <a class="btn btn-default btn-sm" href="${self.newRoundUrl(
							f.point,
							f.monitoring
					  )}">${esc(__("Record re-monitoring"))}</a>`
					: ""
			}</div><div data-region="nc-alert"></div></div>`);
		});
		(data.schedule || []).forEach((row) =>
			(row.periods || [])
				.filter((c) => c.status === "over" || (c.status === "miss" && c.end < data.today))
				.forEach((c) =>
					items.push(
						`<div class="tc-ksnk-alert ${
							c.status === "over" ? "" : "is-warn"
						}" role="status"><strong>${esc(
							`${row.point} · ${c.label} — ${
								c.status === "over" ? __("Overdue") : __("Missing parameters")
							}`
						)}</strong><div>${esc(
							c.status === "over"
								? __("No monitoring round in this period.")
								: __("Missing: {0}. The period does not count as monitored.", [
										(c.missing || []).join(", "),
								  ])
						)}</div></div>`
					)
				)
		);
		(data.labs || [])
			.filter((lab) => lab.expired || lab.expiring)
			.forEach((lab) =>
				items.push(
					`<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
						lab.supplier_name
					)}</strong><div>${esc(
						lab.expired
							? __(
									"{0} expired on {1} — cannot be chosen for samples taken after this date.",
									[lab.vimcerts_no, self.date(lab.valid_until)]
							  )
							: __("{0} expires on {1}.", [
									lab.vimcerts_no,
									self.date(lab.valid_until),
							  ])
					)}</div></div>`
				)
			);
		return `<section class="tc-ksnk-card"><h3>${esc(__("Needs attention"))}</h3>${
			items.length
				? items.join("")
				: `<p class="tc-ksnk-state is-empty">${esc(__("Nothing to handle."))}</p>`
		}</section>`;
	},

	scheduleHtml(data, esc) {
		const self = TcKsnkScr67;
		const months = Array.from({ length: 12 }, (_v, i) => i + 1);
		const [ty, tm] = String(data.today || "")
			.split("-")
			.map(Number);
		const head = months
			.map(
				(m) =>
					`<th class="is-num"${
						ty === Number(data.year) && tm === m ? ' aria-current="date"' : ""
					}>${esc(__("M{0}", [m]))}</th>`
			)
			.join("");
		const body = (data.schedule || [])
			.map((row) => {
				const span = row.frequency || 12;
				const cells = (row.periods || [])
					.map(
						(c) =>
							`<td colspan="${row.periods.length === 1 ? 12 : span}" class="${
								c.start <= data.today && data.today <= c.end ? "is-current" : ""
							}">${self.cellHtml(c, esc)}</td>`
					)
					.join("");
				return `<tr><td>${self.desk("Wastewater Point", row.point, row.point, esc)} ${esc(
					row.point_name
				)}${
					row.awaiting_remonitor
						? `<br>${self.badge(
								"fail",
								`⚑ ${__("Exceeded – awaiting re-monitoring")}`,
								esc
						  )}`
						: ""
				}<small class="tc-ksnk-note">${esc(
					`${__(row.point_type || "")} · ${row.responsible_name || "—"}`
				)}</small></td><td>${esc(
					row.auto_only
						? __("Automatic")
						: row.frequency
						? __("Every {0} months", [row.frequency])
						: "—"
				)}</td>${cells}</tr>`;
			})
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Monitoring schedule {0}", [data.year])
		)} <span class="tc-ksnk-tag">${esc(__("point × period"))}</span></h3>
		<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr><th>${esc(
			__("Point")
		)}</th><th>${esc(__("Frequency"))}</th>${head}</tr></thead><tbody>${
			body ||
			`<tr class="is-empty"><td colspan="14" class="tc-ksnk-note">${esc(
				__("No monitoring point yet.")
			)}</td></tr>`
		}</tbody></table></div>
		<p class="tc-ksnk-note">${esc(
			__(
				"A period counts as monitored only when every required parameter has a value or Not detected. Automatically monitored parameters are not in the periodic schedule."
			)
		)}</p></section>`;
	},

	resultCell(row, inlet, esc) {
		const self = TcKsnkScr67;
		const value = row.below_detection
			? __("Not detected")
			: row.value
			? self.num(row.value)
			: __("Missing");
		if (inlet) return `<td class="is-num">${esc(value)}</td>`;
		if (row.result === "Fail")
			return `<td class="is-num">${esc(value)} ${self.badge(
				"fail",
				`✕ ${__("Exceeded")}`,
				esc
			)}</td>`;
		if (row.result === "Pass") return `<td class="is-num">${esc(value)}</td>`;
		return `<td class="is-num">${self.badge("warn", value, esc)}</td>`;
	},

	overallBadge(result, esc) {
		const self = TcKsnkScr67;
		return (
			{
				Pass: self.badge("pass", `✓ ${__("Pass")}`, esc),
				Fail: self.badge("fail", `✕ ${__("Fail")}`, esc),
				Incomplete: self.badge("warn", `! ${__("Missing parameters")}`, esc),
				"Reference Only": self.badge("neutral", __("Reference only"), esc),
			}[result] || ""
		);
	},

	latestHtml(data, esc) {
		const self = TcKsnkScr67;
		const latest = data.latest || [];
		if (!latest.length)
			return `<section class="tc-ksnk-card"><h3>${esc(
				__("Latest round by point")
			)}</h3><p class="tc-ksnk-state is-empty">${esc(
				__("No monitoring round posted yet.")
			)}</p></section>`;
		const params = [];
		latest.forEach((r) =>
			(r.results || []).forEach((x) => {
				if (!params.some((p) => p.parameter === x.parameter)) params.push(x);
			})
		);
		const heads = latest
			.map(
				(r) =>
					`<th>${esc(r.wastewater_point || r.point)}<br><span class="tc-ksnk-note">${esc(
						self.date(r.sampled_on)
					)}</span></th>`
			)
			.join("");
		const body = params
			.map(
				(p) =>
					`<tr><td>${esc(p.parameter)}</td><td>${esc(
						p.unit || ""
					)}</td><td class="is-num">${esc(p.limit_text || "—")}</td>${latest
						.map((r) => {
							const row = (r.results || []).find((x) => x.parameter === p.parameter);
							return row
								? self.resultCell(row, r.point_type === "Inlet", esc)
								: `<td class="is-num">—</td>`;
						})
						.join("")}</tr>`
			)
			.join("");
		const outcome = latest
			.map((r) => `<td>${self.overallBadge(r.overall_result, esc)}</td>`)
			.join("");
		const refs = latest
			.map(
				(r) =>
					`<td>${self.desk("Wastewater Monitoring", r.name, r.name, esc)}<br>${esc(
						r.supplier_name || ""
					)}<br>${esc(r.vimcerts_no || "")} · ${esc(r.report_no || "")}</td>`
			)
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(__("Latest round by point"))}</h3>
		<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr><th>${esc(
			__("Parameter")
		)}</th><th>${esc(__("Unit"))}</th><th>${esc(
			__("Limit")
		)}</th>${heads}</tr></thead><tbody>${body}
		<tr><td colspan="3"><strong>${esc(__("Round result"))}</strong></td>${outcome}</tr>
		<tr><td colspan="3">${esc(__("Round · monitoring unit"))}</td>${refs}</tr></tbody></table></div>
		<p class="tc-ksnk-note">${esc(
			__(
				"Not detected passes against an upper limit. Inlet values are for reference only. Each round keeps a snapshot of the permit limits in effect on its sampling date."
			)
		)}</p></section>`;
	},

	actionsHtml(data, esc) {
		const self = TcKsnkScr67;
		const create = self.perm(data, "Wastewater Monitoring").create;
		const canPoint = self.perm(data, "Wastewater Point").create;
		return `<div class="tc-ksnk-actions">${
			create && (data.permits || []).length
				? `<a class="btn btn-primary" href="/app/wastewater-monitoring/new">${esc(
						__("Record monitoring round")
				  )}</a>`
				: ""
		}<a class="btn btn-default" href="${TC_WW_REPORT}">${esc(__("Export report"))}</a>${
			canPoint
				? `<a class="btn btn-default" href="/app/wastewater-point">${esc(
						__("Monitoring points")
				  )}</a>`
				: ""
		}</div>`;
	},

	yearOptions(selected, esc) {
		const now = new Date().getFullYear();
		const out = [];
		for (let y = now + 1; y >= now - 4; y--)
			out.push(
				`<option value="${y}"${y === Number(selected) ? " selected" : ""}>${esc(
					String(y)
				)}</option>`
			);
		return out.join("");
	},

	pageHtml(data, esc) {
		const self = TcKsnkScr67;
		const filter = `<div class="tc-ksnk-headrow"><div class="tc-ksnk-filters"><label>${esc(
			__("Year")
		)}<select class="form-control" data-filter="year">${self.yearOptions(
			data.year,
			esc
		)}</select></label></div></div>`;
		if (data.summary_only)
			return (
				filter +
				self.kpisHtml(data, esc) +
				`<p class="tc-ksnk-alert is-info">${esc(
					__(
						"Summary view. Round details and result reports are managed by the infection control department."
					)
				)}</p>`
			);
		return (
			filter +
			self.actionsHtml(data, esc) +
			self.kpisHtml(data, esc) +
			`<div class="tc-ksnk-cols"><div>${self.permitHtml(
				data,
				esc
			)}</div><div>${self.attentionHtml(data, esc)}</div></div>` +
			self.scheduleHtml(data, esc) +
			self.latestHtml(data, esc)
		);
	},

	// POST @idempotent: khóa giữ nguyên khi bấm lại cùng dữ liệu (thử lại sau lỗi mạng)
	post(method, args, handlers) {
		const sig = JSON.stringify([method, args]);
		if (!TcKsnkScr67.pending || TcKsnkScr67.pending.sig !== sig)
			TcKsnkScr67.pending = { sig, key: TcKsnkScr67.uuid(), ts: TcKsnkScr67.iso() };
		const pending = TcKsnkScr67.pending;
		const handle = (result) => {
			TcKsnkScr67.pending = null;
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

	bind(el, ctx) {
		const self = TcKsnkScr67;
		const year = el.querySelector('[data-filter="year"]');
		if (year)
			year.addEventListener("change", () => {
				ctx.setFilters({ year: year.value });
				self.render(el, ctx);
			});
		el.querySelectorAll('[data-action="new-version"]').forEach((button) =>
			button.addEventListener("click", () => {
				const alert = button
					.closest(".tc-ksnk-permit")
					.querySelector('[data-region="permit-alert"]');
				self.post(
					TC_WW_NEW_VERSION,
					{ permit: button.dataset.name },
					{
						success: false,
						on_ok: (result) =>
							frappe.set_route("Form", "Wastewater Permit", result.name),
						on_block: (error) => {
							if (alert) alert.innerHTML = self.blockHtml(error, ctx.esc);
						},
					}
				);
			})
		);
		el.querySelectorAll('[data-action="open-nc"], [data-action="dismiss-nc"]').forEach(
			(button) =>
				button.addEventListener("click", () => {
					const box = button.closest("[data-region]");
					const alert = box && box.querySelector('[data-region="nc-alert"]');
					const handlers = {
						success: button.dataset.action === "open-nc" ? false : undefined,
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
					const monitoring = button.dataset.name;
					if (button.dataset.action === "open-nc")
						self.post(TC_WW_OPEN_NC, { monitoring }, handlers);
					else
						frappe.prompt(
							[
								{
									fieldname: "reason",
									fieldtype: "Small Text",
									label: __("Reason"),
									reqd: 1,
								},
							],
							(values) =>
								self.post(
									TC_WW_DISMISS_NC,
									{ monitoring, reason: values.reason },
									handlers
								),
							__("No non-conformance needed"),
							__("Confirm")
						);
				})
		);
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_WW_OVERVIEW, { year: ctx.filters.year || "" });
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr67.pageHtml(data, ctx.esc);
			TcKsnkScr67.bind(el, ctx);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkScreens["nuoc-thai"] = TcKsnkScr67;
window.TcKsnkScr67 = TcKsnkScr67;
