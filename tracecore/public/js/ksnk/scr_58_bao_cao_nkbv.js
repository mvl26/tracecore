/* global tracecore, TcKsnk */
// SCR-58 Báo cáo NKBV — phần tỷ suất của FEAT-063 (UC-48 bước 6; FR-M13-10, 10.1, 10.2; BRU-HAI-006; A-131, A-144 g).
// Chọn kỳ (tháng, kèm trạng thái khóa), xu hướng tỷ suất NKBV/1.000 ngày nằm viện 12 tháng, bảng theo khoa: ngày nằm
// viện, ca NKBV xác định, ‰, VAP ‰, CLABSI ‰, CAUTI ‰, tỷ lệ thở máy. Mẫu số 0 → "Không tính", không bao giờ 0.
// Chỉ số liệu tổng hợp (R13 xem được). Cảnh báo cụm ca, điều tra cắt ngang, xuất NKVM thuộc FEAT-064/069/072.

const TC_HAI_REPORT = "tracecore.v1.hai_case.report";

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr58 = {
	month(value) {
		if (!value) return "—";
		const [y, m] = String(value).split("-");
		return `${m}/${y}`;
	},

	num(value, digits) {
		if (value === null || value === undefined) return __("Not calculated");
		const fixed = Number(value).toFixed(digits === undefined ? 1 : digits);
		const [whole, frac] = fixed.split(".");
		const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
		return frac ? `${grouped},${frac}` : grouped;
	},

	int(value) {
		return TcKsnkScr58.num(Number(value || 0), 0);
	},

	filtersHtml(data, esc) {
		const options = (data.months || [])
			.map(
				(m) =>
					`<option value="${esc(m.month)}"${
						m.month === data.period ? " selected" : ""
					}>${esc(
						m.locked
							? __("Month {0} (locked)", [TcKsnkScr58.month(m.month)])
							: __("Month {0} (open)", [TcKsnkScr58.month(m.month)])
					)}</option>`
			)
			.join("");
		return `<div class="tc-ksnk-filters"><label>${esc(__("Period"))}
			<select class="form-control" data-filter="period">${options}</select></label></div>`;
	},

	kpisHtml(data, esc) {
		const h = data.hospital || {};
		const self = TcKsnkScr58;
		const tile = (label, value) =>
			`<div class="tc-ksnk-kpi"><span>${esc(label)}</span><strong>${esc(
				value
			)}</strong></div>`;
		const state = data.locked
			? `<span class="tc-ksnk-badge is-pass">${esc(__("Locked"))}</span>`
			: `<span class="tc-ksnk-badge is-info">${esc(
					__("Open — figures may still change")
			  )}</span>`;
		return (
			`<p class="tc-ksnk-note">${esc(
				__("Hospital-wide, month {0}", [self.month(data.period)])
			)} ${state}</p>` +
			`<div class="tc-ksnk-kpis">` +
			tile(__("HAI per 1,000 patient days"), self.num(h.hai)) +
			tile(__("VAP per 1,000 ventilator days"), self.num(h.vap)) +
			tile(__("CLABSI per 1,000 central line days"), self.num(h.clabsi)) +
			tile(__("CAUTI per 1,000 urinary catheter days"), self.num(h.cauti)) +
			`</div>`
		);
	},

	trendHtml(rows, esc) {
		const self = TcKsnkScr58;
		const max = Math.max(1, ...rows.map((r) => Number(r.value || 0)));
		const body = rows
			.map((r) => {
				const pct =
					r.value === null || r.value === undefined
						? 0
						: Math.round((r.value / max) * 100);
				return `<tr><td>${esc(self.month(r.month))}</td>
					<td class="is-num">${esc(self.int(r.cases))}</td>
					<td class="is-num">${esc(self.int(r.patient_days))}</td>
					<td class="is-num">${esc(self.num(r.value))}</td>
					<td><span class="tc-ksnk-progress" role="img" aria-label="${esc(
						self.num(r.value)
					)}"><span style="width: ${pct}%"></span></span></td></tr>`;
			})
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("HAI per 1,000 patient days — 12 months")
		)}</h3>
			<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Month"))}</th><th>${esc(
			__("HAI cases")
		)}</th><th>${esc(
			__("Patient days")
		)}</th><th>‰</th><th></th></tr></thead><tbody>${body}</tbody></table></section>`;
	},

	departmentsHtml(data, esc) {
		const self = TcKsnkScr58;
		const rows = data.departments || [];
		if (!rows.length)
			return `<section class="tc-ksnk-card"><h3>${esc(
				__("By department — month {0}", [self.month(data.period)])
			)}</h3><p class="tc-ksnk-state">${esc(
				__("No census or HAI case in this month.")
			)}</p></section>`;
		const body = rows
			.map(
				(r) => `<tr><td>${esc(r.department_name || r.department)}</td>
				<td class="is-num">${esc(self.int(r.patient_days))}</td>
				<td class="is-num">${esc(self.int(r.cases))}</td>
				<td class="is-num">${esc(self.num(r.hai))}</td>
				<td class="is-num">${esc(self.num(r.vap))}</td>
				<td class="is-num">${esc(self.num(r.clabsi))}</td>
				<td class="is-num">${esc(self.num(r.cauti))}</td>
				<td class="is-num">${esc(
					r.vent_utilization === null || r.vent_utilization === undefined
						? __("Not calculated")
						: `${self.num(r.vent_utilization)} %`
				)}</td></tr>`
			)
			.join("");
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("By department — month {0}", [self.month(data.period)])
		)}</h3>
			<table class="tc-ksnk-table"><thead><tr>
				<th>${esc(__("Department"))}</th><th>${esc(__("Patient days"))}</th><th>${esc(
			__("HAI cases")
		)}</th>
				<th>‰</th><th>VAP ‰</th><th>CLABSI ‰</th><th>CAUTI ‰</th><th>${esc(__("Ventilator use"))}</th>
			</tr></thead><tbody>${body}</tbody></table>
			<p class="tc-ksnk-note">${esc(
				__(
					'"Not calculated" = the denominator (patient days or device days) is 0. Only confirmed cases are counted; device rates follow the device of the case definition.'
				)
			)}</p></section>`;
	},

	pageHtml(data, esc) {
		const self = TcKsnkScr58;
		return (
			self.filtersHtml(data, esc) +
			self.kpisHtml(data, esc) +
			`<div class="tc-ksnk-cols"><div>${self.trendHtml(
				data.trend || [],
				esc
			)}</div><div>${self.departmentsHtml(data, esc)}</div></div>`
		);
	},

	// FEAT-064 (A-147 j, k): NKVM theo nhóm phẫu thuật & NNIS, KSDP; xuất NKVM / NK hồi sức theo hồ sơ ánh xạ cột (R01, R11)
	pct(value) {
		if (value === null || value === undefined) return __("Not calculated");
		return `${TcKsnkScr58.num(value)} %`;
	},

	ssiHtml(s, esc) {
		const self = TcKsnkScr58;
		const groups = s.groups || [];
		const t = s.totals || {};
		const range =
			s.period_from === s.period_to
				? self.month(s.period_from)
				: `${self.month(s.period_from)} – ${self.month(s.period_to)}`;
		const nnis = (r, b) =>
			r[`nnis_${b}`] ? `${self.int(r[`ssi_nnis_${b}`])}/${self.int(r[`nnis_${b}`])}` : "—";
		const body = groups.length
			? `<table class="tc-ksnk-table"><thead><tr><th>${esc(
					__("Procedure Group")
			  )}</th><th>${esc(__("Surgeries"))}</th><th>${esc(__("SSI Cases"))}</th><th>${esc(
					__("SSI Rate")
			  )}</th><th>NNIS 0</th><th>NNIS 1</th><th>NNIS 2</th><th>NNIS 3</th><th>${esc(
					__("Prophylaxis")
			  )}</th><th>${esc(__("On time"))}</th></tr></thead><tbody>${groups
					.map(
						(r) =>
							`<tr><td>${esc(r.group_name)}</td><td class="is-num">${esc(
								self.int(r.surgeries)
							)}</td><td class="is-num">${esc(
								self.int(r.ssi)
							)}</td><td class="is-num">${esc(self.pct(r.ssi_rate))}</td>${[
								0, 1, 2, 3,
							]
								.map((b) => `<td class="is-num">${esc(nnis(r, b))}</td>`)
								.join("")}<td class="is-num">${esc(
								self.pct(r.prophylaxis_rate)
							)}</td><td class="is-num">${esc(self.pct(r.on_time_rate))}</td></tr>`
					)
					.join("")}</tbody></table>`
			: `<p class="tc-ksnk-state">${esc(
					__("No surgery under surveillance in this period.")
			  )}</p>`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(
				__("Surgical site infection by procedure group — {0}", [range])
			)}</h3>` +
			`<p class="tc-ksnk-note">${esc(
				__("Hospital-wide: {0} surgeries, SSI {1}, prophylaxis {2}, on time {3}.", [
					self.int(t.surgeries),
					self.pct(t.ssi_rate),
					self.pct(t.prophylaxis_rate),
					self.pct(t.on_time_rate),
				])
			)}</p>${body}<p class="tc-ksnk-note">${esc(
				__("NNIS columns show SSI cases / surgeries of that risk index.")
			)}</p></section>`
		);
	},

	exportHtml(kinds, s, esc) {
		if (!kinds || !kinds.length) return "";
		const kindOptions = kinds
			.map((k) => `<option value="${esc(k.key)}">${esc(k.label)}</option>`)
			.join("");
		const profiles = (kinds[0].profiles || [])
			.map(
				(p) =>
					`<option value="${esc(p.name)}">${esc(p.name)} (${esc(
						p.file_format
					)})</option>`
			)
			.join("");
		return (
			`<section class="tc-ksnk-card" data-region="export"><h3>${esc(
				__("Export SSI / ICU infection report")
			)}</h3><div class="tc-ksnk-form">` +
			`<label>${esc(
				__("Report")
			)}<select class="form-control" data-export="kind">${kindOptions}</select></label>` +
			`<label>${esc(
				__("Mapping profile")
			)}<select class="form-control" data-export="profile"><option value="">${esc(
				__("Default columns (Excel)")
			)}</option>${profiles}</select></label>` +
			`<label>${esc(
				__("From month")
			)}<input class="form-control" type="month" data-export="from" value="${esc(
				s.period_from
			)}"></label>` +
			`<label>${esc(
				__("To month")
			)}<input class="form-control" type="month" data-export="to" value="${esc(
				s.period_to
			)}"></label>` +
			`<button type="button" class="btn btn-primary" data-action="download">${esc(
				__("Download")
			)}</button></div><p class="tc-ksnk-note">${esc(
				__(
					"Files carry only the masked patient code; mapping profiles shape the columns to the requested template."
				)
			)}</p></section>`
		);
	},

	bindExport(el, kinds, esc) {
		const region = el.querySelector('[data-region="export"]');
		if (!region) return;
		const pick = (name) => region.querySelector(`[data-export="${name}"]`);
		pick("kind").addEventListener("change", () => {
			const kind = kinds.find((k) => k.key === pick("kind").value) || {};
			pick("profile").innerHTML =
				`<option value="">${esc(__("Default columns (Excel)"))}</option>` +
				(kind.profiles || [])
					.map(
						(p) =>
							`<option value="${esc(p.name)}">${esc(p.name)} (${esc(
								p.file_format
							)})</option>`
					)
					.join("");
		});
		region.querySelector('[data-action="download"]').addEventListener("click", () => {
			const args = new URLSearchParams({
				kind: pick("kind").value,
				profile: pick("profile").value,
				period_from: pick("from").value,
				period_to: pick("to").value || pick("from").value,
			});
			window.open(`/api/method/tracecore.v1.exports.download?${args.toString()}`);
		});
	},

	async renderSsi(el, ctx, period) {
		const region = el.querySelector('[data-region="ssi"]');
		if (!region) return;
		try {
			const s = await ctx.get("tracecore.v1.ssi.summary", { period_from: period || "" });
			const kinds = s.can_export
				? (await ctx.get("tracecore.v1.exports.kinds", {})).kinds
				: [];
			if (!ctx.isCurrent()) return;
			region.innerHTML =
				TcKsnkScr58.ssiHtml(s, ctx.esc) + TcKsnkScr58.exportHtml(kinds, s, ctx.esc);
			TcKsnkScr58.bindExport(region, kinds, ctx.esc);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			region.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_HAI_REPORT, { period: ctx.filters.period || "" });
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr58.pageHtml(data, ctx.esc) + `<div data-region="ssi"></div>`;
			TcKsnkScr58.renderSsi(el, ctx, data.period);
			// FEAT-072: khối điều tra cắt ngang (tải riêng, lỗi khối này không làm hỏng phần tỷ suất)
			el.insertAdjacentHTML("beforeend", '<div data-region="pps"></div>');
			TcKsnkPps.render(el.querySelector('[data-region="pps"]'), ctx);
			const select = el.querySelector('[data-filter="period"]');
			if (select)
				select.addEventListener("change", () => {
					ctx.setFilters({ period: select.value });
					TcKsnkScr58.render(el, ctx);
				});
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkScreens["bao-cao-nkbv"] = TcKsnkScr58;
window.TcKsnkScr58 = TcKsnkScr58;

// FEAT-072 (A-149 Q1; FR-M13-14; UC-50 bước 5, 6, E2, E3): điều tra cắt ngang — chọn ngày, bảng tỷ lệ hiện mắc theo khoa
// (số liệu tổng hợp, R13 xem được); R01/R11 ghi từng người bệnh bằng đợt thiết bị đang đặt hoặc mã BN (không họ tên).
// Số khảo sát 0 → "Không tính". Lỗi chặn hiện alert-error inline: kết quả → lý do → hành động.
const TC_PPS_OVERVIEW = "tracecore.v1.hai_prevalence.overview";
const TC_PPS_CANDIDATES = "tracecore.v1.hai_prevalence.candidates";
const TC_PPS_RECORD = "tracecore.v1.hai_prevalence.record";

const TcKsnkPps = {
	day: "",
	form: { department: "", episode: "", masked: "" },

	date(value) {
		if (!value) return "—";
		const [y, m, d] = String(value).slice(0, 10).split("-");
		return `${d}/${m}/${y}`;
	},

	pct(value) {
		if (value === null || value === undefined) return __("Not calculated");
		return `${Number(value).toFixed(1).replace(".", ",")} %`;
	},

	tableHtml(p, esc) {
		const self = TcKsnkPps;
		const row = (label, r, cls) =>
			`<tr${cls ? ` class="${cls}"` : ""}><td>${esc(label)}</td>` +
			`<td class="is-num">${esc(r.surveyed)}</td><td class="is-num">${esc(r.hai)}</td>` +
			`<td class="is-num">${esc(self.pct(r.rate))}</td><td class="is-num">${esc(
				self.pct(r.antibiotic_rate)
			)}</td></tr>`;
		const rows = (p.departments || []).map((r) =>
			row(r.department_name || r.department, r, "")
		);
		if (!rows.length)
			return `<p class="tc-ksnk-state">${esc(__("No patient surveyed on this day."))}</p>`;
		return (
			`<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
				__("Department")
			)}</th>` +
			`<th scope="col" class="is-num">${esc(__("Patients surveyed"))}</th>` +
			`<th scope="col" class="is-num">${esc(__("With HAI"))}</th>` +
			`<th scope="col" class="is-num">${esc(__("Prevalence"))}</th>` +
			`<th scope="col" class="is-num">${esc(__("Antibiotic use"))}</th></tr></thead>` +
			`<tbody>${rows.join("")}${row(
				__("Hospital total"),
				p.hospital || {},
				"is-total"
			)}</tbody></table>`
		);
	},

	datesHtml(p, esc) {
		const self = TcKsnkPps;
		const current = String(p.date || "").slice(0, 10);
		const days = (p.dates || []).map((d) => String(d).slice(0, 10));
		if (current && !days.includes(current)) days.unshift(current);
		const options = days
			.map(
				(d) =>
					`<option value="${esc(d)}"${d === current ? " selected" : ""}>${esc(
						self.date(d)
					)}</option>`
			)
			.join("");
		return (
			`<div class="tc-ksnk-filters"><label>${esc(__("Survey day"))}` +
			`<select class="form-control" data-pps="day">${options}</select></label>` +
			`<label>${esc(
				__("New survey day")
			)}<input type="date" class="form-control tc-ksnk-date" ` +
			`data-pps="new-day" value=""></label></div>`
		);
	},

	formHtml(p, ctx, esc) {
		const self = TcKsnkPps;
		if (!p.can_record) return "";
		if (!p.template)
			return `<div class="tc-ksnk-alert is-warn" role="status">${esc(
				__(
					"No approved point prevalence survey template: approve it on the audit template screen before recording."
				)
			)}</div>`;
		const departments = ((ctx && ctx.departments) || [])
			.map(
				(d) =>
					`<option value="${esc(d.name)}"${
						d.name === self.form.department ? " selected" : ""
					}>${esc(d.department_name || d.name)}</option>`
			)
			.join("");
		const yesNo = (name) =>
			`<select class="form-control" data-pps="${name}"><option value="">—</option>` +
			`<option value="Yes">${esc(__("Yes"))}</option><option value="No">${esc(
				__("No")
			)}</option></select>`;
		return (
			`<h4>${esc(__("Record a patient"))}</h4>` +
			`<div class="tc-ksnk-form"><label>${esc(__("Department"))}` +
			`<select class="form-control" data-pps="department"><option value="">—</option>${departments}</select></label>` +
			`<label>${esc(
				__("Patient code (no name)")
			)}<input type="text" class="form-control" data-pps="code" ` +
			`autocomplete="off" value=""></label>` +
			`<label>${esc(__("Healthcare-associated infection"))}${yesNo("hai")}</label>` +
			`<label>${esc(__("Receiving antibiotics"))}${yesNo("abx")}</label>` +
			`<button type="button" class="btn btn-primary" data-pps="record">${esc(
				__("Record patient")
			)}</button></div>` +
			`<div data-region="pps-candidates"></div><div data-region="pps-alert"></div>`
		);
	},

	candidatesHtml(rows, esc) {
		const self = TcKsnkPps;
		if (!rows.length)
			return `<p class="tc-ksnk-note">${esc(
				__(
					"No open device episode left to survey in this department; enter other patients by code."
				)
			)}</p>`;
		return (
			`<p class="tc-ksnk-note">${esc(
				__(
					"Patients with an open device episode, not yet surveyed (choose one, or enter a code):"
				)
			)}</p><div class="tc-ksnk-filters">` +
			rows
				.map((r) => {
					const ep = r.episodes[0];
					const on = self.form.episode === ep.name;
					return `<button type="button" class="btn ${
						on ? "btn-primary" : "btn-default"
					}" data-pps="episode" data-episode="${esc(ep.name)}" data-masked="${esc(
						r.patient_code_masked
					)}" aria-pressed="${on}"><code class="tc-ksnk-code">${esc(
						r.patient_code_masked
					)}</code> · ${esc(
						r.episodes.map((e) => __(e.device_type)).join(", ")
					)}</button>`;
				})
				.join("") +
			`</div>`
		);
	},

	blockHtml(error, esc) {
		const e = error || {};
		return (
			`<div class="tc-ksnk-alert" role="alert"><strong>${esc(
				e.title || __("Survey not recorded")
			)}</strong>` +
			`<div>${esc(e.reason || "")}</div><div>${esc(e.action || "")}</div></div>`
		);
	},

	cardHtml(p, ctx, esc) {
		const self = TcKsnkPps;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Point prevalence survey"))} ` +
			`<code class="tc-ksnk-tag">${esc(__("day {0}", [self.date(p.date)]))}</code></h3>` +
			self.datesHtml(p, esc) +
			self.tableHtml(p, esc) +
			`<p class="tc-ksnk-note">${esc(
				__(
					"Each patient is recorded by an encrypted patient code, never by name. Prevalence = patients with HAI / patients surveyed."
				)
			)}</p>` +
			self.formHtml(p, ctx, esc) +
			`</section>`
		);
	},

	async loadCandidates(region, ctx) {
		const self = TcKsnkPps;
		const box = region.querySelector('[data-region="pps-candidates"]');
		if (!box || !self.form.department) {
			if (box) box.innerHTML = "";
			return;
		}
		try {
			const res = await ctx.get(TC_PPS_CANDIDATES, {
				date: self.day,
				department: self.form.department,
			});
			if (!ctx.isCurrent()) return;
			box.innerHTML = self.candidatesHtml(res.candidates || [], ctx.esc);
			self.bindCandidates(region, ctx);
		} catch (error) {
			box.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},

	bindCandidates(region, ctx) {
		const self = TcKsnkPps;
		region.querySelectorAll('[data-pps="episode"]').forEach((button) => {
			button.addEventListener("click", () => {
				const same = self.form.episode === button.dataset.episode;
				self.form.episode = same ? "" : button.dataset.episode;
				self.form.masked = same ? "" : button.dataset.masked;
				const code = region.querySelector('[data-pps="code"]');
				if (code) code.value = "";
				self.loadCandidates(region, ctx);
			});
		});
	},

	bind(region, ctx) {
		const self = TcKsnkPps;
		const value = (key) => {
			const input = region.querySelector(`[data-pps="${key}"]`);
			return input ? input.value : "";
		};
		const day = region.querySelector('[data-pps="day"]');
		if (day)
			day.addEventListener("change", () => {
				self.day = day.value;
				self.render(region, ctx);
			});
		const fresh = region.querySelector('[data-pps="new-day"]');
		if (fresh)
			fresh.addEventListener("change", () => {
				if (!fresh.value) return;
				self.day = fresh.value;
				self.render(region, ctx);
			});
		const department = region.querySelector('[data-pps="department"]');
		if (department)
			department.addEventListener("change", () => {
				self.form = { department: department.value, episode: "", masked: "" };
				self.loadCandidates(region, ctx);
			});
		const code = region.querySelector('[data-pps="code"]');
		if (code)
			code.addEventListener("input", () => {
				if (code.value && self.form.episode) {
					self.form.episode = "";
					self.form.masked = "";
					self.loadCandidates(region, ctx);
				}
			});
		const record = region.querySelector('[data-pps="record"]');
		if (record)
			record.addEventListener("click", () => {
				const alertBox = region.querySelector('[data-region="pps-alert"]');
				record.disabled = true;
				tracecore.desk_call({
					method: TC_PPS_RECORD,
					args: {
						date: self.day,
						department: self.form.department,
						hai: value("hai"),
						antibiotic: value("abx"),
						device_episode: self.form.episode || "",
						patient_code: self.form.episode ? "" : value("code"),
					},
					on_ok: () => {
						self.form.episode = "";
						self.form.masked = "";
						self.render(region, ctx);
					},
					on_block: (error) => {
						record.disabled = false;
						if (alertBox) alertBox.innerHTML = self.blockHtml(error, ctx.esc);
					},
					on_fail: () => {
						record.disabled = false;
					},
				});
			});
	},

	async render(region, ctx) {
		const self = TcKsnkPps;
		if (!region) return;
		region.innerHTML = ctx.state("loading");
		try {
			const p = await ctx.get(TC_PPS_OVERVIEW, self.day ? { date: self.day } : {});
			if (!ctx.isCurrent()) return;
			self.day = String(p.date || "").slice(0, 10);
			region.innerHTML = self.cardHtml(p, ctx, ctx.esc);
			self.bind(region, ctx);
			self.loadCandidates(region, ctx);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			region.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkPps = TcKsnkPps;

// FEAT-069 (A-150 Q2; FR-M13-13, .1; UC-50 bước 3–4, E1): banner cảnh báo cụm ca ở đầu SCR-58 — nút "Mở điều tra ổ dịch"
// (sang SCR-61 điền sẵn) và "Đánh dấu đã xem xét" (bắt buộc lý do); chưa có ngưỡng → nhắc cấu hình. Tải riêng, lỗi
// khối này không làm hỏng phần tỷ suất.
const TC_CLUSTER_ALERTS = "tracecore.v1.outbreak.cluster_alerts";
const TC_CLUSTER_DISMISS = "tracecore.v1.outbreak.dismiss_alert";

const TcKsnkClusterBanner = {
	html(b, esc) {
		const date = (value) => {
			if (!value) return "—";
			const [y, m, d] = String(value).slice(0, 10).split("-");
			return `${d}/${m}/${y}`;
		};
		if (!b.configured)
			return `<div class="tc-ksnk-alert is-info" role="note">${esc(
				__("No cluster alert threshold is configured, so no cluster is detected.")
			)} <a class="btn btn-default btn-sm" href="${esc(b.rule_form)}">${esc(
				__("Set thresholds")
			)}</a></div>`;
		return (b.alerts || [])
			.map(
				(a) => `<div class="tc-ksnk-alert is-warn" role="alert">
				<strong>${esc(__("Cluster alert — {0}", [a.department_name || a.department]))}:</strong>
				${esc(
					__(
						"{0} cases of {1} in {2} days (threshold {3} cases / {2} days), {4} – {5}.",
						[
							a.case_count,
							a.key_label,
							a.window_days,
							a.min_cases,
							date(a.window_start),
							date(a.window_end),
						]
					)
				)}
				<div class="tc-ksnk-actions">${
					b.can_review
						? `<a class="btn btn-danger" href="${esc(
								b.open_link
						  )}?alert=${encodeURIComponent(a.name)}">${esc(
								__("Open outbreak investigation")
						  )}</a>
					<button type="button" class="btn btn-default" data-action="cluster-dismiss" data-name="${esc(
						a.name
					)}">${esc(__("Mark as reviewed"))}</button> `
						: ""
				}${TcKsnk.recordActions(
					{
						doctype: "Cluster Alert",
						name: a.name,
						docstatus: a.docstatus === undefined ? 0 : a.docstatus,
						can_write: !!b.can_review,
						can_create: false,
						can_print: false,
					},
					false
				)}</div></div>`
			)
			.join("");
	},

	async render(region, ctx, rerender) {
		if (!region) return;
		try {
			const b = await ctx.get(TC_CLUSTER_ALERTS, {});
			if (!ctx.isCurrent()) return;
			region.innerHTML = TcKsnkClusterBanner.html(b, ctx.esc);
			region.querySelectorAll('[data-action="cluster-dismiss"]').forEach((button) =>
				button.addEventListener("click", () =>
					frappe.prompt(
						[
							{
								fieldname: "reason",
								fieldtype: "Small Text",
								label: __("Reason"),
								reqd: 1,
							},
						],
						(v) =>
							frappe.call({
								method: TC_CLUSTER_DISMISS,
								args: {
									alert: button.dataset.name,
									reason: v.reason,
									client_ts: tcClusterClientTs(),
								},
								headers: { "X-Idempotency-Key": crypto.randomUUID() },
								callback: () => rerender(),
							}),
						__("Mark as reviewed (no investigation)"),
						__("Confirm")
					)
				)
			);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			region.innerHTML = "";
		}
	},
};

function tcClusterClientTs(date = new Date()) {
	const pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
	const offset = -date.getTimezoneOffset();
	return (
		`${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
		`T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
		`${offset >= 0 ? "+" : "-"}${pad(offset / 60)}:${pad(offset % 60)}`
	);
}

(function () {
	const base = TcKsnkScr58.render;
	TcKsnkScr58.render = async function (el, ctx) {
		await base.call(TcKsnkScr58, el, ctx);
		if (!ctx.isCurrent() || el.querySelector('[data-region="clusters"]')) return;
		el.insertAdjacentHTML("afterbegin", '<div data-region="clusters"></div>');
		TcKsnkClusterBanner.render(el.querySelector('[data-region="clusters"]'), ctx, () =>
			TcKsnkScr58.render(el, ctx)
		);
	};
})();

window.TcKsnkClusterBanner = TcKsnkClusterBanner;
