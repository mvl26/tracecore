/* global tracecore */
// SCR-59 Kết quả vi sinh & vi khuẩn đa kháng (FEAT-067; UC-51; FR-M14-01..05, FR-M14-08; A-131, A-136).
// Nhập file WHONET/CSV qua hồ sơ ánh xạ (kiểm từng dòng → ghi sổ dòng hợp lệ), nhập tay có bước xác nhận, chủng đa
// kháng chưa xử lý, chủng mới trong 7 ngày (mã người bệnh luôn đã che), kháng sinh đồ quý trên chủng đầu tiên.
// Trạng thái luôn có chữ (Đa kháng, Chủng đầu tiên, Đã từng mang…), không chỉ màu. Lỗi chặn hiện alert-error inline
// theo thứ tự kết quả → lý do → hành động (design.md §6); không hộp thoại.

const TC_MICRO_OVERVIEW = "tracecore.v1.micro.overview";
const TC_MICRO_PREVIEW = "tracecore.v1.micro.manual_preview";
const TC_MICRO_MANUAL = "tracecore.v1.micro.manual_entry";
const TC_MICRO_CHECK = "tracecore.v1.imports.check";
const TC_MICRO_RUN = "tracecore.v1.imports.run";
const TC_MICRO_BATCH = "tracecore.v1.imports.batch";
const TC_MICRO_ISSUE_LIMIT = 50;
const TC_MICRO_ABX_ROWS = 4;
const TC_MICRO_SEXES = ["Male", "Female", "Other"];
const TC_MICRO_RESULTS = ["S", "I", "R"];

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr59 = {
	date(value) {
		if (!value) return "—";
		const [y, m, d] = String(value).slice(0, 10).split("-");
		return `${d}/${m}/${y}`;
	},

	time(value) {
		if (!value) return "—";
		const text = String(value);
		return `${text.slice(11, 16)} ${TcKsnkScr59.date(text)}`;
	},

	pct(value) {
		return `${Number(value || 0)
			.toFixed(1)
			.replace(".", ",")} %`;
	},

	stepsHtml(stage, esc) {
		const steps = [
			__("Choose file"),
			__("Map columns"),
			__("Check each row"),
			__("Save", null, "Microbiology import"),
		];
		const items = steps
			.map((label, index) => {
				const state = index < stage ? "is-done" : index === stage ? "is-current" : "";
				const mark = index < stage ? "✓" : String(index + 1);
				return (
					`<li class="tc-ksnk-step ${state}"${
						index === stage ? ' aria-current="step"' : ""
					}>` + `<span class="tc-ksnk-step-mark">${esc(mark)}</span> ${esc(label)}</li>`
				);
			})
			.join("");
		return `<ol class="tc-ksnk-steps">${items}</ol>`;
	},

	statsHtml(check, esc) {
		const tiles = [
			[__("Total rows"), check.total, ""],
			[__("Valid"), check.valid, ""],
			[
				__("Duplicates (lab sample ID, organism) — skipped"),
				(check.existing || []).length,
				"",
			],
			[
				__("Errors"),
				(check.issues || []).length,
				(check.issues || []).length ? " is-fail" : "",
			],
		];
		return (
			`<div class="tc-ksnk-stats">` +
			tiles
				.map(
					([label, value, cls]) =>
						`<div class="tc-ksnk-stat${cls}"><span class="tc-ksnk-stat-value">${esc(
							value
						)}</span><span>${esc(label)}</span></div>`
				)
				.join("") +
			`</div>`
		);
	},

	issuesHtml(issues, esc) {
		if (!issues || !issues.length) return "";
		const rows = issues
			.slice(0, TC_MICRO_ISSUE_LIMIT)
			.map(
				(issue) =>
					`<tr><td class="is-num">${esc(
						issue.row
					)}</td><td><code class="tc-ksnk-code">${esc(
						issue.field || ""
					)}</code></td><td>${esc(issue.reason)}</td></tr>`
			)
			.join("");
		const more =
			issues.length > TC_MICRO_ISSUE_LIMIT
				? `<p class="tc-ksnk-note">${esc(
						__("Only the first {0} errors are listed.", [TC_MICRO_ISSUE_LIMIT])
				  )}</p>`
				: "";
		return (
			`<div class="tc-ksnk-alert" role="alert"><strong>${esc(
				__("{0} row(s) with errors are not saved", [issues.length])
			)}</strong>` +
			`<div>${esc(__("Each error below gives the file row number and the reason."))}</div>` +
			`<div>${esc(
				__("Correct the file and check it again, or save only the valid rows.")
			)}</div>` +
			`</div><table class="tc-ksnk-table"><thead><tr><th scope="col" class="is-num">${esc(
				__("Row")
			)}</th>` +
			`<th scope="col">${esc(__("Column"))}</th><th scope="col">${esc(
				__("Reason")
			)}</th></tr></thead><tbody>${rows}</tbody></table>${more}`
		);
	},

	warningsHtml(warnings, esc) {
		return (warnings || [])
			.map((w) => `<div class="tc-ksnk-alert is-warn" role="status">${esc(w)}</div>`)
			.join("");
	},

	importHtml(data, state, esc) {
		if (!data.can_import) return "";
		const options = (data.profiles || [])
			.map(
				(p) =>
					`<option value="${esc(p.name)}"${
						p.name === state.profile ? " selected" : ""
					}>${esc(p.name)} (${esc(p.file_format)})</option>`
			)
			.join("");
		const noProfile = (data.profiles || []).length
			? ""
			: `<div class="tc-ksnk-alert is-warn" role="status">${esc(
					__("No mapping profile for microbiology files yet.")
			  )} <a href="/app/import-mapping-profile/new">${esc(
					__("Create mapping profile")
			  )}</a></div>`;
		const stage = state.check ? 2 : state.file_url ? 1 : 0;
		const check = state.check
			? TcKsnkScr59.statsHtml(state.check, esc) +
			  TcKsnkScr59.warningsHtml(state.check.warnings, esc) +
			  TcKsnkScr59.issuesHtml(state.check.issues, esc)
			: "";
		const run =
			state.check && state.check.valid
				? `<button type="button" class="btn btn-primary" data-action="run">${esc(
						__("Save {0} valid rows", [state.check.valid])
				  )}</button> `
				: "";
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Import microbiology file"))} ` +
			`<code class="tc-ksnk-tag">Import Batch</code></h3>` +
			TcKsnkScr59.stepsHtml(stage, esc) +
			noProfile +
			`<div class="tc-ksnk-filters"><label>${esc(__("Mapping profile"))}` +
			`<select class="form-control" data-input="profile"><option value=""></option>${options}</select></label>` +
			`<label>${esc(__("File"))}<span>` +
			`<button type="button" class="btn btn-default" data-action="choose">${esc(
				__("Choose file")
			)}</button> ` +
			`<span class="tc-ksnk-code">${esc(
				state.file_name || ""
			)}</span></span></label></div>` +
			`<div class="tc-ksnk-actions"><button type="button" class="btn btn-default" data-action="check"${
				state.profile && state.file_url ? "" : " disabled"
			}>${esc(__("Check each row"))}</button> ${run}` +
			`<button type="button" class="btn btn-default" data-action="manual">${esc(
				__("Manual entry when there is no file")
			)}</button></div>` +
			`<div data-region="import-result">${check}</div>` +
			`<div data-region="manual"></div></section>`
		);
	},

	pendingHtml(pending, esc) {
		if (!pending || !pending.count) return "";
		return (
			`<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
				__("{0} new multidrug-resistant isolate(s) not handled yet", [pending.count])
			)}</strong> ` +
			`${esc(
				__(
					"Infection control staff, the department and its network members were notified at {0}.",
					[TcKsnkScr59.time(pending.first_sent)]
				)
			)} ` +
			`<a href="/app/notifications">${esc(__("Open notifications"))}</a></div>`
		);
	},

	mdroBadge(row, esc) {
		return row.is_mdro
			? `<span class="tc-ksnk-badge is-fail">${esc(row.mdro_flags)}</span>` +
					TcKsnkScr59.isolationLink(row, esc)
			: `<span class="tc-ksnk-badge is-neutral">${esc(__("No"))}</span>`;
	},

	// FEAT-068 (A-136 Q5, A-146 Q4): mở SCR-60 với form tạo lệnh cách ly điền sẵn từ chủng đa kháng
	isolationLink(row, esc) {
		return ` <a class="btn btn-default btn-xs" href="/app/tc-ksnk/cach-ly?isolate=${encodeURIComponent(
			row.name
		)}">${esc(__("Create isolation order"))}</a>`;
	},

	historyBadge(labels, esc) {
		return labels && labels.length
			? `<span class="tc-ksnk-badge is-warn">${esc(
					__("Previously carried {0}", [labels.join(", ")])
			  )}</span>`
			: "—";
	},

	recentHtml(rows, esc) {
		if (!rows.length) {
			return (
				`<section class="tc-ksnk-card"><h3>${esc(__("New isolates this week"))}</h3>` +
				`<div class="tc-ksnk-state is-empty">${esc(
					__("No isolate recorded in the last 7 days.")
				)}</div></section>`
			);
		}
		const body = rows
			.map(
				(row) =>
					`<tr><td><code class="tc-ksnk-code">${esc(row.name)}</code></td>` +
					`<td><code class="tc-ksnk-code">${esc(row.patient_code_masked)}</code></td>` +
					`<td>${esc(row.department_name || row.department)}</td><td>${esc(
						row.specimen_type || ""
					)}</td>` +
					`<td><em>${esc(
						row.organism_name || row.organism
					)}</em></td><td>${TcKsnkScr59.mdroBadge(row, esc)}</td>` +
					`<td>${esc(row.is_first_isolate ? __("Yes") : __("No (repeat)"))}</td>` +
					`<td>${TcKsnkScr59.historyBadge(row.history, esc)}</td></tr>`
			)
			.join("");
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("New isolates this week"))} ` +
			`<code class="tc-ksnk-tag">Microbiology Isolate · VS-</code></h3>` +
			`<table class="tc-ksnk-table"><thead><tr>` +
			[
				__("Isolate"),
				__("Patient code"),
				__("Department"),
				__("Specimen"),
				__("Organism", null, "Microbiology Isolate"),
				__("Multidrug resistant"),
				__("First isolate"),
				__("MDRO history"),
			]
				.map((label) => `<th scope="col">${esc(label)}</th>`)
				.join("") +
			`</tr></thead><tbody>${body}</tbody></table>` +
			`<p class="tc-ksnk-note">${esc(
				__(
					"Labels come from approved multidrug resistance rules; statistics use only the first isolate of each patient and organism in the quarter."
				)
			)}</p></section>`
		);
	},

	antibiogramHtml(data, esc) {
		const ab = data.antibiogram || {};
		const organisms = (data.organisms || [])
			.map(
				(o) =>
					`<option value="${esc(o.organism)}"${
						o.organism === ab.organism ? " selected" : ""
					}>${esc(o.organism_name || o.organism)} (${esc(o.first_isolates)})</option>`
			)
			.join("");
		const quarters = [1, 2, 3, 4]
			.map(
				(q) =>
					`<option value="${q}"${q === Number(data.quarter) ? " selected" : ""}>${esc(
						__("Quarter {0}", [q])
					)}</option>`
			)
			.join("");
		const rows = (ab.rows || [])
			.map(
				(row) =>
					`<tr><td>${esc(
						row.antibiotic_name || row.antibiotic
					)} <code class="tc-ksnk-code">${esc(row.antibiotic)}</code></td>` +
					`<td class="is-num">${esc(
						TcKsnkScr59.pct(row.s_pct)
					)}</td><td class="is-num">${esc(TcKsnkScr59.pct(row.i_pct))}</td>` +
					`<td class="is-num">${esc(
						TcKsnkScr59.pct(row.r_pct)
					)}</td><td class="is-num">${esc(row.tested)}</td>` +
					`<td>${
						row.small_sample
							? `<span class="tc-ksnk-badge is-warn">${esc(
									__("Small sample (n < {0})", [ab.threshold])
							  )}</span>`
							: ""
					}</td></tr>`
			)
			.join("");
		const table = rows
			? `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("Antibiotic")
			  )}</th>` +
			  `<th scope="col" class="is-num">S %</th><th scope="col" class="is-num">I %</th>` +
			  `<th scope="col" class="is-num">R %</th><th scope="col" class="is-num">${esc(
					__("Isolates tested")
			  )}</th>` +
			  `<th scope="col">${esc(__("Note"))}</th></tr></thead><tbody>${rows}</tbody></table>`
			: `<div class="tc-ksnk-state is-empty">${esc(
					__("No first isolate in this quarter.")
			  )}</div>`;
		const report = `${data.report}?year=${encodeURIComponent(
			data.year
		)}&quarter=${encodeURIComponent(data.quarter)}`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Antibiogram"))} <em>${esc(
				ab.organism_name || ""
			)}</em> ` +
			`<code class="tc-ksnk-tag">${esc(
				__("n = {0} first isolates", [ab.first_isolates || 0])
			)}</code></h3>` +
			`<div class="tc-ksnk-filters"><label>${esc(
				__("Year")
			)}<input type="number" class="form-control" data-input="year" value="${esc(
				data.year
			)}"></label>` +
			`<label>${esc(
				__("Quarter")
			)}<select class="form-control" data-input="quarter">${quarters}</select></label>` +
			`<label>${esc(
				__("Organism", null, "Microbiology Isolate")
			)}<select class="form-control" data-input="organism">${organisms}</select></label></div>` +
			`${table}<div class="tc-ksnk-actions"><a class="btn btn-primary" href="${esc(
				report
			)}">${esc(__("Export quarterly resistance report"))}</a></div></section>`
		);
	},

	rulesHtml(data, esc) {
		const r = data.rules || {};
		const draft = r.draft
			? ` <span class="tc-ksnk-badge is-warn">${esc(
					__("{0} draft(s) — R01 approval needed", [r.draft])
			  )}</span>`
			: "";
		return (
			`<p class="tc-ksnk-note">${esc(
				__("Approved multidrug resistance rules: {0}", [r.approved || 0])
			)}${draft} ` + `<a href="/app/mdro-rule">${esc(__("Open the rule list"))}</a></p>`
		);
	},

	manualFormHtml(data, esc) {
		const catalog = (data.catalog || [])
			.map((o) => `<option value="${esc(o.name)}">${esc(o.organism_name)}</option>`)
			.join("");
		const departments = (data.departments || [])
			.map((d) => `<option value="${esc(d.name)}">${esc(d.department_name)}</option>`)
			.join("");
		const sexes = TC_MICRO_SEXES.map(
			(s) => `<option value="${esc(s)}">${esc(__(s))}</option>`
		).join("");
		const results = TC_MICRO_RESULTS.map((r) => `<option value="${r}">${r}</option>`).join("");
		const field = (key, label, input) =>
			`<label>${esc(label)}${input.replace("<X", `<input data-manual="${key}"`)}</label>`;
		const abx = Array.from({ length: TC_MICRO_ABX_ROWS })
			.map(
				() =>
					`<tr data-abx-row><td><input class="form-control" data-abx="antibiotic"></td>` +
					`<td><select class="form-control" data-abx="result"><option value=""></option>${results}</select></td>` +
					`<td><input class="form-control" data-abx="mic"></td></tr>`
			)
			.join("");
		return (
			`<div class="tc-ksnk-card"><h3>${esc(__("Manual entry of a result"))}</h3>` +
			`<div class="tc-ksnk-filters">` +
			field("lab_sample_id", __("Lab Sample ID") + " *", '<X class="form-control">') +
			`<label>${esc(
				__("Organism Code")
			)} *<select class="form-control" data-manual="organism"><option value=""></option>${catalog}</select></label>` +
			field(
				"patient_code",
				__("Patient Code") + " *",
				'<X class="form-control" autocomplete="off">'
			) +
			field("birth_year", __("Birth Year"), '<X type="number" class="form-control">') +
			`<label>${esc(
				__("Sex")
			)}<select class="form-control" data-manual="sex"><option value=""></option>${sexes}</select></label>` +
			`<label>${esc(
				__("Department")
			)} *<select class="form-control" data-manual="department"><option value=""></option>${departments}</select></label>` +
			field("specimen_type", __("Specimen Type"), '<X class="form-control">') +
			field(
				"collected_on",
				__("Collection Date") + " *",
				'<X type="date" class="form-control">'
			) +
			`</div><table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
				__("Antibiotic Code")
			)}</th>` +
			`<th scope="col">${esc(__("Result"))}</th><th scope="col">${esc(
				__("MIC or Zone")
			)}</th></tr></thead><tbody>${abx}</tbody></table>` +
			`<div class="tc-ksnk-actions"><button type="button" class="btn btn-default" data-action="preview">${esc(
				__("Check the result")
			)}</button></div><div data-region="manual-result"></div></div>`
		);
	},

	previewHtml(preview, esc) {
		const rows = (preview.susceptibility || [])
			.map((r) => `${r.antibiotic} ${r.result}${r.mic ? ` (${r.mic})` : ""}`)
			.join(", ");
		const labels = preview.mdro_labels.length
			? `<span class="tc-ksnk-badge is-fail">${esc(preview.mdro_labels.join(", "))}</span>`
			: `<span class="tc-ksnk-badge is-neutral">${esc(
					__("Not multidrug resistant")
			  )}</span>`;
		return (
			`<div class="tc-ksnk-alert is-info" role="status"><strong>${esc(
				__("Check before saving")
			)}</strong>` +
			`<div><code class="tc-ksnk-code">${esc(preview.lab_sample_id)}</code> · <em>${esc(
				preview.organism_name
			)}</em> · ` +
			`<code class="tc-ksnk-code">${esc(preview.patient_code_masked)}</code> · ${esc(
				preview.department_name
			)} · ${esc(TcKsnkScr59.date(preview.collected_on))}</div>` +
			`<div>${esc(rows)} ${labels}</div></div>` +
			`<div class="tc-ksnk-actions"><button type="button" class="btn btn-primary" data-action="confirm">${esc(
				__("Confirm and save")
			)}</button></div>`
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

	pageHtml(data, state, esc) {
		const self = TcKsnkScr59;
		return (
			self.importHtml(data, state, esc) +
			self.pendingHtml(data.pending, esc) +
			(data.can_read_isolates ? self.recentHtml(data.recent || [], esc) : "") +
			self.antibiogramHtml(data, esc) +
			self.rulesHtml(data, esc)
		);
	},

	manualValues(el) {
		const values = {};
		el.querySelectorAll("[data-manual]").forEach((input) => {
			values[input.dataset.manual] = input.value.trim() || null;
		});
		const susceptibility = [];
		el.querySelectorAll("[data-abx-row]").forEach((row) => {
			const get = (key) => row.querySelector(`[data-abx="${key}"]`).value.trim();
			if (get("antibiotic") || get("result")) {
				susceptibility.push({
					antibiotic: get("antibiotic"),
					result: get("result"),
					mic: get("mic") || null,
				});
			}
		});
		return { values, susceptibility };
	},

	region(el, name, html) {
		const target = el.querySelector(`[data-region="${name}"]`);
		if (target) target.innerHTML = html;
	},

	chooseFile(el, ctx, state) {
		const profile = (state.data.profiles || []).find((p) => p.name === state.profile);
		const extension = profile && profile.file_format === "CSV" ? ".csv" : ".xlsx";
		new frappe.ui.FileUploader({
			make_attachments_public: false,
			disable_file_browser: true,
			restrictions: { allowed_file_types: [extension], max_number_of_files: 1 },
			on_success: (file) => {
				Object.assign(state, {
					file_url: file.file_url,
					file_name: file.file_name,
					check: null,
					pending: null,
				});
				TcKsnkScr59.paint(el, ctx, state);
			},
		});
	},

	async check(el, ctx, state) {
		const outcome = await tracecore.codes.send(TC_MICRO_CHECK, null, {
			kind: state.data.import_kind,
			file_url: state.file_url,
			profile: state.profile,
		});
		if (!ctx.isCurrent()) return;
		if (!outcome.ok) {
			state.check = null;
			TcKsnkScr59.paint(el, ctx, state);
			TcKsnkScr59.region(el, "import-result", TcKsnkScr59.blockHtml(outcome.error, ctx.esc));
			return;
		}
		state.check = outcome.data;
		TcKsnkScr59.paint(el, ctx, state);
	},

	async run(el, ctx, state) {
		// một lần bấm Ghi sổ = một request cố định; gửi lại sau lỗi mạng dùng đúng khóa cũ
		if (!state.pending) {
			state.pending = tracecore.codes.new_request({
				kind: state.data.import_kind,
				file_url: state.file_url,
				profile: state.profile,
			});
		}
		const outcome = await tracecore.codes.send(TC_MICRO_RUN, state.pending);
		if (!ctx.isCurrent()) return;
		if (!outcome.ok) {
			if (!outcome.network) state.pending = null;
			TcKsnkScr59.region(el, "import-result", TcKsnkScr59.blockHtml(outcome.error, ctx.esc));
			return;
		}
		state.pending = null;
		const batch = await tracecore.codes.send(TC_MICRO_BATCH, null, {
			name: outcome.data.batch,
		});
		if (!ctx.isCurrent()) return;
		const b = batch.ok
			? batch.data
			: { name: outcome.data.batch, status: outcome.data.status };
		Object.assign(state, { file_url: null, file_name: null, check: null });
		await TcKsnkScr59.load(el, ctx, state);
		const message =
			b.status === "Done"
				? __("Import {0}: {1} saved, {2} already existed, {3} errors.", [
						b.name,
						b.created,
						b.skipped,
						b.failed,
				  ])
				: __("Import {0} is running in the background; reload the screen in a moment.", [
						b.name,
				  ]);
		TcKsnkScr59.region(
			el,
			"import-result",
			`<div class="tc-ksnk-alert is-info" role="status">${ctx.esc(message)}</div>`
		);
	},

	async preview(el, ctx, state) {
		const input = TcKsnkScr59.manualValues(el);
		const outcome = await tracecore.codes.send(TC_MICRO_PREVIEW, null, input);
		if (!ctx.isCurrent()) return;
		if (!outcome.ok) {
			state.manual = null;
			TcKsnkScr59.region(el, "manual-result", TcKsnkScr59.blockHtml(outcome.error, ctx.esc));
			return;
		}
		state.manual = tracecore.codes.new_request(Object.assign({ confirm: 1 }, input));
		TcKsnkScr59.region(
			el,
			"manual-result",
			TcKsnkScr59.previewHtml(outcome.data.preview, ctx.esc)
		);
		TcKsnkScr59.bind(el, ctx, state);
	},

	async confirm(el, ctx, state) {
		if (!state.manual) return;
		const outcome = await tracecore.codes.send(TC_MICRO_MANUAL, state.manual);
		if (!ctx.isCurrent()) return;
		if (!outcome.ok) {
			if (!outcome.network) state.manual = null;
			TcKsnkScr59.region(el, "manual-result", TcKsnkScr59.blockHtml(outcome.error, ctx.esc));
			return;
		}
		state.manual = null;
		await TcKsnkScr59.load(el, ctx, state);
		TcKsnkScr59.region(
			el,
			"import-result",
			`<div class="tc-ksnk-alert is-info" role="status">${ctx.esc(
				__("Isolate {0} saved.", [outcome.data.isolate])
			)}</div>`
		);
	},

	bind(el, ctx, state) {
		const self = TcKsnkScr59;
		el.querySelectorAll("[data-action]").forEach((button) => {
			if (button.dataset.bound) return;
			button.dataset.bound = "1";
			button.addEventListener("click", async () => {
				const action = button.dataset.action;
				if (action === "retry") return self.render(el, ctx);
				if (action === "choose") return self.chooseFile(el, ctx, state);
				if (action === "manual") {
					self.region(el, "manual", self.manualFormHtml(state.data, ctx.esc));
					return self.bind(el, ctx, state);
				}
				button.disabled = true;
				const handlers = {
					check: self.check,
					run: self.run,
					preview: self.preview,
					confirm: self.confirm,
				};
				if (handlers[action]) await handlers[action](el, ctx, state);
				button.disabled = false;
			});
		});
		el.querySelectorAll("[data-input]").forEach((input) => {
			if (input.dataset.bound) return;
			input.dataset.bound = "1";
			input.addEventListener("change", () => {
				const key = input.dataset.input;
				if (key === "profile") {
					Object.assign(state, { profile: input.value, check: null, pending: null });
					return self.paint(el, ctx, state);
				}
				state[key] = input.value;
				if (key === "quarter" || key === "year") state.organism = null;
				self.load(el, ctx, state);
			});
		});
	},

	paint(el, ctx, state) {
		el.innerHTML = TcKsnkScr59.pageHtml(state.data, state, ctx.esc);
		TcKsnkScr59.bind(el, ctx, state);
	},

	async load(el, ctx, state) {
		const data = await ctx.get(TC_MICRO_OVERVIEW, {
			year: state.year || null,
			quarter: state.quarter || null,
			organism: state.organism || null,
		});
		if (!ctx.isCurrent()) return;
		data.departments = ctx.departments || [];
		state.data = data;
		state.year = data.year;
		state.quarter = data.quarter;
		state.organism = data.antibiogram && data.antibiogram.organism;
		if (!state.profile && (data.profiles || []).length) state.profile = data.profiles[0].name;
		TcKsnkScr59.paint(el, ctx, state);
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		const state = {
			profile: null,
			file_url: null,
			file_name: null,
			check: null,
			pending: null,
		};
		try {
			await TcKsnkScr59.load(el, ctx, state);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
			TcKsnkScr59.bind(el, ctx, state);
		}
	},
};

window.TcKsnkScreens["vi-sinh"] = TcKsnkScr59;
window.TcKsnkScr59 = TcKsnkScr59;
