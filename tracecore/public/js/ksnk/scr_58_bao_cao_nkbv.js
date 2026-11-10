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

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_HAI_REPORT, { period: ctx.filters.period || "" });
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr58.pageHtml(data, ctx.esc);
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
