// SCR-66 Bảng chỉ số KSNK toàn viện — bản tối thiểu của khung (FEAT-056 AC-15; FR-M9-27; BRU-RPT-001; A-131 g).
// Đọc giá trị đã lưu khi khóa kỳ qua tracecore.v1.indicator.values (không tính lại). Trạng thái luôn có chữ.
// FEAT-065 hoàn thiện: KPI, xu hướng 12 tháng, tuân thủ theo khoa, việc cần xử lý, tự đánh giá QĐ 38.

const TC_IND_VALUES = "tracecore.v1.indicator.values";

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr66 = {
	unit(kind) {
		if (kind === "Percentage") return " %";
		if (kind === "Rate per 1000") return " ‰";
		return "";
	},

	number(value) {
		// dấu phẩy thập phân, dấu chấm hàng nghìn, tối đa 1 chữ số lẻ (NFR-L10N-01)
		const rounded = Math.round(Number(value) * 10) / 10;
		const [whole, fraction] = Math.abs(rounded).toFixed(1).split(".");
		const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
		return (rounded < 0 ? "-" : "") + grouped + (fraction === "0" ? "" : `,${fraction}`);
	},

	formatValue(value, kind) {
		if (value === null || value === undefined) return "—";
		return TcKsnkScr66.number(value) + TcKsnkScr66.unit(kind);
	},

	targetText(row) {
		if (
			!row.target_direction ||
			row.national_target === null ||
			row.national_target === undefined
		)
			return "—";
		const sign = row.target_direction === "Higher is better" ? "≥ " : "≤ ";
		return sign + TcKsnkScr66.number(row.national_target) + TcKsnkScr66.unit(row.kind);
	},

	statusBadge(status) {
		if (status === "Met") return { cls: "is-pass", label: __("Met") };
		if (status === "Not met") return { cls: "is-fail", label: __("Not met") };
		if (status === "Not calculated")
			return { cls: "is-neutral", label: __("Not calculated (denominator 0)") };
		if (status === "Insufficient sample")
			return { cls: "is-neutral", label: __("Insufficient sample") };
		return { cls: "", label: "—" };
	},

	periodLabel(period) {
		const [year, month] = String(period).split("-");
		return `${month}/${year}`;
	},

	tableHtml(data, esc) {
		const self = TcKsnkScr66;
		const latest = data.periods[data.periods.length - 1];
		const head = data.periods
			.map((p) => `<th class="is-num">${esc(self.periodLabel(p))}</th>`)
			.join("");
		const body = data.rows
			.map((row) => {
				const cells = data.periods
					.map((p) => {
						const cell = row.values[p];
						return `<td class="is-num">${esc(
							cell ? self.formatValue(cell.value, row.kind) : "—"
						)}</td>`;
					})
					.join("");
				const badge = self.statusBadge(
					row.values[latest] ? row.values[latest].status : ""
				);
				const label = badge.cls
					? `<span class="tc-ksnk-badge ${badge.cls}">${esc(badge.label)}</span>`
					: esc(badge.label);
				return (
					`<tr><td><code class="tc-ksnk-code">${esc(row.code)}</code></td>` +
					`<td>${esc(row.indicator_name)}</td><td>${esc(__(row.measure_group))}</td>` +
					`<td class="is-num">${esc(
						self.targetText(row)
					)}</td>${cells}<td>${label}</td></tr>`
				);
			})
			.join("");
		return (
			`<table class="tc-ksnk-table"><thead><tr>` +
			`<th scope="col">${esc(__("Code"))}</th><th scope="col">${esc(__("Indicator"))}</th>` +
			`<th scope="col">${esc(__("Measure Group"))}</th><th scope="col" class="is-num">${esc(
				__("Target")
			)}</th>` +
			`${head}<th scope="col">${esc(
				__("Status")
			)}</th></tr></thead><tbody>${body}</tbody></table>`
		);
	},

	async render(el, ctx) {
		const self = TcKsnkScr66;
		const esc = ctx.esc;
		const filters = ctx.filters;
		const departments = ctx.departments
			.map(
				(d) =>
					`<option value="${esc(d.name)}"${
						d.name === filters.department ? " selected" : ""
					}>` + `${esc(d.department_name || d.name)}</option>`
			)
			.join("");
		el.innerHTML =
			`<div class="tc-ksnk-filters">` +
			`<label>${esc(
				__("Period")
			)}<input type="month" class="form-control" data-filter="period" value="${esc(
				filters.period
			)}"></label>` +
			`<label>${esc(
				__("Department")
			)}<select class="form-control" data-filter="department">` +
			`<option value="">${esc(
				__("Whole hospital")
			)}</option>${departments}</select></label></div>` +
			`<section class="tc-ksnk-card"><h3>${esc(__("Indicators"))}</h3>` +
			`<div data-region="table">${ctx.state("loading")}</div>` +
			`<p class="tc-ksnk-note">${esc(
				__(
					"Values are read from the indicator values saved when the period was locked; opening this board does not recalculate them. A rate with a zero denominator shows Not calculated, never 0."
				)
			)}</p></section>`;
		el.querySelectorAll("[data-filter]").forEach((input) => {
			input.addEventListener("change", () => {
				ctx.setFilters({ [input.dataset.filter]: input.value });
				self.render(el, ctx);
			});
		});
		const region = el.querySelector('[data-region="table"]');
		region.addEventListener("click", (event) => {
			if (event.target.closest('[data-action="retry"]')) self.render(el, ctx);
		});
		try {
			const data = await ctx.get(TC_IND_VALUES, {
				period: filters.period || undefined,
				department: filters.department || undefined,
				periods: 3,
			});
			if (!ctx.isCurrent()) return;
			if (!data || !data.periods.length || !data.rows.length) {
				region.innerHTML = ctx.state(
					"empty",
					__(
						"No indicator values yet. Values appear after a reporting period is locked."
					)
				);
				return;
			}
			region.innerHTML = self.tableHtml(data, esc);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			region.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkScreens["chi-so"] = TcKsnkScr66;
window.TcKsnkScr66 = TcKsnkScr66;
