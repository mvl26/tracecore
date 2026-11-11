/* global tracecore, TcKsnk */
// SCR-56 Ca nhiễm khuẩn bệnh viện & kỳ báo cáo (FEAT-063; UC-48; FR-M13-01, 05, 06, 11, 15; BRU-HAI-001, 005; A-131,
// A-144). R01/R11: danh sách ca (mã người bệnh chỉ dạng che), hồ sơ ca với kiểm tra thời gian theo phiên bản định nghĩa,
// Xác định / Loại trừ (bắt buộc lý do) / Gắn chủng vi sinh, Xem mã BN (lý do + Audit Log); R01 khóa / mở khóa kỳ.
// Tạo ca Nghi ngờ trên Desk form HAI Case. Trạng thái luôn có chữ; lỗi chặn hiện alert inline (kết quả → lý do → hành động).

const TC_HAI_SCREEN = "tracecore.v1.hai_case.screen";
const TC_HAI_DETAIL = "tracecore.v1.hai_case.detail";
const TC_HAI_DECIDE = "tracecore.v1.hai_case.decide";
const TC_HAI_ISOLATES = "tracecore.v1.hai_case.isolate_options";
const TC_HAI_LINK = "tracecore.v1.hai_case.link_isolate";
const TC_HAI_LOCK = "tracecore.v1.hai_case.lock_period";
const TC_HAI_UNLOCK = "tracecore.v1.hai_case.unlock_period";
const TC_HAI_REVEAL = "tracecore.v1.patient_code.reveal";
const TC_HAI_CONTEXT = "HAI Case";

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr56 = {
	date(value) {
		if (!value) return "—";
		const [day, time] = String(value).split(" ");
		const [y, m, d] = day.split("-");
		return time ? `${d}/${m}/${y} ${time.slice(0, 5)}` : `${d}/${m}/${y}`;
	},

	month(value) {
		if (!value) return "—";
		const [y, m] = String(value).split("-");
		return `${m}/${y}`;
	},

	opt(value) {
		return value ? __(value, null, TC_HAI_CONTEXT) : "—";
	},

	statusBadge(status, esc) {
		const cls =
			{ Suspected: "is-warn", Confirmed: "is-fail", Excluded: "is-neutral" }[status] ||
			"is-neutral";
		return `<span class="tc-ksnk-badge ${cls}">${esc(TcKsnkScr56.opt(status))}</span>`;
	},

	periodBadge(locked, esc) {
		return locked
			? `<span class="tc-ksnk-badge is-pass">${esc(__("Locked"))}</span>`
			: `<span class="tc-ksnk-badge is-info">${esc(
					__("Open", null, "IC Reporting Period")
			  )}</span>`;
	},

	headHtml(data, esc) {
		const label = data.current_locked
			? __("Period {0} · Locked", [TcKsnkScr56.month(data.current_period)])
			: __("Period {0} · Open", [TcKsnkScr56.month(data.current_period)]);
		return `<p class="tc-ksnk-note"><span class="tc-ksnk-badge ${
			data.current_locked ? "is-pass" : "is-info"
		}">${esc(label)}</span></p>`;
	},

	listHtml(rows, esc, selected, data) {
		const self = TcKsnkScr56;
		// Tạo ca Nghi ngờ trên form Desk; ẩn khi người gọi không có quyền tạo (R13 chỉ đọc).
		const create =
			data && data.can_create === false
				? ""
				: TcKsnk.recordActions(
						{
							doctype: TC_HAI_CONTEXT,
							can_create: true,
							create_label: __("New suspected case"),
						},
						false
				  );
		const body =
			rows
				.map(
					(r) => `<tr class="tc-ksnk-row${
						r.name === selected ? " is-selected" : ""
					}" data-action="open" data-name="${esc(r.name)}" tabindex="0">
				<td class="tc-ksnk-code">${esc(r.name)}</td>
				<td class="tc-ksnk-code">${esc(r.patient_code_masked || "—")}</td>
				<td>${esc(r.department_name || r.department || "—")}</td>
				<td>${esc(r.def_code || "—")}</td>
				<td>${self.statusBadge(r.status, esc)}</td>
			</tr>`
				)
				.join("") || `<tr><td colspan="5">${esc(__("No HAI cases yet."))}</td></tr>`;
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Cases")
		)} <span class="tc-ksnk-tag">HAI Case · CA-</span></h3>
			<table class="tc-ksnk-table"><thead><tr>
				<th>${esc(__("Case"))}</th><th>${esc(__("Patient Code"))}</th><th>${esc(__("Department"))}</th>
				<th>${esc(__("Type"))}</th><th>${esc(__("Status"))}</th>
			</tr></thead><tbody>${body}</tbody></table>
			<p class="tc-ksnk-note">${esc(
				__("The patient code is always masked on lists and exported files.")
			)}</p>
			<div class="tc-ksnk-actions">${create}</div></section>`;
	},

	timeHtml(d, esc) {
		const self = TcKsnkScr56;
		if (!d.time_check || d.time_check === "Not applicable")
			return `<div class="tc-ksnk-alert is-info" role="status">${esc(
				d.time_check_note || ""
			)}</div>`;
		const met = d.time_check === "Met";
		const title = met
			? __("Time check by {0}: met.", [d.case_definition])
			: __("Time check by {0}: not met.", [d.case_definition]);
		const action = met
			? __("The case can be confirmed.")
			: __("Exclude the case, or enter an exception reason to confirm it.");
		const exception = d.exception_reason
			? `<div>${esc(__("Exception reason"))}: ${esc(d.exception_reason)}</div>`
			: "";
		return `<div class="tc-ksnk-alert ${
			met ? "is-info" : "is-warn"
		}" role="status"><strong>${esc(title)}</strong> ${esc(d.time_check_note || "")}<div>${esc(
			action
		)}</div>${exception}</div>${self.lockedHtml(d, esc)}`;
	},

	lockedHtml(d, esc) {
		if (!d.period_locked) return "";
		return `<div class="tc-ksnk-alert is-warn" role="status">${esc(
			__(
				"Reporting period {0} is locked: the case cannot be changed until R01 unlocks it.",
				[TcKsnkScr56.month(d.reporting_period)]
			)
		)}</div>`;
	},

	detailHtml(d, data, esc) {
		const self = TcKsnkScr56;
		if (!d) {
			const blank = (label) => `<div><dt>${esc(label)}</dt><dd>—</dd></div>`;
			return `<section class="tc-ksnk-card"><h3>${esc(
				__("Case record", null, "IC HAI Case")
			)}</h3>
				<dl class="tc-ksnk-facts">
					${blank(__("Patient Code"))}${blank(__("Birth Year · Sex"))}${blank(__("Department"))}
					${blank(__("Admitted At"))}${blank(__("Onset Date"))}${blank(__("Case Definition (snapshot)"))}
					${blank(__("Device Episode"))}${blank(__("Related Isolates"))}${blank(__("Outcome"))}
				</dl>
				<p class="tc-ksnk-state">${esc(__("Choose a case to see its record."))}</p></section>`;
		}
		const episode = d.episode
			? `<span class="tc-ksnk-code">${esc(d.device_episode)}</span> · ${esc(
					self.opt(d.episode.device_type)
			  )} ${esc(__("{0} days", [d.episode.device_days]))}`
			: "—";
		const isolates = (d.isolates || []).length
			? d.isolates
					.map(
						(row) =>
							`<span class="tc-ksnk-code">${esc(row.isolate)}</span> ${esc(
								row.organism || ""
							)}${
								row.mdro_flags
									? ` <span class="tc-ksnk-badge is-fail">${esc(
											row.mdro_flags
									  )}</span>`
									: ""
							}`
					)
					.join("<br>")
			: "—";
		const fact = (label, value) => `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
		const open = d.docstatus === 0 && !d.period_locked;
		const actions = [];
		if (open && data.can_decide) {
			actions.push(
				`<button type="button" class="btn btn-primary" data-action="confirm">${esc(
					__("Confirm case")
				)}</button>`,
				`<button type="button" class="btn btn-default" data-action="exclude">${esc(
					__("Exclude (enter reason)")
				)}</button>`
			);
		}
		if (!d.period_locked && d.docstatus < 2 && data.can_decide)
			actions.push(
				`<button type="button" class="btn btn-default" data-action="link">${esc(
					__("Link isolate")
				)}</button>`
			);
		const reveal = data.can_reveal
			? `<button type="button" class="btn btn-default btn-sm" data-action="reveal">${esc(
					__("View full patient code")
			  )}</button> <span class="tc-ksnk-note">${esc(
					__("R01 and R11 only; a reason is required and recorded in the audit log.")
			  )}</span> <span data-region="revealed" class="tc-ksnk-code"></span>`
			: "";
		return `<section class="tc-ksnk-card" data-name="${esc(d.name)}">
			<h3><span class="tc-ksnk-code">${esc(d.name)}</span> ${self.statusBadge(d.status, esc)}</h3>
			<div data-region="detail-alert"></div>
			<dl class="tc-ksnk-facts">
				${fact(
					__("Patient Code"),
					`<span class="tc-ksnk-code">${esc(d.patient_code_masked || "—")}</span>`
				)}
				${fact(__("Birth Year · Sex"), esc(`${d.birth_year || "—"} · ${self.opt(d.sex)}`))}
				${fact(__("Department"), esc(d.department_name || d.department || "—"))}
				${fact(__("Admitted At"), esc(self.date(d.admission_at)))}
				${fact(__("Onset Date"), esc(self.date(d.onset_date)))}
				${fact(
					__("Case Definition (snapshot)"),
					`<span class="tc-ksnk-code">${esc(d.case_definition || "—")}</span>`
				)}
				${fact(__("Device Episode"), episode)}
				${fact(__("Related Isolates"), isolates)}
				${fact(__("Outcome"), esc(self.opt(d.outcome)))}
			</dl>
			<p>${reveal}</p>
			${self.timeHtml(d, esc)}
			${
				d.exclusion_reason
					? `<p class="tc-ksnk-note">${esc(__("Exclusion Reason"))}: ${esc(
							d.exclusion_reason
					  )}</p>`
					: ""
			}
			<div class="tc-ksnk-actions">${actions.join("")}
				${TcKsnk.recordActions(
					{
						doctype: TC_HAI_CONTEXT,
						name: d.name,
						docstatus: d.docstatus,
						can_write: !!data.can_write,
						can_create: false,
					},
					false
				)}
				<span class="tc-ksnk-note">${esc(
					__("Only R11 and R01 can confirm a case. Locking a period: R01.")
				)}</span>
			</div>
		</section>`;
	},

	periodsHtml(rows, data, esc) {
		const self = TcKsnkScr56;
		const note = (r) => {
			if (r.locked && r.unlock_count)
				return __("Unlocked {0} time(s) — last reason: {1}", [
					r.unlock_count,
					r.unlock_reason || "—",
				]);
			if (r.locked) return __("Indicators saved to IC Indicator Value");
			if (r.missing_wards)
				return __("{0} department(s) without a full census", [r.missing_wards]);
			return __("Census complete");
		};
		const action = (r) => {
			if (!data.can_lock) return "";
			return r.locked
				? `<button type="button" class="btn btn-default btn-sm" data-action="unlock" data-month="${esc(
						r.month
				  )}">${esc(__("Unlock (enter reason)"))}</button>`
				: `<button type="button" class="btn btn-default btn-sm" data-action="lock" data-month="${esc(
						r.month
				  )}">${esc(__("Lock period"))}</button>`;
		};
		const body =
			rows
				.map(
					(r) => `<tr><td class="tc-ksnk-code">${esc(r.name)}</td><td>${self.periodBadge(
						r.locked,
						esc
					)}</td>
				<td>${esc(r.locked_by_name || "—")}</td><td>${esc(r.locked ? self.date(r.locked_on) : "—")}</td>
				<td>${esc(note(r))}</td><td>${action(r)}</td></tr>`
				)
				.join("") ||
			`<tr><td colspan="6">${esc(__("No reporting period yet."))}</td></tr>`;
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Reporting periods")
		)} <span class="tc-ksnk-tag">IC Reporting Period · KY-</span></h3>
			<div data-region="period-alert"></div>
			<table class="tc-ksnk-table"><thead><tr>
				<th>${esc(__("Period"))}</th><th>${esc(__("Status"))}</th><th>${esc(__("Locked By"))}</th>
				<th>${esc(__("Locked On"))}</th><th>${esc(__("Note"))}</th><th></th>
			</tr></thead><tbody>${body}</tbody></table></section>`;
	},

	pageHtml(data, esc, detail) {
		const self = TcKsnkScr56;
		return (
			self.headHtml(data, esc) +
			`<div class="tc-ksnk-cols"><div>${self.listHtml(
				data.cases || [],
				esc,
				detail && detail.name,
				data
			)}</div>
			<div data-region="detail">${self.detailHtml(detail, data, esc)}</div></div>` +
			`<div data-region="periods">${self.periodsHtml(data.periods || [], data, esc)}</div>`
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

	askReason(title, label, done) {
		frappe.prompt(
			[{ fieldname: "reason", fieldtype: "Small Text", label, reqd: 1 }],
			(values) => done(values.reason),
			title,
			__("Confirm")
		);
	},

	call(method, args, region, esc, onOk, button) {
		if (button) button.disabled = true;
		tracecore.desk_call({
			method,
			args,
			on_ok: (result) => {
				if (button) button.disabled = false;
				onOk(result);
			},
			on_block: (error) => {
				if (button) button.disabled = false;
				if (region) region.innerHTML = TcKsnkScr56.blockHtml(error, esc);
			},
			on_fail: () => {
				if (button) button.disabled = false;
			},
		});
	},

	async openDetail(el, ctx, data, name) {
		const region = el.querySelector('[data-region="detail"]');
		if (!region) return;
		region.innerHTML = ctx.state("loading");
		try {
			const result = await ctx.get(TC_HAI_DETAIL, { name });
			if (!ctx.isCurrent()) return;
			TcKsnkScr56.paintDetail(el, ctx, data, result.detail);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			region.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},

	paintDetail(el, ctx, data, detail) {
		el.querySelectorAll(".tc-ksnk-row").forEach((row) =>
			row.classList.toggle("is-selected", row.dataset.name === detail.name)
		);
		const region = el.querySelector('[data-region="detail"]');
		region.innerHTML = TcKsnkScr56.detailHtml(detail, data, ctx.esc);
		TcKsnkScr56.bindDetail(el, ctx, data, detail);
	},

	bindDetail(el, ctx, data, d) {
		const self = TcKsnkScr56;
		const region = el.querySelector('[data-region="detail"]');
		const alert = region.querySelector('[data-region="detail-alert"]');
		const done = (result) => {
			if (!ctx.isCurrent()) return;
			self.render(el, ctx, result.detail || d);
		};
		region.querySelectorAll("[data-action]").forEach((button) => {
			button.addEventListener("click", () => {
				const action = button.dataset.action;
				if (action === "confirm") {
					const send = (exception) =>
						self.call(
							TC_HAI_DECIDE,
							{
								name: d.name,
								decision: "Confirmed",
								exception_reason: exception || "",
							},
							alert,
							ctx.esc,
							done,
							button
						);
					if (d.time_check === "Not met")
						self.askReason(
							__("Confirm case with an exception"),
							__("Exception Reason"),
							send
						);
					else send("");
				} else if (action === "exclude") {
					self.askReason(__("Exclude case"), __("Exclusion Reason"), (reason) =>
						self.call(
							TC_HAI_DECIDE,
							{ name: d.name, decision: "Excluded", reason },
							alert,
							ctx.esc,
							done,
							button
						)
					);
				} else if (action === "link") {
					self.pickIsolate(ctx, d, (isolate) =>
						self.call(
							TC_HAI_LINK,
							{ name: d.name, isolate },
							alert,
							ctx.esc,
							done,
							button
						)
					);
				} else if (action === "reveal") {
					self.askReason(
						__("Why do you need the full patient code?"),
						__("Reason"),
						(reason) =>
							self.call(
								TC_HAI_REVEAL,
								{ doctype: "HAI Case", name: d.name, reason },
								alert,
								ctx.esc,
								(result) => {
									const box = region.querySelector('[data-region="revealed"]');
									if (box) box.textContent = result.patient_code || "—";
								},
								button
							)
					);
				}
			});
		});
	},

	async pickIsolate(ctx, d, done) {
		const result = await ctx.get(TC_HAI_ISOLATES, { name: d.name });
		const rows = result.isolates || [];
		if (!rows.length) {
			frappe.msgprint(__("No other isolate of this patient was found."));
			return;
		}
		const options = rows.map((r) => ({
			value: r.name,
			label: `${r.name} · ${r.organism_name || ""} · ${TcKsnkScr56.date(r.collected_on)}${
				r.mdro_flags ? ` · ${r.mdro_flags}` : ""
			}`,
		}));
		frappe.prompt(
			[
				{
					fieldname: "isolate",
					fieldtype: "Select",
					label: __("Isolate"),
					options,
					reqd: 1,
				},
			],
			(values) => done(values.isolate),
			__("Link isolate"),
			__("Link")
		);
	},

	bindPeriods(el, ctx, data) {
		const self = TcKsnkScr56;
		const region = el.querySelector('[data-region="periods"]');
		if (!region) return;
		const alert = () => region.querySelector('[data-region="period-alert"]');
		const done = () => {
			if (ctx.isCurrent()) self.render(el, ctx, null);
		};
		region.querySelectorAll("[data-action]").forEach((button) => {
			button.addEventListener("click", () => {
				const month = button.dataset.month;
				if (button.dataset.action === "lock") {
					frappe.confirm(
						__(
							"Lock period {0}? Census and cases of the month can no longer change.",
							[self.month(month)]
						),
						() => self.call(TC_HAI_LOCK, { month }, alert(), ctx.esc, done, button)
					);
				} else {
					self.askReason(__("Unlock period"), __("Reason"), (reason) =>
						self.call(TC_HAI_UNLOCK, { month, reason }, alert(), ctx.esc, done, button)
					);
				}
			});
		});
	},

	bind(el, ctx, data) {
		el.querySelectorAll('[data-action="open"]').forEach((row) => {
			const open = () => TcKsnkScr56.openDetail(el, ctx, data, row.dataset.name);
			row.addEventListener("click", open);
			row.addEventListener("keydown", (event) => {
				if (event.key === "Enter") open();
			});
		});
		TcKsnkScr56.bindPeriods(el, ctx, data);
	},

	async render(el, ctx, detail) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_HAI_SCREEN, {
				period: ctx.filters.period || "",
				department: ctx.filters.department || "",
			});
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr56.pageHtml(data, ctx.esc, null);
			TcKsnkScr56.bind(el, ctx, data);
			const wanted =
				(detail && detail.name) || new URLSearchParams(window.location.search).get("case");
			if (wanted) TcKsnkScr56.openDetail(el, ctx, data, wanted);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkScreens["ca-nkbv"] = TcKsnkScr56;
window.TcKsnkScr56 = TcKsnkScr56;
