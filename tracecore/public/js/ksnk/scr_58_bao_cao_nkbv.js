/* global tracecore */
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
