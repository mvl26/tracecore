/* global tracecore */
// SCR-64 Phơi nhiễm nghề nghiệp & tiêm chủng nhân viên (FEAT-071; UC-55; FR-M16-03..09; BRU-OCC-001..004; A-131,
// A-137). R01/R11: KPI, hồ sơ phơi nhiễm (mã BN nguồn chỉ dạng che), xử trí (sơ cứu, chỉ định dự phòng → lịch theo
// dõi theo mẫu đã duyệt), ghi "đã thực hiện" từng mốc (không có ô kết quả), tiêm chủng, cảnh báo thuốc dự phòng.
// R13: chỉ số liệu tổng hợp. Trạng thái và cờ luôn có chữ; lỗi chặn hiện alert inline (kết quả → lý do → hành động).

const TC_EXP_DASHBOARD = "tracecore.v1.exposure.dashboard_data";
const TC_EXP_DETAIL = "tracecore.v1.exposure.detail";
const TC_EXP_HANDLING = "tracecore.v1.exposure.record_handling";
const TC_EXP_STEP_DONE = "tracecore.v1.exposure.followup_done";
const TC_EXP_CANCEL = "tracecore.v1.exposure.cancel";
const TC_EXP_REVEAL = "tracecore.v1.exposure.reveal_source_code";
const TC_EXP_CONTEXT = "Occupational Exposure";
const TC_EXP_REPORT = "/app/query-report/Occupational Exposure by Period";
const TC_EXP_PORTAL = "/ksnk-khoa/bao-phoi-nhiem";

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr64 = {
	date(value) {
		if (!value) return "—";
		const [day, time] = String(value).split(" ");
		const [y, m, d] = day.split("-");
		return time ? `${d}/${m}/${y} ${time.slice(0, 5)}` : `${d}/${m}/${y}`;
	},

	duration(minutes) {
		if (minutes === null || minutes === undefined || minutes === "") return "—";
		const value = Number(minutes);
		const hours = Math.floor(value / 60);
		const rest = value % 60;
		return hours ? __("{0} h {1} min", [hours, rest]) : __("{0} min", [rest]);
	},

	opt(value) {
		return value ? __(value, null, TC_EXP_CONTEXT) : "—";
	},

	statusBadge(status, esc) {
		const cls =
			{
				New: "is-fail",
				"Following Up": "is-neutral",
				Completed: "is-pass",
				Cancelled: "is-neutral",
			}[status] || "is-neutral";
		const label = status === "New" ? __("New — awaiting handling") : TcKsnkScr64.opt(status);
		return `<span class="tc-ksnk-badge ${cls}">${esc(label)}</span>`;
	},

	lateBadge(esc) {
		return ` <span class="tc-ksnk-badge is-warn">${esc(__("Late"))}</span>`;
	},

	kpisHtml(kpis, esc) {
		const imm = kpis.immunization || {};
		const tile = (label, value, warn) =>
			`<div class="tc-ksnk-kpi${warn ? " is-warn" : ""}"><span>${esc(
				label
			)}</span><strong>${esc(value)}</strong></div>`;
		const th = kpis.thresholds || {};
		const limits = [
			th.report_hours
				? __("report within {0} h", [th.report_hours])
				: __("report limit not set"),
			th.prophylaxis_hours
				? __("prophylaxis within {0} h", [th.prophylaxis_hours])
				: __("prophylaxis limit not set"),
		].join(" · ");
		return (
			`<div class="tc-ksnk-kpis">` +
			tile(__("Exposures in {0}", [kpis.year]), kpis.year_total, false) +
			tile(__("Late (over the time limit)"), kpis.late, kpis.late > 0) +
			tile(__("Being followed up"), kpis.following, false) +
			tile(
				__("Staff with all required vaccines"),
				imm.rate === null || imm.rate === undefined ? "—" : `${imm.rate} %`,
				false
			) +
			`</div><p class="tc-ksnk-note">${esc(__("Time limits in use"))}: ${esc(limits)}</p>`
		);
	},

	recordsHtml(rows, esc) {
		const self = TcKsnkScr64;
		if (!rows.length)
			return `<section class="tc-ksnk-card"><h3>${esc(__("Exposure records"))}</h3>
				<p class="tc-ksnk-state">${esc(__("No exposure records yet."))}</p></section>`;
		const body = rows
			.map(
				(r) => `<tr>
				<td><button type="button" class="btn btn-link tc-ksnk-code" data-action="open" data-name="${esc(
					r.name
				)}">${esc(r.name)}</button></td>
				<td>${esc(r.employee_name || "—")}</td>
				<td>${esc(r.department_name || r.department || "—")}</td>
				<td>${esc(self.opt(r.exposure_type))}</td>
				<td>${esc(self.opt(r.report_channel))}</td>
				<td class="is-num">${esc(self.duration(r.minutes_to_report))}${
					r.report_late ? self.lateBadge(esc) : ""
				}</td>
				<td class="is-num">${esc(self.duration(r.minutes_to_prophylaxis))}${
					r.prophylaxis_late ? self.lateBadge(esc) : ""
				}</td>
				<td>${self.statusBadge(r.status, esc)}</td>
			</tr>`
			)
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(__("Exposure records"))}</h3>
			<table class="tc-ksnk-table"><thead><tr>
				<th>${esc(__("Code"))}</th><th>${esc(__("Employee"))}</th><th>${esc(__("Department"))}</th>
				<th>${esc(__("Type"))}</th><th>${esc(__("Reported Via"))}</th>
				<th>${esc(__("Exposure to report"))}</th><th>${esc(__("Exposure to prophylaxis"))}</th>
				<th>${esc(__("Status"))}</th>
			</tr></thead><tbody>${body}</tbody></table>
			<div class="tc-ksnk-alert is-info" role="note">${esc(
				__(
					"Only the head of infection control, the supervisor and the staff member can see a record; reports show totals without names. There is no field for the staff member's test results or diagnosis."
				)
			)}</div></section>`;
	},

	detailHtml(d, esc) {
		const self = TcKsnkScr64;
		if (!d)
			return `<section class="tc-ksnk-card"><p class="tc-ksnk-state">${esc(
				__("Choose a record to see its follow-up schedule.")
			)}</p></section>`;
		const open = d.status === "New" || d.status === "Following Up";
		const steps = (d.followups || [])
			.map((row) => {
				const done = row.done_on
					? `<span class="tc-ksnk-badge is-pass">${esc(__("Done"))} ${esc(
							self.date(row.done_on)
					  )}</span>`
					: open
					? `<input type="date" class="form-control tc-ksnk-date" data-step-date="${esc(
							row.name
					  )}">
					   <button type="button" class="btn btn-default btn-sm" data-action="step-done" data-row="${esc(
							row.name
						)}">${esc(__("Mark done"))}</button>`
					: `<span class="tc-ksnk-badge is-neutral">${esc(__("Not done"))}</span>`;
				return `<tr><td>${esc(row.step)}</td><td>${esc(
					self.date(row.due_date)
				)}</td><td>${done}</td></tr>`;
			})
			.join("");
		const schedule = d.followups.length
			? `<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Step"))}</th><th>${esc(
					__("Due")
			  )}</th><th>${esc(__("Done"))}</th></tr></thead><tbody>${steps}</tbody></table>
			  <p class="tc-ksnk-note">${esc(
					__(
						"Steps come from the approved follow-up template; only the date done is recorded, never a result."
					)
				)}</p>`
			: `<div class="tc-ksnk-alert${
					d.has_template ? " is-info" : " is-warn"
			  }" role="status">${esc(
					d.has_template
						? __(
								"Record first aid and the prophylaxis decision to create the follow-up schedule."
						  )
						: __(
								"No approved follow-up template for this exposure type. Ask the head of infection control to approve one."
						  )
			  )}</div>`;
		const prophylaxis = ["Given", "Not Indicated", "Refused"]
			.map(
				(v) =>
					`<option value="${esc(v)}"${d.prophylaxis === v ? " selected" : ""}>${esc(
						self.opt(v)
					)}</option>`
			)
			.join("");
		const local = (value) => (value ? String(value).replace(" ", "T").slice(0, 16) : "");
		const handling = open
			? `<div class="tc-ksnk-form" data-region="handling">
				<label><input type="checkbox" data-field="first_aid_done"${
					d.first_aid_done ? " checked" : ""
				}> ${esc(__("First aid done"))}</label>
				<label>${esc(
					__("First aid at")
				)}<input type="datetime-local" class="form-control" data-field="first_aid_at" value="${esc(
					local(d.first_aid_at)
			  )}"></label>
				<label>${esc(
					__("Prophylaxis")
				)}<select class="form-control" data-field="prophylaxis"><option value="">${esc(
					__("Choose")
			  )}</option>${prophylaxis}</select></label>
				<label>${esc(
					__("Prophylaxis started at")
				)}<input type="datetime-local" class="form-control" data-field="prophylaxis_started_at" value="${esc(
					local(d.prophylaxis_started_at)
			  )}"></label>
				<button type="button" class="btn btn-primary" data-action="handling">${esc(
					__("Record first aid and prophylaxis")
				)}</button>
			</div>`
			: "";
		const source = d.source_patient_code_masked
			? `${esc(
					d.source_patient_code_masked
			  )} <button type="button" class="btn btn-link btn-sm" data-action="reveal">${esc(
					__("View full code")
			  )}</button> <span data-region="revealed" class="tc-ksnk-code"></span>`
			: esc(self.opt(d.source_known));
		return `<section class="tc-ksnk-card" data-name="${esc(d.name)}">
			<h3><span class="tc-ksnk-code">${esc(d.name)}</span> — ${esc(
			__("follow-up schedule")
		)} ${self.statusBadge(d.status, esc)}</h3>
			<div data-region="detail-alert"></div>
			<table class="tc-ksnk-table"><tbody>
				<tr><th>${esc(__("Employee"))}</th><td>${esc(d.employee_name || "—")} · ${esc(
			d.occupation || ""
		)}</td></tr>
				<tr><th>${esc(__("Type"))}</th><td>${esc(self.opt(d.exposure_type))}</td></tr>
				<tr><th>${esc(__("Occurred At"))}</th><td>${esc(self.date(d.occurred_at))}</td></tr>
				<tr><th>${esc(__("Reported At"))}</th><td>${esc(self.date(d.reported_at))} (${esc(
			self.duration(d.minutes_to_report)
		)})${d.report_late ? self.lateBadge(esc) : ""}</td></tr>
				<tr><th>${esc(__("Activity"))} / ${esc(__("Device"))}</th><td>${esc(d.activity || "—")} / ${esc(
			d.device || "—"
		)}</td></tr>
				<tr><th>${esc(__("Source Patient Code"))}</th><td>${source}</td></tr>
				<tr><th>${esc(__("First Aid"))}</th><td>${esc(
			d.first_aid_done ? __("Recorded {0}", [self.date(d.first_aid_at)]) : __("Not recorded")
		)}</td></tr>
				<tr><th>${esc(__("Prophylaxis"))}</th><td>${esc(self.opt(d.prophylaxis))}${
			d.prophylaxis_started_at ? ` · ${esc(self.date(d.prophylaxis_started_at))}` : ""
		}${d.prophylaxis_late ? self.lateBadge(esc) : ""}</td></tr>
			</tbody></table>
			${handling}
			${schedule}
			${
				open
					? `<p><button type="button" class="btn btn-default btn-sm" data-action="cancel">${esc(
							__("Cancel record (reported by mistake)")
					  )}</button></p>`
					: ""
			}
		</section>`;
	},

	immunizationHtml(rows, esc) {
		const cls = {
			Overdue: "is-fail",
			"Due Soon": "is-warn",
			Scheduled: "is-neutral",
			Complete: "is-pass",
		};
		const label = (r) =>
			r.state === "Due Soon"
				? __("{0} days left", [r.days_left])
				: {
						Overdue: __("Overdue"),
						Scheduled: __("Scheduled"),
						Complete: __("All doses"),
				  }[r.state];
		const body = rows.length
			? rows
					.map(
						(r) => `<tr><td>${esc(r.employee_name || "—")}</td><td>${esc(
							r.department || "—"
						)}</td>
				<td>${esc(r.vaccine)}</td><td class="is-num">${esc(`${r.dose_no}/${r.doses_required || "—"}`)}</td>
				<td>${esc(TcKsnkScr64.date(r.next_due))}</td>
				<td><span class="tc-ksnk-badge ${cls[r.state] || "is-neutral"}">${esc(label(r))}</span></td></tr>`
					)
					.join("")
			: `<tr><td colspan="6">${esc(__("No vaccinations recorded yet."))}</td></tr>`;
		return `<section class="tc-ksnk-card"><h3>${esc(__("Staff vaccination"))}</h3>
			<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Employee"))}</th><th>${esc(
			__("Department")
		)}</th><th>${esc(__("Vaccine"))}</th><th>${esc(__("Dose"))}</th><th>${esc(
			__("Due")
		)}</th><th>${esc(__("Status"))}</th></tr></thead><tbody>${body}</tbody></table>
			<p class="tc-ksnk-note"><a href="/app/staff-immunization">${esc(
				__("Open the vaccination list")
			)}</a></p></section>`;
	},

	pepHtml(alerts, esc) {
		if (!alerts || !alerts.length) return "";
		const lines = alerts
			.map((a) =>
				a.kind === "below_min"
					? __("{0} at {1}: {2} left, minimum {3}", [
							a.item,
							a.warehouse,
							a.qty,
							a.level,
					  ])
					: __("{0} batch {1}: {2} days to expiry", [a.item, a.batch, a.days])
			)
			.map((text) => `<li>${esc(text)}</li>`)
			.join("");
		return `<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
			__("Post-exposure prophylaxis drugs")
		)}</strong><ul>${lines}</ul><a href="/app/query-report/Stock Balance">${esc(
			__("View stock")
		)}</a></div>`;
	},

	actionsHtml(esc) {
		return `<div class="tc-ksnk-actions">
			<a class="btn btn-default" href="${esc(TC_EXP_REPORT)}">${esc(__("Exposure report by period"))}</a>
			<a class="btn btn-default" href="${esc(TC_EXP_PORTAL)}" target="_blank" rel="noopener">${esc(
			__("Open the exposure report screen")
		)}</a>
		</div>`;
	},

	pageHtml(data, esc, detail) {
		const self = TcKsnkScr64;
		if (!data.is_manager) return self.kpisHtml(data.kpis, esc) + self.actionsHtml(esc);
		return (
			self.kpisHtml(data.kpis, esc) +
			self.recordsHtml(data.records || [], esc) +
			`<div class="tc-ksnk-cols"><div data-region="detail">${self.detailHtml(
				detail,
				esc
			)}</div>
			<div>${self.immunizationHtml(data.immunizations || [], esc)}${self.pepHtml(
				data.pep_alerts,
				esc
			)}</div></div>` +
			self.actionsHtml(esc)
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

	values(region) {
		const out = {};
		region.querySelectorAll("[data-field]").forEach((input) => {
			const value = input.type === "checkbox" ? (input.checked ? 1 : 0) : input.value;
			out[input.dataset.field] =
				input.type === "datetime-local" && value ? value.replace("T", " ") + ":00" : value;
		});
		return out;
	},

	async openDetail(el, ctx, data, name) {
		const region = el.querySelector('[data-region="detail"]');
		if (!region) return;
		region.innerHTML = ctx.state("loading");
		try {
			const detail = await ctx.get(TC_EXP_DETAIL, { name });
			if (!ctx.isCurrent()) return;
			TcKsnkScr64.paintDetail(el, ctx, data, detail);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			region.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},

	paintDetail(el, ctx, data, detail) {
		const region = el.querySelector('[data-region="detail"]');
		region.innerHTML = TcKsnkScr64.detailHtml(detail, ctx.esc);
		TcKsnkScr64.bindDetail(el, ctx, data, detail);
	},

	write(el, ctx, data, detail, method, args, button) {
		const alert = el.querySelector('[data-region="detail-alert"]');
		if (button) button.disabled = true;
		tracecore.desk_call({
			method,
			args,
			on_ok: (result) => {
				if (!ctx.isCurrent()) return;
				if (result.source_patient_code !== undefined) {
					const box = el.querySelector('[data-region="revealed"]');
					if (box) box.textContent = result.source_patient_code || "—";
					if (button) button.disabled = false;
					return;
				}
				TcKsnkScr64.paintDetail(el, ctx, data, result.detail || detail);
			},
			on_block: (error) => {
				if (button) button.disabled = false;
				if (alert) alert.innerHTML = TcKsnkScr64.blockHtml(error, ctx.esc);
			},
			on_fail: () => {
				if (button) button.disabled = false;
			},
		});
	},

	askReason(title, done) {
		frappe.prompt(
			[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
			(values) => done(values.reason),
			title,
			__("Confirm")
		);
	},

	bindDetail(el, ctx, data, detail) {
		const self = TcKsnkScr64;
		const region = el.querySelector('[data-region="detail"]');
		if (!region || !detail) return;
		region.querySelectorAll("[data-action]").forEach((button) => {
			button.addEventListener("click", () => {
				const action = button.dataset.action;
				if (action === "handling") {
					const form = region.querySelector('[data-region="handling"]');
					self.write(
						el,
						ctx,
						data,
						detail,
						TC_EXP_HANDLING,
						{ name: detail.name, ...self.values(form) },
						button
					);
				} else if (action === "step-done") {
					const input = region.querySelector(`[data-step-date="${button.dataset.row}"]`);
					self.write(
						el,
						ctx,
						data,
						detail,
						TC_EXP_STEP_DONE,
						{
							name: detail.name,
							row: button.dataset.row,
							done_on: (input && input.value) || "",
						},
						button
					);
				} else if (action === "reveal") {
					self.askReason(__("Why do you need the full patient code?"), (reason) =>
						self.write(
							el,
							ctx,
							data,
							detail,
							TC_EXP_REVEAL,
							{ name: detail.name, reason },
							button
						)
					);
				} else if (action === "cancel") {
					self.askReason(__("Cancel this exposure record"), (reason) =>
						self.write(
							el,
							ctx,
							data,
							detail,
							TC_EXP_CANCEL,
							{ name: detail.name, reason },
							button
						)
					);
				}
			});
		});
	},

	bind(el, ctx, data) {
		el.querySelectorAll('[data-action="open"]').forEach((button) =>
			button.addEventListener("click", () =>
				TcKsnkScr64.openDetail(el, ctx, data, button.dataset.name)
			)
		);
		el.querySelectorAll('[data-action="retry"]').forEach((button) =>
			button.addEventListener("click", () => TcKsnkScr64.render(el, ctx))
		);
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_EXP_DASHBOARD, {});
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr64.pageHtml(data, ctx.esc, null);
			TcKsnkScr64.bind(el, ctx, data);
			const wanted = new URLSearchParams(window.location.search).get("exposure");
			if (wanted && data.is_manager) TcKsnkScr64.openDetail(el, ctx, data, wanted);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
			TcKsnkScr64.bind(el, ctx, null);
		}
	},
};

window.TcKsnkScreens["phoi-nhiem"] = TcKsnkScr64;
window.TcKsnkScr64 = TcKsnkScr64;
