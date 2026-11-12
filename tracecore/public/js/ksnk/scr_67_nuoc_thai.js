/* global tracecore, TcKsnk */
// SCR-67 Nước thải y tế — view WEB trong Page tc-ksnk (FEAT-095; UC-58; FR-M15-08..13; BRU-ENV-003..006; A-153 §3.4,
// bổ sung 12/11/2026: làm giống bản mẫu). Khối: KPI · thẻ GPMT hiện hành + Cần xử lý · lưới lịch điểm × kỳ 12 tháng ·
// bảng đợt gần nhất (kèm dòng NC / việc tiếp theo). Thanh thao tác cố định ở đáy, luôn đủ 3 nút: Ghi đợt quan trắc
// (cửa sổ ngay trên màn) · Xuất báo cáo (cửa sổ, tải Excel/PDF) · Cập nhật GPMT (R01, tạo phiên bản mới). Nút không dùng
// được thì mờ và có lý do bằng chữ. Lỗi chặn = alert inline (kết quả → lý do → hành động); trạng thái luôn có chữ.

const TC_WW_OVERVIEW = "tracecore.v1.wastewater.overview";
const TC_WW_PARAMETERS = "tracecore.v1.wastewater.parameters";
const TC_WW_RECORD = "tracecore.v1.wastewater.record_round";
const TC_WW_EXPORT = "/api/method/tracecore.v1.wastewater.export_report";
const TC_WW_NEW_VERSION = "tracecore.v1.wastewater.new_permit_version";
const TC_WW_OPEN_NC = "tracecore.v1.wastewater.open_nc";
const TC_WW_DISMISS_NC = "tracecore.v1.wastewater.dismiss_nc";

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

	// Số người dùng gõ: dấu phẩy là thập phân, dấu chấm là phân cách nghìn khi có dấu phẩy ("1.234,5" → 1234.5)
	parse(raw) {
		let text = String(raw === null || raw === undefined ? "" : raw).trim();
		if (!text) return NaN;
		if (text.includes(",")) text = text.replace(/\./g, "").replace(",", ".");
		return Number(text);
	},

	// Cùng luật với server (BRU-ENV-005): pass / fail / none (chưa nhập)
	judge(limit, raw, kph) {
		const low = Number(limit.min_value) || 0;
		const high = Number(limit.max_value) || 0;
		if (kph) return low ? "fail" : "pass";
		const value = TcKsnkScr67.parse(raw);
		if (Number.isNaN(value) || value === 0) return "none";
		if (limit.detect_only) return value > 0 ? "fail" : "pass";
		if (high && value > high) return "fail";
		if (low && value < low) return "fail";
		return "pass";
	},

	badge(cls, label, esc) {
		return `<span class="tc-ksnk-badge is-${cls}">${esc(label)}</span>`;
	},

	desk(doctype, name, label, esc) {
		return `<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(
			name
		)}"><span class="tc-ksnk-code">${esc(label || name)}</span></a>`;
	},

	cellHtml(cell, esc) {
		const self = TcKsnkScr67;
		const labels = {
			done: __("Monitored"),
			fail: __("Failed"),
			miss: __("Missing parameters"),
			due: __("Due"),
			over: __("Overdue"),
			future: __("Not yet due"),
			na: __("Not applicable"),
			none: __("No permit"),
		};
		const status = labels[cell.status] ? cell.status : "none";
		let note = "";
		if (status === "due" && cell.days_left !== null && cell.days_left !== undefined)
			note = __("{0} days left", [cell.days_left]);
		else if (status === "na") note = __("automatic monitoring");
		else if (status === "over") note = __("no round");
		else if (cell.missing && cell.missing.length && status !== "done")
			note = __("missing {0}", [cell.missing.join(", ")]);
		else if (cell.date) note = __("sampled {0}", [self.date(cell.date)]);
		return `<span class="tc-ww-cell is-${status}">${esc(labels[status])}${
			note ? `<small>${esc(note)}</small>` : ""
		}</span>`;
	},

	kpisHtml(data, esc) {
		const k = data.kpis || {};
		const tile = (cls, value, label) =>
			`<div class="tc-ksnk-kpi${cls ? ` is-${cls}` : ""}"><strong>${esc(
				value
			)}</strong><span>${esc(label)}</span></div>`;
		const rate = k.total_periods ? `${Math.round((k.on_time * 100) / k.total_periods)}%` : "—";
		return (
			`<div class="tc-ksnk-kpis tc-ww-kpis">` +
			tile("", k.points || 0, __("Periodic monitoring points")) +
			tile(
				k.on_time < k.total_periods ? "warn" : "pass",
				rate,
				__("Periods on time in {0} ({1}/{2})", [
					data.year,
					k.on_time || 0,
					k.total_periods || 0,
				])
			) +
			tile(k.overdue ? "fail" : "", k.overdue || 0, __("Periods overdue")) +
			tile(
				k.flagged ? "fail" : "",
				k.flagged || 0,
				__("Points exceeded – awaiting re-monitoring")
			) +
			tile(
				"warn",
				k.days_left_period === null || k.days_left_period === undefined
					? "—"
					: k.days_left_period,
				__("Days left in current period")
			) +
			`</div>`
		);
	},

	permitHtml(data, esc) {
		const self = TcKsnkScr67;
		const permits = data.permits || [];
		if (!permits.length)
			return `<section class="tc-ksnk-card"><h3>${esc(
				__("Environmental permit in effect")
			)}</h3><p class="tc-ksnk-state is-empty">${esc(
				__(
					"No approved environmental permit yet. Monitoring schedule and limits come from the hospital's environmental permit."
				)
			)}</p><p class="tc-ksnk-note">${esc(
				data.can_permit
					? __(
							"Use Update permit below to declare the permit, its points and parameters."
					  )
					: __("Ask the head of infection control (R01) to declare the permit.")
			)}</p></section>`;
		return permits
			.map((p) => {
				const state = p.expiring
					? self.badge(
							p.days_to_expiry < 0 ? "fail" : "warn",
							p.days_to_expiry < 0
								? __("Expired")
								: __("{0} days left", [p.days_to_expiry]),
							esc
					  )
					: self.badge("pass", __("In effect"), esc);
				const item = (label, value, mono) =>
					`<div><span>${esc(label)}</span><strong${
						mono ? ' class="tc-ksnk-code"' : ""
					}>${esc(value || "—")}</strong></div>`;
				return `<section class="tc-ksnk-card"><h3>${esc(
					__("Environmental permit in effect")
				)} ${state} <span class="tc-ksnk-tag">${esc(p.name)}</span>${
					p.previous
						? `<span class="tc-ww-spacer"></span><a class="tc-ww-link" href="/app/wastewater-permit/${encodeURIComponent(
								p.previous
						  )}">${esc(__("Previous version: {0}", [p.previous]))}</a>`
						: ""
				}</h3><div class="tc-ww-permit">${item(__("Permit No"), p.permit_no, true)}${item(
					__("Standard · Column"),
					`${p.standard} · ${p.standard_column}`
				)}${item(
					__("Version effective"),
					__("from {0}", [self.date(p.effective_from)])
				)}${item(__("Valid Until"), self.date(p.valid_until))}${item(
					__("Issuing Authority"),
					p.issuing_authority
				)}${item(__("Factor Note"), p.factor_note)}</div>${
					data.drafts
						? `<p class="tc-ksnk-alert is-warn">${esc(
								__(
									"{0} draft permit version(s) — awaiting approval by the head of infection control.",
									[data.drafts]
								)
						  )}</p>`
						: ""
				}</section>`;
			})
			.join("");
	},

	attentionHtml(data, esc) {
		const self = TcKsnkScr67;
		const items = [];
		(data.flagged || []).forEach((f) => {
			const decide = data.can_decide && f.nc_status === "Suggested";
			items.push(`<div class="tc-ksnk-alert" role="alert" data-region="nc-${esc(
				f.monitoring
			)}">
				<strong>${esc(`${f.point} · ${__("Exceeded – awaiting re-monitoring")}.`)}</strong>
				<div>${esc(
					__("Round {0} sampled {1}: {2} exceeded the permit limits.", [
						f.monitoring,
						self.date(f.sampled_on),
						(f.failed || []).join(", ") || "—",
					])
				)} ${esc(
				f.nc_name
					? __("Non-conformance {0} is open.", [f.nc_name])
					: __("Infection control, R11 and the responsible person were notified.")
			)}</div>${
				decide
					? `<div class="tc-ksnk-actions"><button type="button" class="btn btn-danger btn-sm" data-action="open-nc" data-name="${esc(
							f.monitoring
					  )}">${esc(__("Open Environment NC"))}</button>
					<button type="button" class="btn btn-default btn-sm" data-action="dismiss-nc" data-name="${esc(
						f.monitoring
					)}">${esc(__("No NC needed"))}</button></div>`
					: ""
			}<div data-region="nc-alert"></div></div>`);
		});
		(data.schedule || []).forEach((row) =>
			(row.periods || [])
				.filter((c) => c.status === "over" || (c.status === "miss" && c.end < data.today))
				.forEach((c) =>
					items.push(
						`<div class="tc-ksnk-alert${
							c.status === "over" ? "" : " is-warn"
						}" role="status"><strong>${esc(
							`${row.point} · ${c.label} — ${
								c.status === "over" ? __("Overdue") : __("Missing parameters")
							}`
						)}</strong> ${esc(
							c.status === "over"
								? __("No monitoring round in this period.")
								: __("Missing: {0}. The period does not count as monitored.", [
										(c.missing || []).join(", "),
								  ])
						)}</div>`
					)
				)
		);
		(data.labs || [])
			.filter((lab) => lab.expired || lab.expiring)
			.forEach((lab) =>
				items.push(
					`<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
						lab.supplier_name
					)}</strong> — ${esc(
						lab.expired
							? __(
									"{0} expired on {1} — cannot be chosen for samples taken after this date.",
									[lab.vimcerts_no, self.date(lab.valid_until)]
							  )
							: __("{0} expires on {1}.", [
									lab.vimcerts_no,
									self.date(lab.valid_until),
							  ])
					)}</div>`
				)
			);
		return `<section class="tc-ksnk-card"><h3>${esc(__("Needs attention"))}</h3>${
			items.length
				? items.join("")
				: `<p class="tc-ksnk-state is-empty">${esc(__("Nothing to handle."))}</p>`
		}</section>`;
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

	scheduleHtml(data, esc) {
		const self = TcKsnkScr67;
		const [ty, tm] = String(data.today || "")
			.split("-")
			.map(Number);
		const thisYear = ty === Number(data.year);
		const head = Array.from({ length: 12 }, (_v, i) => i + 1)
			.map(
				(m) =>
					`<th class="tc-ww-month"${
						thisYear && tm === m ? ' aria-current="date"' : ""
					}>${esc(__("M{0}", [m]))}${thisYear && tm === m ? " ▾" : ""}</th>`
			)
			.join("");
		const body = (data.schedule || [])
			.map((row) => {
				const span = row.periods.length === 1 ? 12 : row.frequency || 12;
				const cells = (row.periods || [])
					.map(
						(c) =>
							`<td colspan="${span}"${
								c.start <= data.today && data.today <= c.end
									? ' class="is-current"'
									: ""
							}>${self.cellHtml(c, esc)}</td>`
					)
					.join("");
				return `<tr><td class="tc-ww-point"><b class="tc-ksnk-code">${esc(
					row.point
				)}</b> ${esc(row.point_name)}${
					row.awaiting_remonitor
						? `<br><span class="tc-ww-flag">⚑ ${esc(
								__("Exceeded – awaiting re-monitoring")
						  )}</span>`
						: ""
				}<small>${esc(
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
		const legend = ["done", "fail", "miss", "due", "over", "na"]
			.map((status) => self.cellHtml({ status, missing: [] }, esc))
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Monitoring schedule {0}", [data.year])
		)} <span class="tc-ksnk-tag">${esc(
			__("point × period")
		)}</span><span class="tc-ww-spacer"></span><select class="form-control tc-ww-year" data-filter="year" aria-label="${esc(
			__("Year")
		)}">${self.yearOptions(data.year, esc)}</select></h3>
		<div class="tc-ksnk-scroll"><table class="tc-ksnk-table tc-ww-sched"><thead><tr><th>${esc(
			__("Point")
		)}</th><th>${esc(__("Frequency"))}</th>${head}</tr></thead><tbody>${
			body ||
			`<tr class="is-empty"><td colspan="14" class="tc-ksnk-note">${esc(
				__("No monitoring point yet.")
			)}</td></tr>`
		}</tbody></table></div>
		<div class="tc-ww-legend">${legend}<span>${esc(
			__("Outlined cell = current period. Status always has text, not only colour.")
		)}</span></div></section>`;
	},

	resultCell(row, inlet, esc) {
		const self = TcKsnkScr67;
		if (!row) return `<td class="is-num">—</td>`;
		const value = row.below_detection
			? __("Not detected")
			: row.value
			? self.num(row.value)
			: "";
		if (inlet) return `<td class="is-num">${esc(value || "—")}</td>`;
		if (!value) return `<td class="is-num tc-ww-missing">${esc(__("Missing"))}</td>`;
		if (row.result === "Fail")
			return `<td class="is-num tc-ww-fail">${esc(value)} ${self.badge(
				"fail",
				`✕ ${__("Exceeded")}`,
				esc
			)}</td>`;
		return `<td class="is-num">${esc(value)}</td>`;
	},

	overallBadge(result, esc) {
		const self = TcKsnkScr67;
		return (
			{
				Pass: self.badge("pass", __("Pass"), esc),
				Fail: self.badge("fail", __("Fail"), esc),
				Incomplete: self.badge("warn", __("Missing parameters"), esc),
				"Reference Only": self.badge("neutral", __("Reference only"), esc),
			}[result] || ""
		);
	},

	nextStepHtml(data, round, esc) {
		const self = TcKsnkScr67;
		if (round.overall_result === "Fail") {
			const nc = round.nc_name
				? `<span class="tc-ksnk-code">${esc(round.nc_name)}</span> ${self.badge(
						"warn",
						__("In progress"),
						esc
				  )}`
				: self.badge("warn", __("NC suggested"), esc);
			return `${nc}${
				data.can_record
					? `<br><button type="button" class="btn btn-default btn-sm" data-action="remonitor" data-point="${esc(
							round.wastewater_point
					  )}" data-name="${esc(round.name)}">${esc(
							__("Record re-monitoring")
					  )}</button>`
					: ""
			}`;
		}
		if (
			round.overall_result === "Incomplete" &&
			(round.missing || []).length &&
			data.can_record
		)
			return `<button type="button" class="btn btn-default btn-sm" data-action="supplement" data-point="${esc(
				round.wastewater_point
			)}">${esc(__("Supplement {0}", [round.missing.join(", ")]))}</button>`;
		return "—";
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
		const permit = (data.permits || [])[0];
		const heads = latest
			.map(
				(r) =>
					`<th>${esc(r.wastewater_point)}<br><small>${esc(
						self.date(r.sampled_on)
					)}</small></th>`
			)
			.join("");
		const body = params
			.map(
				(p) =>
					`<tr><td>${esc(p.parameter)}</td><td>${esc(
						p.unit || ""
					)}</td><td class="is-num">${esc(p.limit_text || "—")}</td>${latest
						.map((r) =>
							self.resultCell(
								(r.results || []).find((x) => x.parameter === p.parameter),
								r.point_type === "Inlet",
								esc
							)
						)
						.join("")}</tr>`
			)
			.join("");
		const row = (label, cells) =>
			`<tr class="tc-ww-sum"><td colspan="3">${label}</td>${cells}</tr>`;
		return `<section class="tc-ksnk-card"><h3>${esc(__("Latest round by point"))}${
			permit
				? ` <span class="tc-ksnk-tag">${esc(__("limits from {0}", [permit.name]))}</span>`
				: ""
		}</h3>
		<div class="tc-ksnk-scroll"><table class="tc-ksnk-table tc-ww-results"><thead><tr><th>${esc(
			__("Parameter")
		)}</th><th>${esc(__("Unit"))}</th><th>${esc(
			__("Limit")
		)}</th>${heads}</tr></thead><tbody>${body}
		${row(
			`<strong>${esc(__("Round result"))}</strong>`,
			latest.map((r) => `<td>${self.overallBadge(r.overall_result, esc)}</td>`).join("")
		)}
		${row(
			esc(__("Report no · monitoring unit")),
			latest
				.map(
					(r) =>
						`<td>${self.desk("Wastewater Monitoring", r.name, r.name, esc)}<br>${esc(
							r.supplier_name || ""
						)}<br>${esc(`${r.vimcerts_no || ""} · ${r.report_no || ""}`)}</td>`
				)
				.join("")
		)}
		${row(
			esc(__("NC / next step")),
			latest.map((r) => `<td>${self.nextStepHtml(data, r, esc)}</td>`).join("")
		)}</tbody></table></div>
		<p class="tc-ksnk-note">${esc(
			__(
				"Not detected passes against an upper limit. Inlet values are for reference only. Each round keeps a snapshot of the permit limits in effect on its sampling date."
			)
		)}</p></section>`;
	},

	// Thanh thao tác cố định ở đáy: luôn 3 nút; nút không dùng được thì mờ + lý do bằng chữ
	actionsHtml(data, esc) {
		const hasPermit = (data.permits || []).length > 0;
		const canRecord = data.can_record && hasPermit;
		let hint = "";
		if (!data.can_record && !data.can_permit) hint = __("This role can only view.");
		else if (!hasPermit) hint = __("No approved permit yet — declare the permit first.");
		else if (!data.can_permit)
			hint = __("Only the head of infection control (R01) updates the permit.");
		const button = (action, cls, label, enabled) =>
			`<button type="button" class="btn ${cls}" data-action="${action}"${
				enabled ? "" : " disabled"
			}>${esc(label)}</button>`;
		return `<div class="tc-ww-actions">${button(
			"record",
			"btn-primary",
			`＋ ${__("Record monitoring round")}`,
			canRecord
		)}${button("export", "btn-default", `⤓ ${__("Export report")}`, true)}${button(
			"permit",
			"btn-default",
			`✎ ${__("Update permit")}`,
			data.can_permit
		)}<span class="tc-ww-hint">${esc(hint)}</span></div>`;
	},

	pageHtml(data, esc) {
		const self = TcKsnkScr67;
		if (data.summary_only)
			return (
				self.kpisHtml(data, esc) +
				`<section class="tc-ksnk-card"><h3>${esc(
					__("Summary for the board of directors")
				)}</h3><p>${esc(
					__(
						"{0}: {1}/{2} periodic monitoring periods done on time; {3} point(s) exceeded limits.",
						[
							data.year,
							(data.kpis || {}).on_time || 0,
							(data.kpis || {}).total_periods || 0,
							(data.kpis || {}).flagged || 0,
						]
					)
				)}</p><p class="tc-ksnk-alert is-info">${esc(
					__(
						"Summary view. Round details and result reports are managed by the infection control department."
					)
				)}</p></section>`
			);
		return (
			`<div class="tc-ww">` +
			self.kpisHtml(data, esc) +
			`<div class="tc-ww-two"><div>${self.permitHtml(
				data,
				esc
			)}</div><div>${self.attentionHtml(data, esc)}</div></div>` +
			self.scheduleHtml(data, esc) +
			self.latestHtml(data, esc) +
			self.actionsHtml(data, esc) +
			`</div>`
		);
	},

	// --- cửa sổ Ghi đợt quan trắc (FR-M15-10, .1, FR-M15-13) ---------------------------------------------------------

	labOptions(labs, onDate, esc) {
		const self = TcKsnkScr67;
		return (labs || [])
			.map((lab) => {
				const expired =
					lab.valid_until && onDate && String(lab.valid_until) < String(onDate);
				return `<option value="${esc(lab.supplier)}"${expired ? " disabled" : ""}>${esc(
					`${lab.supplier_name} · ${lab.vimcerts_no} · ${__("until {0}", [
						self.date(lab.valid_until),
					])}${expired ? ` (${__("expired")})` : ""}`
				)}</option>`;
			})
			.join("");
	},

	paramRowsHtml(params, esc) {
		return (params || [])
			.map(
				(p, i) => `<tr data-index="${i}"><td>${esc(p.parameter)}</td><td>${esc(
					p.unit || ""
				)}</td><td class="is-num">${esc(p.limit_text || "—")}</td>
				<td><input class="form-control tc-ww-value" data-index="${i}" data-param="${esc(
					p.parameter
				)}" inputmode="decimal" aria-label="${esc(__("Value of {0}", [p.parameter]))}"${
					p.detect_only ? " disabled" : ""
				}></td>
				<td><label class="tc-ww-kph"><input type="checkbox" data-index="${i}" data-kph="${esc(
					p.parameter
				)}"${p.detect_only ? " checked" : ""}> ${esc(__("Not detected"))}</label></td>
				<td data-result="${i}">${
					p.detect_only
						? TcKsnkScr67.badge("pass", __("Pass"), esc)
						: `<span class="tc-ww-missing">${esc(__("Not entered"))}</span>`
				}</td></tr>`
			)
			.join("");
	},

	summaryHtml(counts, esc) {
		const self = TcKsnkScr67;
		const note = counts.fail
			? `<strong class="tc-ww-fail-text">${esc(
					__(
						"→ The round will fail: the point is flagged, people are notified and a non-conformance is suggested."
					)
			  )}</strong>`
			: counts.missing
			? `<span class="tc-ww-missing">${esc(
					__(
						"Not all parameters entered: the round has missing parameters and the period does not count as monitored."
					)
			  )}</span>`
			: `<strong class="tc-ww-pass-text">${esc(__("→ The round passes."))}</strong>`;
		return `${self.badge("pass", __("{0} passed", [counts.pass]), esc)} ${self.badge(
			"fail",
			__("{0} exceeded", [counts.fail]),
			esc
		)} ${self.badge("warn", __("{0} not entered", [counts.missing]), esc)} ${note}`;
	},

	recordDialog(data, ctx, opts = {}) {
		const self = TcKsnkScr67;
		const esc = ctx.esc;
		const today = data.today || frappe.datetime.get_today();
		const state = { params: [], permit: null };
		const points = (data.points || [])
			.map(
				(p) =>
					`<option value="${esc(p.point)}"${
						p.point === opts.point ? " selected" : ""
					}>${esc(`${p.point} · ${p.point_name}`)}</option>`
			)
			.join("");
		const dialog = new frappe.ui.Dialog({
			title: opts.remonitor
				? __("Record re-monitoring round")
				: __("Record wastewater monitoring round"),
			size: "extra-large",
			fields: [
				{
					fieldname: "head",
					fieldtype: "HTML",
					options: `<p class="text-muted">${esc(
						__(
							"Parameters and limits load from the permit in effect on the sampling date. Each result keeps a snapshot of the limit."
						)
					)}</p><div class="tc-ww-form">
					<label>${esc(__("Point"))} *<select class="form-control" data-f="point">${points}</select></label>
					<label>${esc(
						__("Sampling date")
					)} *<input type="date" class="form-control" data-f="date" value="${esc(
						today
					)}" max="${esc(today)}"></label>
					<label>${esc(__("Period"))}<input class="form-control" data-f="period" readonly></label>
					<label>${esc(
						__("Monitoring unit (VIMCERTS)")
					)} *<select class="form-control" data-f="lab"></select></label>
					<label>${esc(
						__("Result report no")
					)} *<input class="form-control" data-f="report" placeholder="${esc(
						__("e.g. 2611/KQ-QTMT")
					)}"></label></div>${
						opts.remonitor
							? `<p class="tc-ksnk-alert is-info">${esc(
									__("Re-monitoring of failed round {0}.", [opts.remonitor])
							  )}</p>`
							: ""
					}`,
				},
				{
					fieldname: "attachment",
					fieldtype: "Attach",
					label: __("Result report file (PDF or image)"),
					description: __("Required to post."),
				},
				{ fieldname: "table", fieldtype: "HTML" },
				{ fieldname: "alert", fieldtype: "HTML" },
			],
			primary_action_label: __("Post round"),
			primary_action: () => save(1),
			secondary_action_label: __("Save draft"),
			secondary_action: () => save(0),
		});
		const body = dialog.$wrapper[0];
		const pick = (name) => body.querySelector(`[data-f="${name}"]`);
		const alertBox = () => dialog.fields_dict.alert.$wrapper[0];
		const evaluate = () => {
			const counts = { pass: 0, fail: 0, missing: 0 };
			state.params.forEach((p, i) => {
				const kph = body.querySelector(`input[data-kph][data-index="${i}"]`).checked;
				const raw = body.querySelector(`input.tc-ww-value[data-index="${i}"]`).value;
				const verdict = self.judge(p, raw, kph);
				const cell = body.querySelector(`[data-result="${i}"]`);
				if (verdict === "fail") {
					counts.fail += 1;
					cell.innerHTML = self.badge("fail", `✕ ${__("Exceeded")}`, esc);
				} else if (verdict === "pass") {
					counts.pass += 1;
					cell.innerHTML = self.badge("pass", __("Pass"), esc);
				} else {
					counts.missing += 1;
					cell.innerHTML = `<span class="tc-ww-missing">${esc(
						__("Not entered")
					)}</span>`;
				}
			});
			const sum = body.querySelector("[data-region='ww-sum']");
			if (sum) sum.innerHTML = self.summaryHtml(counts, esc);
		};
		const renderTable = (result) => {
			state.params = result.results || [];
			state.permit = result.permit;
			pick("period").value = result.period_label || "";
			dialog.fields_dict.table.$wrapper.html(
				result.permit
					? `<p class="tc-ksnk-alert is-info">${esc(
							__("Applies {0} · {1}", [result.permit, result.standard])
					  )}</p><div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr><th>${esc(
							__("Parameter")
					  )}</th><th>${esc(__("Unit"))}</th><th>${esc(__("Limit"))}</th><th>${esc(
							__("Value")
					  )}</th><th>${esc(__("Not detected"))}</th><th>${esc(
							__("Result")
					  )}</th></tr></thead><tbody>${self.paramRowsHtml(
							state.params,
							esc
					  )}</tbody></table></div><div class="tc-ww-sum-line" data-region="ww-sum"></div>`
					: self.blockHtml(
							{
								title: __("No permit in effect"),
								reason: __(
									"No approved environmental permit covers this point on the sampling date."
								),
								action: __(
									"Ask the head of infection control to approve the permit for this point."
								),
							},
							esc
					  )
			);
			body.querySelectorAll("input[data-kph]").forEach((box) =>
				box.addEventListener("change", () => {
					const input = body.querySelector(
						`input.tc-ww-value[data-index="${box.dataset.index}"]`
					);
					input.disabled = box.checked;
					if (box.checked) input.value = "";
					evaluate();
				})
			);
			body.querySelectorAll("input.tc-ww-value").forEach((input) =>
				input.addEventListener("input", evaluate)
			);
			evaluate();
		};
		const load = () => {
			pick("lab").innerHTML = self.labOptions(data.labs, pick("date").value, esc);
			frappe.call({
				method: TC_WW_PARAMETERS,
				type: "GET",
				args: { point: pick("point").value, sampled_on: pick("date").value },
				callback: (r) => renderTable(r.message || {}),
			});
		};
		const save = (submit) => {
			const results = state.params.map((p, i) => {
				const kph = body.querySelector(`input[data-kph][data-index="${i}"]`).checked;
				const value = self.parse(
					body.querySelector(`input.tc-ww-value[data-index="${i}"]`).value
				);
				return {
					parameter: p.parameter,
					below_detection: kph ? 1 : 0,
					value: kph || Number.isNaN(value) ? 0 : value,
				};
			});
			self.post(
				TC_WW_RECORD,
				{
					point: pick("point").value,
					sampled_on: pick("date").value,
					supplier: pick("lab").value,
					report_no: pick("report").value,
					attachment: dialog.get_value("attachment") || "",
					results: JSON.stringify(results),
					is_remonitor_of: opts.remonitor || "",
					submit,
				},
				{
					success: submit ? __("Round posted.") : __("Draft round saved."),
					on_ok: (result) => {
						dialog.hide();
						if (result.overall_result === "Fail" && result.docstatus === 1)
							self.ncDialog(result, ctx);
						else if (ctx.isCurrent()) self.render(ctx.el, ctx);
					},
					on_block: (error) => {
						alertBox().innerHTML = self.blockHtml(error, esc);
					},
				}
			);
		};
		pick("point").addEventListener("change", load);
		pick("date").addEventListener("change", load);
		dialog.$wrapper.find(".modal-body").addClass("tc-ksnk");
		dialog.show();
		load();
		return dialog;
	},

	ncDialog(result, ctx) {
		const self = TcKsnkScr67;
		const esc = ctx.esc;
		const text = __(
			"Posted. The point is flagged as exceeded – awaiting re-monitoring; R01, R11 and the responsible person were notified and a re-monitoring task was created."
		);
		const dialog = new frappe.ui.Dialog({
			title: __("Monitoring round failed"),
			fields: [
				{
					fieldname: "info",
					fieldtype: "HTML",
					options: `<div class="tc-ksnk-alert" role="alert">${esc(text)}</div><p>${esc(
						result.can_decide
							? __("A non-conformance (Environment) is suggested.")
							: __(
									"Opening a non-conformance is decided by R01 — the suggestion was sent to the head of infection control."
							  )
					)}</p>`,
				},
				...(result.can_decide
					? [
							{
								fieldname: "reason",
								fieldtype: "Small Text",
								label: __(
									"Reason for no NC (required to dismiss — recorded in the audit log)"
								),
							},
							{ fieldname: "alert", fieldtype: "HTML" },
					  ]
					: []),
			],
			primary_action_label: result.can_decide ? __("Open NC") : __("Close"),
			primary_action: () => {
				if (!result.can_decide) {
					dialog.hide();
					return self.render(ctx.el, ctx);
				}
				self.post(TC_WW_OPEN_NC, { monitoring: result.name }, done(false));
			},
			...(result.can_decide
				? {
						secondary_action_label: __("No NC needed"),
						secondary_action: () =>
							self.post(
								TC_WW_DISMISS_NC,
								{
									monitoring: result.name,
									reason: dialog.get_value("reason") || "",
								},
								done(undefined)
							),
				  }
				: {}),
		});
		function done(success) {
			return {
				success,
				on_ok: (r) => {
					dialog.hide();
					if (r.incident)
						frappe.show_alert({
							message: __("Incident {0} opened.", [r.incident]),
							indicator: "green",
						});
					if (ctx.isCurrent()) self.render(ctx.el, ctx);
				},
				on_block: (error) => {
					dialog.fields_dict.alert.$wrapper.html(self.blockHtml(error, esc));
				},
			};
		}
		dialog.$wrapper.find(".modal-body").addClass("tc-ksnk");
		dialog.show();
		return dialog;
	},

	// --- cửa sổ Xuất báo cáo (FR-M15-12) ------------------------------------------------------------------------------

	exportDialog(data) {
		const year = data.year;
		const scopes = [{ value: String(year), label: __("Year {0}", [year]) }].concat(
			[4, 3, 2, 1].map((q) => ({
				value: `${year}-Q${q}`,
				label: __("Quarter {0}/{1}", [q, year]),
			}))
		);
		const dialog = new frappe.ui.Dialog({
			title: __("Export wastewater report"),
			fields: [
				{ fieldname: "scope", fieldtype: "Select", label: __("Scope"), options: scopes },
				{ fieldname: "col1", fieldtype: "Column Break" },
				{
					fieldname: "point",
					fieldtype: "Select",
					label: __("Point"),
					options: [{ value: "", label: __("All points") }].concat(
						(data.points || []).map((p) => ({ value: p.point, label: p.point }))
					),
				},
				{ fieldname: "col2", fieldtype: "Column Break" },
				{
					fieldname: "fmt",
					fieldtype: "Select",
					label: __("Format"),
					options: [
						{ value: "xlsx", label: "Excel (.xlsx)" },
						{ value: "pdf", label: "PDF" },
					],
				},
				{ fieldname: "sec", fieldtype: "Section Break" },
				{
					fieldname: "note",
					fieldtype: "HTML",
					options: `<p class="tc-ksnk-alert is-info">${frappe.utils.escape_html(
						__(
							"Point × parameter × round with limits and number of exceedances — an annex for the yearly environmental protection report. TraceCore only exports the data; it does not submit it."
						)
					)}</p>`,
				},
			],
			primary_action_label: __("Export"),
			primary_action: (values) => {
				const query = new URLSearchParams({
					scope: values.scope || String(year),
					point: values.point || "",
					fmt: values.fmt || "xlsx",
				});
				window.open(`${TC_WW_EXPORT}?${query.toString()}`);
				dialog.hide();
			},
		});
		dialog.set_value("scope", String(year));
		dialog.set_value("fmt", "xlsx");
		dialog.$wrapper.find(".modal-body").addClass("tc-ksnk");
		dialog.show();
		return dialog;
	},

	// --- cửa sổ Cập nhật GPMT (FR-M15-08, .1) -------------------------------------------------------------------------

	permitDialog(data, ctx) {
		const self = TcKsnkScr67;
		const esc = ctx.esc;
		const permit = (data.permits || [])[0];
		if (!permit) {
			frappe.set_route("Form", "Wastewater Permit", "new");
			return null;
		}
		const next = (Number(permit.version_no) || 1) + 1;
		const dialog = new frappe.ui.Dialog({
			title: __("Update environmental permit"),
			fields: [
				{
					fieldname: "info",
					fieldtype: "HTML",
					options: `<div class="tc-ksnk-alert is-warn">${esc(
						__(
							"{0} is approved and locked. Saving changes creates new version V{1}; the current version stays unchanged and points to the new one. Rounds already recorded keep their results.",
							[permit.name, next]
						)
					)}</div><p>${esc(
						__(
							"The draft opens in the permit form: edit the permit number, standard, column, effective date, scan and the parameter rows (point, parameter, limits, frequency, automatic monitoring), then post to approve."
						)
					)}</p><p><a href="/app/wastewater-permit/new">${esc(
						__("Declare another permit instead")
					)}</a></p>`,
				},
				{ fieldname: "alert", fieldtype: "HTML" },
			],
			primary_action_label: __("Create version V{0}", [next]),
			primary_action: () =>
				self.post(
					TC_WW_NEW_VERSION,
					{ permit: permit.name },
					{
						success: false,
						on_ok: (result) => {
							dialog.hide();
							frappe.set_route("Form", "Wastewater Permit", result.name);
						},
						on_block: (error) =>
							dialog.fields_dict.alert.$wrapper.html(self.blockHtml(error, esc)),
					}
				),
		});
		dialog.$wrapper.find(".modal-body").addClass("tc-ksnk");
		dialog.show();
		return dialog;
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

	bind(el, ctx, data) {
		const self = TcKsnkScr67;
		ctx.el = el;
		const year = el.querySelector('[data-filter="year"]');
		if (year)
			year.addEventListener("change", () => {
				ctx.setFilters({ year: year.value });
				self.render(el, ctx);
			});
		const offline = typeof navigator !== "undefined" && navigator.onLine === false;
		el.querySelectorAll(".tc-ww-actions button").forEach((button) => {
			if (offline && button.dataset.action !== "export") button.disabled = true;
		});
		const on = (selector, fn) =>
			el
				.querySelectorAll(selector)
				.forEach((button) => button.addEventListener("click", () => fn(button)));
		on('[data-action="record"]', () => self.recordDialog(data, ctx));
		on('[data-action="remonitor"]', (b) =>
			self.recordDialog(data, ctx, { point: b.dataset.point, remonitor: b.dataset.name })
		);
		on('[data-action="supplement"]', (b) =>
			self.recordDialog(data, ctx, { point: b.dataset.point })
		);
		on('[data-action="export"]', () => self.exportDialog(data));
		on('[data-action="permit"]', () => self.permitDialog(data, ctx));
		on('[data-action="open-nc"], [data-action="dismiss-nc"]', (button) => {
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
		});
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_WW_OVERVIEW, { year: ctx.filters.year || "" });
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr67.pageHtml(data, ctx.esc);
			TcKsnkScr67.bind(el, ctx, data);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkScreens["nuoc-thai"] = TcKsnkScr67;
window.TcKsnkScr67 = TcKsnkScr67;
