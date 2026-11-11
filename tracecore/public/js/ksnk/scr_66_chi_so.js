/* global tracecore */
// SCR-66 Bảng chỉ số KSNK toàn viện (FEAT-065; FR-M9-24, .1, .2, FR-M9-25, FR-M9-29, .1; BRU-RPT-001; NFR-PERF-05;
// UC-57 bước 3, 4, 7; A-131 g; A-145). Khung tối thiểu từ FEAT-056.
// Đọc giá trị đã lưu khi khóa kỳ qua tracecore.v1.indicator.board (không tính lại). Trạng thái luôn có chữ hoặc ký hiệu:
// badge chữ, ô KPI có dòng trạng thái, thanh dưới mục tiêu có "↓". R13 chỉ đọc; R01 sinh báo cáo Hội đồng và lập tự đánh
// giá QĐ 38. Cổng khoa (view DEPT) ở Portal /ksnk-khoa/chi-so.

const TC_IND_BOARD = "tracecore.v1.indicator.board";
const TC_IND_SELF = "tracecore.v1.indicator.self_assessment";
const TC_IND_SELF_PREPARE = "tracecore.v1.indicator.self_assessment_prepare";
const TC_IND_SELF_SET = "tracecore.v1.indicator.self_assessment_set";
const TC_IND_SELF_SUBMIT = "tracecore.v1.indicator.self_assessment_submit";
const TC_IND_COUNCIL = "tracecore.v1.indicator.council_generate";
const TC_IND_IMPORT_ROUTE = "/app/tc-import";
const TC_IND_SELF_STATUSES = ["Not assessed", "Met", "Not met", "Needs confirmation"];
// FEAT-074 (FR-M9-30; A-152): gói hồ sơ KSNK cho đoàn kiểm tra — chỉ R01
const TC_DOSSIER_SECTIONS = "tracecore.v1.archive.ic_dossier_sections";
const TC_DOSSIER_EXPORT = "tracecore.v1.archive.ic_dossier_export";
const TC_DOSSIER_LIST = "tracecore.v1.archive.ic_dossiers";

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

	// giá trị một ô: không có dòng → "—"; mẫu số 0 → "Không tính" (BRU-RPT-001), không bao giờ 0
	cellText(cell, kind) {
		if (!cell) return "—";
		if (cell.value === null || cell.value === undefined) return __("Not calculated");
		return TcKsnkScr66.formatValue(cell.value, kind);
	},

	targetText(row) {
		const target = row.target !== undefined ? row.target : row.national_target;
		if (!row.target_direction || target === null || target === undefined) return "—";
		const sign = row.target_direction === "Higher is better" ? "≥ " : "≤ ";
		return sign + TcKsnkScr66.number(target) + TcKsnkScr66.unit(row.kind);
	},

	// trạng thái bằng chữ; "Chưa đạt" của chỉ số càng thấp càng tốt là "Vượt ngưỡng" (đỏ), càng cao càng tốt là cam
	statusBadge(status, direction) {
		if (status === "Met") return { cls: "is-pass", label: __("Met") };
		if (status === "Not met") {
			if (direction === "Higher is better") return { cls: "is-warn", label: __("Not met") };
			if (direction === "Lower is better")
				return { cls: "is-fail", label: __("Above threshold") };
			return { cls: "is-fail", label: __("Not met") };
		}
		if (status === "Not calculated")
			return { cls: "is-neutral", label: __("Not calculated (denominator 0)") };
		if (status === "Insufficient sample")
			return { cls: "is-neutral", label: __("Insufficient sample") };
		if (status === "No data") return { cls: "is-neutral", label: __("No data") };
		return { cls: "", label: "—" };
	},

	badgeHtml(status, direction, esc) {
		const badge = TcKsnkScr66.statusBadge(status, direction);
		return badge.cls
			? `<span class="tc-ksnk-badge ${badge.cls}">${esc(badge.label)}</span>`
			: esc(badge.label);
	},

	periodLabel(period) {
		const [year, month] = String(period).split("-");
		return `${month}/${year}`;
	},

	// --- xu hướng 12 tháng: sparkline SVG, có aria-label liệt kê giá trị (không chỉ hình) ---------------------------
	sparkline(row, periods, esc) {
		const self = TcKsnkScr66;
		const points = periods.map((p) => {
			const cell = row.values[p];
			return cell && cell.value !== null && cell.value !== undefined ? cell.value : null;
		});
		const known = points.filter((v) => v !== null);
		const label =
			__("Trend 12 months") +
			": " +
			periods
				.map(
					(p, i) =>
						`${self.periodLabel(p)} ${
							points[i] === null ? "—" : self.formatValue(points[i], row.kind)
						}`
				)
				.join(", ");
		if (known.length < 2) {
			return `<span class="tc-ksnk-spark-empty" title="${esc(label)}">${esc(
				__("Not enough data")
			)}</span>`;
		}
		const target = row.target_direction ? row.target : null;
		const all = target === null || target === undefined ? known : known.concat([target]);
		const max = Math.max(...all);
		const min = Math.min(...all);
		const span = max - min || 1;
		const width = 120;
		const height = 32;
		const step = width / Math.max(periods.length - 1, 1);
		const y = (v) => (height - 2 - ((v - min) / span) * (height - 4)).toFixed(1);
		const path = points
			.map((v, i) => (v === null ? null : `${(i * step).toFixed(1)},${y(v)}`))
			.filter(Boolean)
			.join(" ");
		const goal =
			target === null || target === undefined
				? ""
				: `<line class="tc-ksnk-spark-target" x1="0" x2="${width}" y1="${y(
						target
				  )}" y2="${y(target)}"></line>`;
		return (
			`<svg class="tc-ksnk-spark" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(
				label
			)}">` +
			`<title>${esc(label)}</title>${goal}<polyline points="${path}"></polyline></svg>`
		);
	},

	// --- khối ------------------------------------------------------------------------------------------------------
	kpisHtml(data, esc) {
		const self = TcKsnkScr66;
		const rows = data.rows.filter((row) => data.kpis.indexOf(row.code) >= 0);
		if (!rows.length) return "";
		const tiles = rows
			.map((row) => {
				const badge = self.statusBadge(row.status, row.target_direction);
				const sample =
					row.latest && row.latest.sample_size ? row.latest.sample_size : null;
				const facts = [__("Target {0}", [self.targetText(row)])];
				if (sample !== null) facts.push(__("{0} sample", [self.number(sample)]));
				return (
					`<div class="tc-ksnk-kpi ${badge.cls}"><span>${esc(
						row.indicator_name
					)}</span>` +
					`<b>${esc(self.cellText(row.latest, row.kind))}</b>` +
					`<small>${esc(facts.join(" · "))}</small>` +
					`<small><strong class="tc-ksnk-kpi-status">${esc(
						badge.label
					)}</strong></small></div>`
				);
			})
			.join("");
		return `<div class="tc-ksnk-kpis">${tiles}</div>`;
	},

	tableHtml(data, esc) {
		const self = TcKsnkScr66;
		const head = data.table_periods
			.map((p) => `<th scope="col" class="is-num">${esc(self.periodLabel(p))}</th>`)
			.join("");
		const body = data.rows
			.map((row) => {
				const cells = data.table_periods
					.map(
						(p) =>
							`<td class="is-num">${esc(
								self.cellText(row.values[p], row.kind)
							)}</td>`
					)
					.join("");
				const sample = row.latest ? self.number(row.latest.sample_size || 0) : "—";
				const provisional =
					row.latest && !row.latest.locked
						? ` <span class="tc-ksnk-badge is-info">${esc(__("Provisional"))}</span>`
						: "";
				return (
					`<tr><td><code class="tc-ksnk-code">${esc(row.code)}</code></td>` +
					`<td>${esc(row.indicator_name)}</td><td>${esc(__(row.measure_group))}</td>` +
					`<td class="is-num">${esc(self.targetText(row))}</td>${cells}` +
					`<td class="is-num">${esc(sample)}</td>` +
					`<td>${self.sparkline(row, data.periods, esc)}</td>` +
					`<td>${self.badgeHtml(
						row.status,
						row.target_direction,
						esc
					)}${provisional}</td></tr>`
				);
			})
			.join("");
		return (
			`<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr>` +
			`<th scope="col">${esc(__("Code"))}</th><th scope="col">${esc(__("Indicator"))}</th>` +
			`<th scope="col">${esc(__("Measure Group"))}</th>` +
			`<th scope="col" class="is-num">${esc(__("Target"))}</th>${head}` +
			`<th scope="col" class="is-num">${esc(__("Sample Size"))}</th>` +
			`<th scope="col">${esc(__("Trend 12 months"))}</th>` +
			`<th scope="col">${esc(
				__("Status")
			)}</th></tr></thead><tbody>${body}</tbody></table></div>`
		);
	},

	// thanh theo khoa: dưới mục tiêu = thanh cam + "↓" (không chỉ màu); vạch mục tiêu
	chartHtml(chart, esc) {
		const self = TcKsnkScr66;
		if (!chart) return "";
		const values = chart.rows.map((r) => r.value || 0);
		const scale =
			chart.kind === "Percentage" ? 100 : Math.max(...values, chart.target || 0) * 1.1 || 1;
		const pos = (v) => Math.max(0, Math.min(100, (v / scale) * 100)).toFixed(1);
		const options = chart.options
			.map(
				(o) =>
					`<option value="${esc(o.code)}"${
						o.code === chart.indicator ? " selected" : ""
					}>${esc(o.indicator_name)}</option>`
			)
			.join("");
		const marker =
			chart.target_direction && chart.target !== null && chart.target !== undefined
				? `<span class="tc-ksnk-bar-target" style="left: ${pos(chart.target)}%"></span>`
				: "";
		const bars = chart.rows
			.map((r) => {
				const below = r.status === "Not met";
				const text =
					r.value === null || r.value === undefined
						? __("Not calculated")
						: self.formatValue(r.value, chart.kind) + (below ? " ↓" : "");
				return (
					`<div class="tc-ksnk-bar${below ? " is-below" : ""}">` +
					`<span class="tc-ksnk-bar-label">${esc(r.department_name)}</span>` +
					`<span class="tc-ksnk-bar-track"><span class="tc-ksnk-bar-fill" style="width: ${pos(
						r.value || 0
					)}%"></span>${marker}</span>` +
					`<span class="tc-ksnk-bar-value">${esc(text)}</span></div>`
				);
			})
			.join("");
		return (
			`<section class="tc-ksnk-card"><h3>${esc(
				__("By department — {0}", [self.periodLabel(chart.period)])
			)} <span class="tc-ksnk-badge is-neutral">${esc(
				__("target {0}", [self.targetText(chart)])
			)}</span></h3>` +
			`<label class="tc-ksnk-inline">${esc(
				__("Indicator")
			)}<select class="form-control" data-chart>${options}</select></label>` +
			`<div class="tc-ksnk-bars">${bars}</div>` +
			`<p class="tc-ksnk-note">${esc(
				__("Orange bar and ↓ = below target. Dark line = target.")
			)}</p></section>`
		);
	},

	todosHtml(todos, esc) {
		const items = todos.length
			? todos
					.map((item) => {
						const cls =
							{ error: "", warn: " is-warn", info: " is-info" }[item.severity] || "";
						const link = item.link
							? ` <a href="${esc(item.link)}">${esc(__("Open"))}</a>`
							: "";
						const detail = item.detail ? ` — ${esc(item.detail)}` : "";
						return `<li class="tc-ksnk-alert${cls}"><strong>${esc(
							item.title
						)}</strong>${detail}${link}</li>`;
					})
					.join("")
			: `<li class="tc-ksnk-note">${esc(__("Nothing to handle right now."))}</li>`;
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Items to handle")
		)}</h3><ul class="tc-ksnk-todos">${items}</ul></section>`;
	},

	selfStatusLabel(row) {
		const labels = {
			Met: __("Met"),
			"Not met": __("Not met"),
			"Needs confirmation": __("Needs R01 confirmation"),
			"Not assessed": __("Not assessed"),
		};
		const source = row.source === "Auto" ? __("automatic") : __("manual");
		return row.status === "Not assessed"
			? labels[row.status]
			: `${labels[row.status] || row.status} (${source})`;
	},

	selfHtml(sa, esc) {
		const self = TcKsnkScr66;
		const cls = {
			Met: "is-pass",
			"Not met": "is-fail",
			"Needs confirmation": "is-warn",
			"Not assessed": "is-neutral",
		};
		const editable = sa.can_manage && sa.name && sa.docstatus === 0;
		const rows = sa.rows
			.map((row) => {
				const status = `<span class="tc-ksnk-badge ${
					cls[row.status] || "is-neutral"
				}">${esc(self.selfStatusLabel(row))}</span>`;
				const source =
					esc(row.source_hint) + (row.source_ref ? `<br>${esc(row.source_ref)}` : "");
				const edit = editable
					? `<td><div class="tc-ksnk-inline"><select class="form-control" data-sa-status="${esc(
							row.criterion
					  )}">${TC_IND_SELF_STATUSES.map(
							(s) =>
								`<option value="${esc(s)}"${
									s === row.status ? " selected" : ""
								}>${esc(
									self.selfStatusLabel({ status: s, source: "Manual" })
								)}</option>`
					  ).join("")}</select>` +
					  `<input class="form-control" data-sa-evidence="${esc(
							row.criterion
					  )}" value="${esc(row.evidence)}" placeholder="${esc(__("Evidence"))}">` +
					  `<button type="button" class="btn btn-default btn-sm" data-action="sa-save" data-criterion="${esc(
							row.criterion
					  )}">${esc(__("Save"))}</button></div></td>`
					: "";
				return `<tr><td>${esc(
					row.criterion_text
				)}</td><td>${source}</td><td>${status}</td>${edit}</tr>`;
			})
			.join("");
		const actions = [];
		if (sa.can_manage)
			actions.push(
				`<button type="button" class="btn btn-default" data-action="sa-prepare">${esc(
					sa.name ? __("Refresh automatic rows") : __("Prepare self-assessment")
				)}</button>`
			);
		if (editable)
			actions.push(
				`<button type="button" class="btn btn-primary" data-action="sa-submit">${esc(
					__("Submit self-assessment")
				)}</button>`
			);
		if (sa.name)
			actions.push(
				`<a class="btn btn-default" target="_blank" href="/printview?doctype=${encodeURIComponent(
					"IC Self Assessment"
				)}&name=${encodeURIComponent(sa.name)}&format=${encodeURIComponent(
					"TC IC Self Assessment"
				)}">${esc(__("Print"))}</a>`
			);
		const table = sa.rows.length
			? `<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr>` +
			  `<th scope="col">${esc(__("Criterion 2025-2030"))}</th><th scope="col">${esc(
					__("Data Source")
			  )}</th>` +
			  `<th scope="col">${esc(__("Status"))}</th>${
					editable ? `<th scope="col">${esc(__("Assess by hand"))}</th>` : ""
			  }</tr></thead><tbody>${rows}</tbody></table></div>`
			: `<p class="tc-ksnk-note">${esc(
					__("The self-assessment of {0} is not prepared yet.", [sa.year])
			  )}</p>`;
		const state =
			sa.docstatus === 1
				? ` <span class="tc-ksnk-badge is-pass">${esc(__("Submitted"))}</span>`
				: sa.name
				? ` <span class="tc-ksnk-badge is-neutral">${esc(__("Draft"))}</span>`
				: "";
		return (
			`<section class="tc-ksnk-card" id="tc-ksnk-self"><h3>${esc(
				__("Self-assessment against Decision 38/QD-BYT — year {0}", [sa.year])
			)}${state}</h3>` +
			`<div data-region="sa-alert"></div>${table}<div class="tc-ksnk-actions">${actions.join(
				""
			)}</div></section>`
		);
	},

	// FEAT-074: khối gói hồ sơ KSNK (R01) — dải tháng, chọn phần, danh sách gói gần nhất; trạng thái luôn có chữ
	dossierHtml(dz, data, esc) {
		const year = data.year || new Date().getFullYear();
		const lastMonth = data.period || `${year}-12`;
		const statusCls = {
			Completed: "is-pass",
			Failed: "is-fail",
			Running: "is-warn",
			Queued: "is-neutral",
		};
		const statusLabel = {
			Completed: __("Completed"),
			Failed: __("Failed"),
			Running: __("Running"),
			Queued: __("Queued"),
		};
		const sections = dz.sections
			.map(
				(s) =>
					`<label><input type="checkbox" data-dossier-section="${esc(
						s.key
					)}" checked> ${esc(s.label)}${
						s.in_pdf
							? ""
							: ` <span class="tc-ksnk-note">(${esc(__("Excel only"))})</span>`
					}</label>`
			)
			.join("");
		const rows = dz.dossiers
			.map((d) => {
				const status = `<span class="tc-ksnk-badge ${
					statusCls[d.status] || "is-neutral"
				}">${esc(statusLabel[d.status] || d.status)}</span>${
					d.provisional
						? ` <span class="tc-ksnk-badge is-warn">${esc(__("Provisional"))}</span>`
						: ""
				}`;
				const file = d.file
					? `<a target="_blank" href="${esc(d.file)}">${esc(__("Download ZIP"))}</a>`
					: d.error
					? esc(d.error)
					: "—";
				return (
					`<tr><td><code class="tc-ksnk-code">${esc(d.name)}</code></td><td>${esc(
						d.months || ""
					)}</td>` +
					`<td>${status}</td><td><code class="tc-ksnk-code">${esc(
						d.sha256 ? d.sha256.slice(0, 12) + "…" : "—"
					)}</code></td><td>${file}</td></tr>`
				);
			})
			.join("");
		const table = dz.dossiers.length
			? `<div class="tc-ksnk-scroll"><table class="tc-ksnk-table"><thead><tr>` +
			  `<th scope="col">${esc(__("Dossier"))}</th><th scope="col">${esc(
					__("Months")
			  )}</th>` +
			  `<th scope="col">${esc(__("Status"))}</th><th scope="col">${esc(
					__("SHA-256")
			  )}</th><th scope="col">${esc(
					__("File")
			  )}</th></tr></thead><tbody>${rows}</tbody></table></div>`
			: `<p class="tc-ksnk-note">${esc(__("No dossier exported yet."))}</p>`;
		return (
			`<section class="tc-ksnk-card" id="tc-ksnk-dossier"><h3>${esc(
				__("Infection control dossier for an inspection team")
			)} <code class="tc-ksnk-code">FR-M9-30</code></h3>` +
			`<p class="tc-ksnk-note">${esc(
				__(
					"PDF + Excel of the chosen months with SHA-256 checksums. Patient codes are masked; exposures are aggregated only. A month that is not locked yet makes the dossier Provisional."
				)
			)}</p>` +
			`<div class="tc-ksnk-filters tc-ksnk-actions"><label>${esc(
				__("From month")
			)}<input type="month" class="form-control" data-dossier="from" value="${esc(
				`${year}-01`
			)}"></label>` +
			`<label>${esc(
				__("To month")
			)}<input type="month" class="form-control" data-dossier="to" value="${esc(
				lastMonth
			)}"></label></div>` +
			`<fieldset class="tc-ksnk-checks"><legend>${esc(
				__("Sections")
			)}</legend>${sections}</fieldset>` +
			`<div data-region="dossier-alert"></div>` +
			`<div class="tc-ksnk-actions"><button type="button" class="btn btn-primary" data-action="dossier-export">${esc(
				__("Create dossier")
			)}</button><button type="button" class="btn btn-default" data-action="dossier-refresh">${esc(
				__("Refresh")
			)}</button></div>${table}</section>`
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

	headerHtml(data, ctx) {
		const self = TcKsnkScr66;
		const esc = ctx.esc;
		const filters = ctx.filters;
		const now = new Date().getFullYear();
		const years = [];
		for (let y = Math.max(data.year, now) + 1; y >= Math.min(data.year, now) - 3; y--)
			years.push(y);
		const yearOptions = years
			.map(
				(y) =>
					`<option value="${y}"${y === data.year ? " selected" : ""}>${y}${
						y === data.year && data.plan ? ` — ${esc(data.plan.name)}` : ""
					}</option>`
			)
			.join("");
		const departments = ctx.departments
			.map(
				(d) =>
					`<option value="${esc(d.name)}"${
						d.name === filters.department ? " selected" : ""
					}>` + `${esc(d.department_name || d.name)}</option>`
			)
			.join("");
		const periodBadge = data.period
			? `<span class="tc-ksnk-badge ${data.locked ? "is-pass" : "is-warn"}">${esc(
					__("Period {0}", [self.periodLabel(data.period)])
			  )} · ${esc(data.locked ? __("Locked") : __("Provisional"))}</span>`
			: "";
		const report = data.council_report;
		const reportForPeriod = report && report.period === data.period;
		const actions = [
			ctx.readOnly
				? ""
				: `<a class="btn btn-default" href="${TC_IND_IMPORT_ROUTE}">${esc(
						__("Import census / microbiology file")
				  )}</a>`,
			`<a class="btn btn-default" href="#tc-ksnk-self" data-action="goto-self">${esc(
				__("Self-assessment Decision 38")
			)}</a>`,
			reportForPeriod && report.pdf
				? `<a class="btn btn-primary" target="_blank" href="${esc(report.pdf)}">${esc(
						__("Committee report (PDF)")
				  )}${
						report.report_status === "Official" ? "" : ` · ${esc(__("Provisional"))}`
				  }</a>`
				: `<span class="tc-ksnk-note">${esc(
						__("No committee report for this period yet.")
				  )}</span>`,
			frappe.user.has_role("TC R01") && data.period
				? `<button type="button" class="btn btn-default" data-action="council">${esc(
						__("Generate committee report")
				  )}</button>`
				: "",
		].join("");
		return (
			`<div class="tc-ksnk-filters tc-ksnk-actions">` +
			`<label>${esc(
				__("Plan year")
			)}<select class="form-control" data-filter="year">${yearOptions}</select></label>` +
			`<label>${esc(
				__("Period")
			)}<input type="month" class="form-control" data-filter="period" value="${esc(
				data.period || ""
			)}"></label>` +
			`<label>${esc(
				__("Department")
			)}<select class="form-control" data-filter="department">` +
			`<option value="">${esc(
				__("Whole hospital")
			)}</option>${departments}</select></label>` +
			`${periodBadge}</div>` +
			`<div class="tc-ksnk-actions">${actions}</div><div data-region="actions-alert"></div>` +
			(data.plan
				? ""
				: `<div class="tc-ksnk-alert is-warn" role="status">${esc(
						__(
							"No approved infection control plan for {0}: showing every active indicator with the national target.",
							[data.year]
						)
				  )}</div>`)
		);
	},

	pageHtml(data, sa, ctx, dz) {
		const self = TcKsnkScr66;
		const esc = ctx.esc;
		const hasValues = data.periods.length && data.rows.length;
		const board = hasValues
			? self.kpisHtml(data, esc) +
			  `<section class="tc-ksnk-card"><h3>${esc(
					data.plan
						? __("Indicators of the infection control plan {0}", [data.year])
						: __("Active indicators")
			  )}${
					data.plan ? ` <code class="tc-ksnk-code">${esc(data.plan.name)}</code>` : ""
			  }</h3>${self.tableHtml(data, esc)}<p class="tc-ksnk-note">${esc(
					__(
						"Values are read from the indicator values saved when the period was locked; opening this board does not recalculate them. A rate with a zero denominator shows Not calculated, never 0."
					)
			  )}</p></section>`
			: ctx.state(
					"empty",
					__(
						"No indicator values yet. Values appear after a reporting period is locked."
					)
			  );
		const lower = data.chart
			? `<div class="tc-ksnk-cols">${self.chartHtml(data.chart, esc)}${self.todosHtml(
					data.todos,
					esc
			  )}</div>`
			: self.todosHtml(data.todos, esc);
		return (
			self.headerHtml(data, ctx) +
			board +
			lower +
			(sa ? self.selfHtml(sa, esc) : "") +
			(dz ? self.dossierHtml(dz, data, esc) : "")
		);
	},

	// --- sự kiện ---------------------------------------------------------------------------------------------------
	post(el, ctx, method, args, region, done, success) {
		const self = TcKsnkScr66;
		tracecore.desk_call({
			method,
			args,
			success,
			on_ok: (result) => {
				if (!ctx.isCurrent()) return;
				done(result);
			},
			on_block: (error) => {
				const target = el.querySelector(`[data-region="${region}"]`);
				if (target) target.innerHTML = self.blockHtml(error, ctx.esc);
			},
			on_fail: () => {
				el.querySelectorAll("button[disabled]").forEach((b) => (b.disabled = false));
			},
		});
	},

	bind(el, ctx, data) {
		const self = TcKsnkScr66;
		el.querySelectorAll("[data-filter]").forEach((input) => {
			input.addEventListener("change", () => {
				const updates = { [input.dataset.filter]: input.value };
				if (input.dataset.filter === "year") updates.period = "";
				ctx.setFilters(updates);
				self.render(el, ctx);
			});
		});
		const chart = el.querySelector("[data-chart]");
		if (chart)
			chart.addEventListener("change", () => {
				self.chartCode = chart.value;
				self.render(el, ctx);
			});
		el.querySelectorAll("[data-action]").forEach((button) => {
			button.addEventListener("click", (event) => {
				const action = button.dataset.action;
				const year = data.year;
				if (action === "retry" || action === "dossier-refresh")
					return self.render(el, ctx);
				if (action === "goto-self") {
					event.preventDefault();
					const target = el.querySelector("#tc-ksnk-self");
					if (target) target.scrollIntoView();
					return;
				}
				button.disabled = true;
				if (action === "dossier-export") {
					const value = (name) => el.querySelector(`[data-dossier="${name}"]`).value;
					const sections = Array.from(
						el.querySelectorAll("[data-dossier-section]:checked")
					).map((node) => node.dataset.dossierSection);
					self.post(
						el,
						ctx,
						TC_DOSSIER_EXPORT,
						{
							from_month: value("from"),
							to_month: value("to"),
							sections: JSON.stringify(sections),
						},
						"dossier-alert",
						() => self.render(el, ctx),
						__("Dossier prepared successfully")
					);
				} else if (action === "council") {
					self.post(
						el,
						ctx,
						TC_IND_COUNCIL,
						{ period: data.period },
						"actions-alert",
						() => self.render(el, ctx),
						__("Council report generated successfully")
					);
				} else if (action === "sa-prepare") {
					self.post(el, ctx, TC_IND_SELF_PREPARE, { year }, "sa-alert", () =>
						self.render(el, ctx)
					);
				} else if (action === "sa-submit") {
					self.post(el, ctx, TC_IND_SELF_SUBMIT, { year }, "sa-alert", () =>
						self.render(el, ctx)
					);
				} else if (action === "sa-save") {
					const code = button.dataset.criterion;
					const pick = (attr) =>
						Array.from(el.querySelectorAll(`[${attr}]`)).find(
							(node) => node.getAttribute(attr) === code
						);
					self.post(
						el,
						ctx,
						TC_IND_SELF_SET,
						{
							year,
							criterion: code,
							status: pick("data-sa-status").value,
							evidence: pick("data-sa-evidence").value,
						},
						"sa-alert",
						() => self.render(el, ctx)
					);
				}
			});
		});
	},

	async render(el, ctx) {
		const self = TcKsnkScr66;
		const filters = ctx.filters;
		el.innerHTML = ctx.state("loading");
		el.onclick = (event) => {
			if (event.target.closest('[data-action="retry"]')) self.render(el, ctx);
		};
		try {
			const data = await ctx.get(TC_IND_BOARD, {
				year: filters.year || undefined,
				period: filters.period || undefined,
				department: filters.department || undefined,
				chart: self.chartCode || undefined,
			});
			if (!ctx.isCurrent()) return;
			let sa = null;
			try {
				sa = await ctx.get(TC_IND_SELF, { year: data.year });
			} catch (error) {
				sa = null; // vai trò không đọc được tự đánh giá (R10/R11/R13 đọc được theo ma trận)
			}
			if (!ctx.isCurrent()) return;
			let dz = null;
			if (frappe.user.has_role("TC R01")) {
				try {
					const [sections, list] = await Promise.all([
						ctx.get(TC_DOSSIER_SECTIONS, {}),
						ctx.get(TC_DOSSIER_LIST, {}),
					]);
					dz = { sections: sections.sections, dossiers: list.dossiers };
				} catch (error) {
					dz = null; // khối gói hồ sơ không chặn bảng chỉ số
				}
			}
			if (!ctx.isCurrent()) return;
			el.innerHTML = self.pageHtml(data, sa, ctx, dz);
			self.bind(el, ctx, data);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkScreens["chi-so"] = TcKsnkScr66;
window.TcKsnkScr66 = TcKsnkScr66;
