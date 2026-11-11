/* global tracecore, TcKsnk */
// SCR-49 Đào tạo KSNK, sinh viên thực tập (FEAT-059; UC-42; FR-M11-09..11; A-131, A-135).
// Thẻ chỉ số, tỷ lệ đào tạo KSNK cơ bản theo khoa (nhắc người chưa học), chuyên trách/Hội đồng/mạng lưới chưa đạt,
// sinh viên thực tập. Trạng thái luôn có chữ (server đã dịch), không chỉ màu. Sinh viên đào tạo muộn chỉ cảnh báo
// (A-135 c, không chặn); lỗi chặn của nút nhắc hiện alert-error inline: kết quả → lý do → hành động.
// FEAT-072 (A-149; FR-M11-12, FR-M11-13): thẻ dự án cải tiến, khối "Cải tiến chất lượng & đề tài" (giai đoạn PDCA có
// chữ) và khối tự đánh giá chất lượng hai năm liền theo mục.

const TC_TRAINING_STATUS = "tracecore.v1.ksnk_training.status";
const TC_IMPROVEMENT_STATUS = "tracecore.v1.ksnk_improvement.status"; // FEAT-072
const TC_TRAINING_REMIND = "tracecore.v1.ksnk_training.remind";
const TC_TRAINING_GROUPS = {
	full_time: "Full-time IC staff",
	committee: "Committee member",
	network: "Network member",
};

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr49 = {
	badge(status, label) {
		const cls = { ok: "is-pass", below: "is-warn" }[status] || "is-neutral";
		return { cls, label: label || "—" };
	},

	traineeBadge(status, label) {
		const cls = status === "Valid" ? "is-pass" : "is-fail";
		return { cls, label: label || "—" };
	},

	badgeHtml(b, esc) {
		return `<span class="tc-ksnk-badge ${b.cls}">${esc(b.label)}</span>`;
	},

	date(value) {
		if (!value) return "—";
		const [y, m, d] = String(value).split("-");
		return `${d}/${m}/${y}`;
	},

	levelClass(rate, target) {
		if (rate === null || rate === undefined || target === null || target === undefined)
			return "";
		return rate >= target ? "is-pass" : "is-warn";
	},

	kpiCard(cls, title, value, sub, esc) {
		return (
			`<article class="tc-ksnk-kpi${cls ? " " + cls : ""}"><span>${esc(title)}</span>` +
			`<b>${esc(value)}</b><small>${esc(sub)}</small></article>`
		);
	},

	kpiHtml(data, esc, improvement) {
		const self = TcKsnkScr49;
		const total = data.basic.total;
		const core = data.core.total;
		const trainees = data.trainees;
		const pending = (trainees.late || 0) + (trainees.not_trained || 0);
		const target =
			data.target !== null && data.target !== undefined
				? " · " + __("target ≥ {0} %", [data.target])
				: "";
		return (
			`<div class="tc-ksnk-kpis">` +
			self.kpiCard(
				self.levelClass(total.rate, data.target),
				__("Staff trained in basic infection control"),
				total.rate_label,
				__("{0}/{1} people", [total.trained, total.employees]) + target,
				esc
			) +
			self.kpiCard(
				core.people && core.passed < core.people ? "is-warn" : "is-pass",
				__("Full-time staff, committee and network trained"),
				core.rate_label,
				__("{0}/{1} people", [core.passed, core.people]),
				esc
			) +
			self.kpiCard(
				pending ? "is-fail" : "is-pass",
				__("Trainees not trained before the start date"),
				String(pending),
				__("{0} late · {1} not trained", [trainees.late || 0, trainees.not_trained || 0]),
				esc
			) +
			(improvement ? self.improvementKpi(improvement, esc) : "") +
			`</div>`
		);
	},

	departmentsHtml(data, readOnly, esc) {
		const self = TcKsnkScr49;
		const canRemind = data.can_remind && !readOnly;
		const rows = data.basic.departments
			.map((d) => {
				const count = (d.untrained || []).length;
				const action =
					canRemind && count
						? `<button type="button" class="btn btn-default btn-sm" data-action="remind" data-department="${esc(
								d.department
						  )}">${esc(__("Remind {0} people", [count]))}</button>`
						: count
						? esc(__("{0} not trained", [count]))
						: "—";
				return (
					`<tr><td>${esc(d.department_name)}</td><td class="is-num">${esc(
						d.employees
					)}</td>` +
					`<td class="is-num">${esc(d.trained)}</td><td class="is-num">${esc(
						d.rate_label
					)}</td>` +
					`<td>${self.badgeHtml(self.badge(d.status, d.status_label), esc)}</td>` +
					`<td>${action}</td></tr>`
				);
			})
			.join("");
		const table = rows
			? `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("Department")
			  )}</th>` +
			  `<th scope="col" class="is-num">${esc(__("Employees"))}</th>` +
			  `<th scope="col" class="is-num">${esc(__("Trained", null, "IC Training"))}</th>` +
			  `<th scope="col" class="is-num">${esc(__("Rate", null, "IC Training"))}</th>` +
			  `<th scope="col">${esc(__("Status"))}</th><th scope="col">${esc(
					__("Action")
			  )}</th></tr></thead>` +
			  `<tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-note">${esc(__("No department has staff in service."))}</p>`;
		const untagged = data.basic.untagged_events
			? `<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
					__("{0} training events have no IC category and are not counted.", [
						data.basic.untagged_events,
					])
			  )}</strong> ${esc(
					__("Set the IC training category on the training program.")
			  )}</div>`
			: "";
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Training rate by department"))} ` +
			`<code class="tc-ksnk-tag">HRMS Training Event / Training Result</code></h3>${table}` +
			`<p class="tc-ksnk-note">${esc(
				__(
					"Numerator: staff with a passed training result of a basic infection control program in the year; denominator: active employees of the department."
				)
			)}</p>${untagged}<div data-region="remind-alert"></div></section>`
		);
	},

	coreHtml(data, esc) {
		const pending = data.core.people.filter((p) => !p.passed);
		const rows = pending
			.map(
				(p) =>
					`<tr><td>${esc(p.employee_name || p.employee)}</td><td>${esc(
						p.department_name
					)}</td>` +
					`<td>${esc(
						(p.groups || []).map((g) => __(TC_TRAINING_GROUPS[g] || g)).join(", ")
					)}</td>` +
					`<td>${TcKsnkScr49.badgeHtml(
						{ cls: "is-fail", label: __("Not trained as required") },
						esc
					)}</td></tr>`
			)
			.join("");
		const body = rows
			? `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("Employee")
			  )}</th>` +
			  `<th scope="col">${esc(__("Department"))}</th><th scope="col">${esc(
					__("Group", null, "IC Training")
			  )}</th>` +
			  `<th scope="col">${esc(
					__("Status")
			  )}</th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-note">${esc(
					__("All full-time staff, committee and network members are trained.")
			  )}</p>`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(
				__("Full-time staff, committee and network not yet trained")
			)}</h3>${body}` +
			`<p class="tc-ksnk-note">${esc(
				__(
					"Passed: a class of their group's category in the year, or a valid certificate of an accepted IC type."
				)
			)} <a class="btn btn-default btn-sm" href="/app/ic-program-settings">${esc(
				__("Accepted certificate types")
			)}</a></p></section>`
		);
	},

	traineesHtml(data, esc) {
		const self = TcKsnkScr49;
		const t = data.trainees;
		const rows = t.rows
			.map(
				(r) =>
					`<tr><td><a href="/app/trainee-induction/${encodeURIComponent(
						r.name
					)}"><code class="tc-ksnk-code">${esc(r.name)}</code></a></td>` +
					`<td>${esc(r.school)}</td><td>${esc(r.department_name || r.department)}</td>` +
					`<td>${esc(self.date(r.period_from))}</td><td>${esc(
						self.date(r.trained_on)
					)}</td>` +
					`<td>${self.badgeHtml(
						self.traineeBadge(r.status, r.status_label),
						esc
					)}</td></tr>`
			)
			.join("");
		const late = t.rows.filter((r) => r.status === "Trained After Start").map((r) => r.name);
		const warning = late.length
			? `<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
					__("{0} trainees were trained after the internship start date", [late.length])
			  )}:</strong> ${esc(late.join(", "))}. ${esc(
					__("Move the training date or the start date.")
			  )}</div>`
			: "";
		const body = rows
			? `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("ID", null, "IC Training")
			  )}</th>` +
			  `<th scope="col">${esc(__("School"))}</th><th scope="col">${esc(
					__("Department")
			  )}</th>` +
			  `<th scope="col">${esc(__("Internship Start"))}</th><th scope="col">${esc(
					__("IC Training Date")
			  )}</th>` +
			  `<th scope="col">${esc(
					__("Status")
			  )}</th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-note">${esc(__("No trainees in this year."))}</p>`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Student interns"))} ` +
			`<code class="tc-ksnk-tag">Trainee Induction · SV-</code></h3>${body}${warning}` +
			TcKsnk.recordActions({
				doctype: "Trainee Induction",
				can_create: data.can_create_trainee !== false,
				create_label: __("Add trainee"),
			}) +
			`</section>`
		);
	},

	// --- FEAT-072: cải tiến chất lượng & đề tài, tự đánh giá ------------------------------------------------------

	improvementKpi(imp, esc) {
		const p = imp.improvement || {};
		return TcKsnkScr49.kpiCard(
			"",
			__("Improvement projects / research"),
			String(p.total || 0),
			__("{0} completed · {1} in progress", [p.completed || 0, p.in_progress || 0]),
			esc
		);
	},

	stageBadge(status, label) {
		const cls = { Completed: "is-pass", Cancelled: "is-neutral" }[status] || "is-info";
		return { cls, label: label || status || "—" };
	},

	improvementHtml(imp, esc) {
		const self = TcKsnkScr49;
		const rows = ((imp.improvement && imp.improvement.projects) || [])
			.map(
				(r) =>
					`<tr><td><a href="/app/ic-improvement-project/${encodeURIComponent(
						r.name
					)}"><code class="tc-ksnk-code">${esc(r.name)}</code></a></td>` +
					`<td>${esc(r.title)}<br><small>${esc(
						r.project_type_label || ""
					)}</small></td>` +
					`<td>${self.badgeHtml(self.stageBadge(r.status, r.status_label), esc)}</td>` +
					`<td>${esc(r.result_summary || "—")}</td></tr>`
			)
			.join("");
		const body = rows
			? `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("ID", null, "IC Training")
			  )}</th>` +
			  `<th scope="col">${esc(__("Project Title"))}</th><th scope="col">${esc(
					__("PDCA Stage")
			  )}</th>` +
			  `<th scope="col">${esc(
					__("Result Summary")
			  )}</th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-note">${esc(__("No improvement projects in this year."))}</p>`;
		const add = imp.can_edit
			? `<p class="tc-ksnk-note"><a class="btn btn-default btn-sm" href="/app/ic-improvement-project/new">${esc(
					__("Add improvement project")
			  )}</a></p>`
			: "";
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Quality improvement and research"))} ` +
			`<code class="tc-ksnk-tag">IC Improvement Project · CI-</code></h3>${body}${add}` +
			self.selfAssessmentHtml(imp, esc) +
			`</section>`
		);
	},

	scoreLabel(row) {
		if (!row) return "—";
		if (row.score_pct === null || row.score_pct === undefined) return __("not scored");
		return `${String(row.score_pct).replace(".", ",")} %`;
	},

	selfAssessmentHtml(imp, esc) {
		const self = TcKsnkScr49;
		const sa = imp.self_assessment || { items: [] };
		const open = imp.template
			? ` <a class="btn btn-default btn-sm" href="/app/audit-session/new?audit_template=${encodeURIComponent(
					imp.template
			  )}">${esc(__("Open form"))}</a>`
			: ` ${esc(
					__(
						"No approved self-assessment template yet: approve it on the audit template screen."
					)
			  )}`;
		const intro = `<div class="tc-ksnk-alert is-info" role="status">${esc(
			__(
				"The annual infection control quality self-assessment uses the audit template type Quality Self-Assessment."
			)
		)}${open}</div>`;
		// phiếu tự đánh giá đã ghi sổ (Audit Session): xem form, Hủy/sửa đổi theo quyền, In
		const sessionActions = (row) =>
			row && row.name
				? TcKsnk.recordActions({
						doctype: "Audit Session",
						name: row.name,
						docstatus: 1,
						can_write: !!imp.can_write_session,
				  })
				: "";
		if (!sa.current && !sa.previous) {
			return (
				intro +
				`<p class="tc-ksnk-note">${esc(
					__("No self-assessment posted for these two years.")
				)}</p>`
			);
		}
		const rows = (sa.items || [])
			.map(
				(r) =>
					`<tr><td>${esc(r.question)}<br><small>${esc(r.section)}</small></td>` +
					`<td>${esc(r.previous_label || "—")}</td><td>${esc(r.current_label || "—")}${
						r.changed
							? ` <span class="tc-ksnk-badge is-info">${esc(__("Changed"))}</span>`
							: ""
					}</td></tr>`
			)
			.join("");
		const note = sa.both
			? ""
			: `<p class="tc-ksnk-note">${esc(
					__("Only one of the two years has a posted self-assessment.")
			  )}</p>`;
		return (
			intro +
			sessionActions(sa.current || sa.previous) +
			`<h4>${esc(
				__("Quality self-assessment {0} vs {1}", [sa.year, sa.previous_year])
			)}</h4>` +
			`<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(__("Item"))}</th>` +
			`<th scope="col">${esc(String(sa.previous_year))}</th><th scope="col">${esc(
				String(sa.year)
			)}</th></tr></thead>` +
			`<tbody><tr class="is-total"><th scope="row">${esc(__("Score"))}</th><td>${esc(
				self.scoreLabel(sa.previous)
			)}</td>` +
			`<td>${esc(self.scoreLabel(sa.current))}</td></tr>${rows}</tbody></table>${note}`
		);
	},

	actionsHtml(data, esc) {
		return (
			`<div class="tc-ksnk-filters" data-region="actions">` +
			`<a class="btn btn-primary" href="/app/training-event">${esc(
				__("Open training schedule (HRMS)")
			)}</a> ` +
			`<a class="btn btn-default" href="/app/query-report/IC Training by Department?year=${esc(
				data.year
			)}">${esc(__("Export training report (Excel)"))}</a></div>`
		);
	},

	filtersHtml(data, ctx, esc) {
		const department = (ctx && ctx.filters && ctx.filters.department) || "";
		const options = ((ctx && ctx.departments) || [])
			.map(
				(d) =>
					`<option value="${esc(d.name)}"${
						d.name === department ? " selected" : ""
					}>${esc(d.department_name || d.name)}</option>`
			)
			.join("");
		return (
			`<div class="tc-ksnk-filters"><label>${esc(__("Year"))}` +
			`<input type="number" min="2000" max="2100" class="form-control" data-filter="year" value="${esc(
				data.year
			)}"></label>` +
			`<label>${esc(
				__("Department")
			)}<select class="form-control" data-filter="department">` +
			`<option value="">${esc(
				__("All departments")
			)}</option>${options}</select></label></div>`
		);
	},

	blockHtml(error, esc) {
		const e = error || {};
		return (
			`<div class="tc-ksnk-alert" role="alert"><strong>${esc(
				e.title || __("Not sent")
			)}</strong>` +
			`<div>${esc(e.reason || "")}</div><div>${esc(e.action || "")}</div></div>`
		);
	},

	pageHtml(data, ctx, esc, imp) {
		const self = TcKsnkScr49;
		const readOnly = !!(ctx && ctx.readOnly);
		// FEAT-072: sinh viên thực tập và cải tiến chất lượng hai cột (bố cục SCR-49)
		const lower = imp
			? `<div class="tc-ksnk-cols"><div>${self.traineesHtml(
					data,
					esc
			  )}</div><div>${self.improvementHtml(imp, esc)}</div></div>`
			: self.traineesHtml(data, esc);
		return (
			`<p class="tc-ksnk-head"><span class="tc-ksnk-badge is-info">${esc(
				__("Year {0}", [data.year])
			)}</span></p>` +
			self.filtersHtml(data, ctx, esc) +
			self.kpiHtml(data, esc, imp) +
			self.departmentsHtml(data, readOnly, esc) +
			self.coreHtml(data, esc) +
			lower +
			self.actionsHtml(data, esc)
		);
	},

	bind(el, ctx, data) {
		const self = TcKsnkScr49;
		const esc = ctx.esc;
		el.querySelectorAll("[data-filter]").forEach((input) => {
			input.addEventListener("change", () => {
				ctx.setFilters({ [input.dataset.filter]: input.value });
				self.render(el, ctx);
			});
		});
		el.querySelectorAll("[data-action]").forEach((button) => {
			button.addEventListener("click", () => {
				if (button.dataset.action === "retry") {
					self.render(el, ctx);
					return;
				}
				const region = el.querySelector('[data-region="remind-alert"]');
				button.disabled = true;
				tracecore.desk_call({
					method: TC_TRAINING_REMIND,
					args: { department: button.dataset.department, year: data && data.year },
					success: false, // kết quả gửi nhắc đã hiện inline ngay dưới
					on_ok: (result) => {
						if (!ctx.isCurrent() || !region) return;
						region.innerHTML = `<div class="tc-ksnk-alert is-info" role="status">${esc(
							__("Reminder sent to {0} people; {1} have no user account.", [
								result.sent,
								result.without_account,
							])
						)}</div>`;
					},
					on_block: (error) => {
						button.disabled = false;
						if (region) region.innerHTML = self.blockHtml(error, esc);
					},
					on_fail: () => {
						button.disabled = false;
					},
				});
			});
		});
	},

	paint(el, ctx, data, imp) {
		el.innerHTML = TcKsnkScr49.pageHtml(data, ctx, ctx.esc, imp);
		TcKsnkScr49.bind(el, ctx, data);
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const args = {};
			if (ctx.filters.year) args.year = ctx.filters.year;
			if (ctx.filters.department) args.department = ctx.filters.department;
			// FEAT-072: khối cải tiến & tự đánh giá theo năm (không lọc khoa — dự án không thuộc khoa)
			const [data, imp] = await Promise.all([
				ctx.get(TC_TRAINING_STATUS, args),
				ctx.get(TC_IMPROVEMENT_STATUS, args.year ? { year: args.year } : {}),
			]);
			if (!ctx.isCurrent()) return;
			TcKsnkScr49.paint(el, ctx, data, imp);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
			TcKsnkScr49.bind(el, ctx, null);
		}
	},
};

window.TcKsnkScreens["dao-tao"] = TcKsnkScr49;
window.TcKsnkScr49 = TcKsnkScr49;
