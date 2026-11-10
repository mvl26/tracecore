/* global tracecore */
// SCR-54 Hóa chất KSNK theo khoa–tháng & đơn vị thuê ngoài (FEAT-066; UC-46; FR-M12-12, FR-M12-13; A-131, A-142).
// Ba nguồn: phiếu xuất kho ERPNext tới kho khoa (tự động), file khoa Dược qua hồ sơ ánh xạ (kiểm từng dòng → ghi sổ),
// nhập tay có ghi nguồn và bước xác nhận. Bộ (tháng, khoa, hóa chất) có ≥ 2 nguồn hiện "Chờ xác nhận" và không vào
// tổng cho tới khi R09/R01 chọn nguồn giữ. Bảng đơn vị thuê ngoài: giấy phép, hợp đồng, phiếu giám sát gần nhất; giấy
// phép hết hạn chỉ cảnh báo (BRU-AUD-006). Trạng thái luôn có chữ; lỗi chặn hiện alert-error inline (design.md §6).

const TC_CHEM_OVERVIEW = "tracecore.v1.ic_chemical.overview";
const TC_CHEM_PREVIEW = "tracecore.v1.ic_chemical.manual_preview";
const TC_CHEM_MANUAL = "tracecore.v1.ic_chemical.manual_entry";
const TC_CHEM_CHOOSE = "tracecore.v1.ic_chemical.choose_source";
const TC_CHEM_CHECK = "tracecore.v1.imports.check";
const TC_CHEM_RUN = "tracecore.v1.imports.run";
const TC_CHEM_BATCH = "tracecore.v1.imports.batch";
const TC_CHEM_TYPES = [
	["Hand Rub", "Hand Rub (L)"],
	["Soap", "Soap (L)"],
	["Surface Disinfectant", "Surface Disinfectant (L)"],
	["Instrument Disinfectant", "Instrument Disinfectant (L)"],
	["Other", "Other (L)"],
];
const TC_CHEM_ISSUE_LIMIT = 50;
const TC_CHEM_QUARTERS_BACK = 7;

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr54 = {
	num(value, digits = 1) {
		if (value === null || value === undefined || value === "") return "—";
		const [whole, frac] = Math.abs(Number(value)).toFixed(digits).split(".");
		const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
		return `${Number(value) < 0 ? "-" : ""}${grouped}${frac ? `,${frac}` : ""}`;
	},

	date(value) {
		if (!value) return "—";
		const [y, m, d] = String(value).slice(0, 10).split("-");
		return `${d}/${m}/${y}`;
	},

	month(period) {
		const [y, m] = String(period || "").split("-");
		return m ? `${m}/${y}` : "—";
	},

	quarterOptions(data) {
		const out = [];
		const year = Number(data.year);
		const quarter = Number(data.quarter);
		const now = new Date();
		let y = now.getFullYear();
		let q = Math.floor(now.getMonth() / 3) + 1;
		for (let i = 0; i <= TC_CHEM_QUARTERS_BACK; i += 1) {
			out.push([y, q]);
			q -= 1;
			if (!q) {
				q = 4;
				y -= 1;
			}
		}
		if (!out.some(([oy, oq]) => oy === year && oq === quarter)) out.unshift([year, quarter]);
		return out;
	},

	sourceBadge(source, esc) {
		const labels = {
			"Stock Entry": __("Stock Entry"),
			Import: __("Import", null, "IC Chemical Consumption"),
			"Manual Entry": __("Manual Entry"),
		};
		return `<span class="tc-ksnk-tag">${esc(labels[source] || source)}</span>`;
	},

	toolbarHtml(data, esc) {
		const options = TcKsnkScr54.quarterOptions(data)
			.map(
				([y, q]) =>
					`<option value="${y}-${q}"${
						y === Number(data.year) && q === Number(data.quarter) ? " selected" : ""
					}>${esc(__("Quarter {0}/{1}", [q, y]))}</option>`
			)
			.join("");
		const report = `${data.report}?year=${encodeURIComponent(
			data.year
		)}&quarter=${encodeURIComponent(data.quarter)}`;
		const buttons = [
			data.can_import
				? `<button type="button" class="btn btn-default" data-action="import">${esc(
						__("Import pharmacy file")
				  )}</button>`
				: "",
			data.can_write
				? `<button type="button" class="btn btn-default" data-action="manual">${esc(
						__("Manual entry (with source)")
				  )}</button>`
				: "",
			`<a class="btn btn-primary" href="${esc(report)}">${esc(
				__("Quarterly chemical report")
			)}</a>`,
		].join(" ");
		return (
			`<div class="tc-ksnk-filters"><label>${esc(__("Period"))}` +
			`<select class="form-control" data-input="quarter">${options}</select></label>` +
			`<div class="tc-ksnk-actions">${buttons}</div></div>` +
			`<div data-region="import"></div><div data-region="manual"></div><div data-region="message"></div>`
		);
	},

	chemicalRow(entry, esc, name, total) {
		const cells = TC_CHEM_TYPES.map(
			([kind]) => `<td class="is-num">${esc(TcKsnkScr54.num(entry.litres[kind]))}</td>`
		).join("");
		const per1000 =
			entry.hand_rub_per_1000 === null || entry.hand_rub_per_1000 === undefined
				? esc(__("No denominator yet"))
				: esc(TcKsnkScr54.num(entry.hand_rub_per_1000));
		const sources = total
			? ""
			: (entry.sources || []).map((s) => TcKsnkScr54.sourceBadge(s, esc)).join(" ") +
			  (entry.awaiting
					? ` <span class="tc-ksnk-badge is-warn">${esc(
							__("Awaiting confirmation")
					  )}</span>`
					: "") +
			  (entry.no_litre
					? ` <span class="tc-ksnk-badge is-neutral">${esc(
							__("No litre conversion")
					  )}</span>`
					: "");
		const head = total ? `<th scope="row">${esc(name)}</th>` : `<td>${esc(name)}</td>`;
		return `<tr${
			total ? ' class="is-total"' : ""
		}>${head}${cells}<td class="is-num">${per1000}</td><td>${sources}</td></tr>`;
	},

	chemicalsHtml(data, esc) {
		const summary = data.summary || { departments: [], total: { litres: {} } };
		const head =
			`<tr><th scope="col">${esc(__("Department"))}</th>` +
			TC_CHEM_TYPES.map(
				([, label]) => `<th scope="col" class="is-num">${esc(__(label))}</th>`
			).join("") +
			`<th scope="col" class="is-num">${esc(
				__("Hand Rub per 1,000 Patient Days (L)")
			)}</th><th scope="col">${esc(__("Source"))}</th></tr>`;
		const body = summary.departments.length
			? summary.departments
					.map((d) => TcKsnkScr54.chemicalRow(d, esc, d.department_name, false))
					.join("") +
			  TcKsnkScr54.chemicalRow(
					summary.total,
					esc,
					__("Whole hospital ({0} departments)", [summary.total.departments || 0]),
					true
			  )
			: "";
		const table = body
			? `<table class="tc-ksnk-table"><thead>${head}</thead><tbody>${body}</tbody></table>`
			: `<div class="tc-ksnk-state is-empty">${esc(
					__("No infection control chemical recorded in this quarter.")
			  )}</div>`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("IC chemicals by department"))} ` +
			`<code class="tc-ksnk-tag">IC Chemical Consumption · HC-</code></h3>${table}` +
			`<div class="tc-ksnk-alert is-info" role="status">${esc(
				__(
					"Preferred source: ERPNext stock transfers to the department warehouse; otherwise the pharmacy file or a manual entry confirmed by the person entering it."
				)
			)}</div>${TcKsnkScr54.awaitingHtml(data, esc)}</section>`
		);
	},

	awaitingHtml(data, esc) {
		const rows = [];
		((data.summary && data.summary.departments) || []).forEach((d) => {
			(d.awaiting_items || []).forEach((item) => rows.push({ dept: d, item }));
		});
		if (!rows.length) return "";
		const body = rows
			.map(({ dept, item }, index) => {
				const choose = data.can_write
					? `<div class="tc-ksnk-inline"><select class="form-control" data-choose-source="${index}">` +
					  item.sources
							.map((s) => `<option value="${esc(s)}">${esc(__(s))}</option>`)
							.join("") +
					  `</select><input class="form-control" data-choose-reason="${index}" placeholder="${esc(
							__("Reason")
					  )}">` +
					  `<button type="button" class="btn btn-default" data-action="choose" data-index="${index}">${esc(
							__("Keep this source")
					  )}</button></div>`
					: esc(
							__(
								"Waiting for the materials accountant or the head of infection control to choose."
							)
					  );
				return (
					`<tr><td>${esc(dept.department_name)}</td><td>${esc(
						TcKsnkScr54.month(item.period)
					)}</td>` +
					`<td>${esc(item.item_name || item.item)} <code class="tc-ksnk-code">${esc(
						item.item
					)}</code></td>` +
					`<td>${item.sources
						.map((s) => TcKsnkScr54.sourceBadge(s, esc))
						.join(" ")}</td><td>${choose}</td></tr>`
				);
			})
			.join("");
		return (
			`<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
				__("{0} item(s) have two sources and are not counted", [rows.length])
			)}</strong> ${esc(
				__("Choose the source to keep; the other source is cancelled with your reason.")
			)}</div>` +
			`<table class="tc-ksnk-table" data-region="awaiting"><thead><tr><th scope="col">${esc(
				__("Department")
			)}</th>` +
			`<th scope="col">${esc(__("Month"))}</th><th scope="col">${esc(
				__("Item")
			)}</th><th scope="col">${esc(__("Sources"))}</th>` +
			`<th scope="col">${esc(__("Action"))}</th></tr></thead><tbody>${body}</tbody></table>`
		);
	},

	vendorState(vendor, esc) {
		if (vendor.state === "Expired") {
			return `<span class="tc-ksnk-badge is-fail">${esc(__("Expired"))}</span>`;
		}
		if (vendor.state === "Expiring") {
			return `<span class="tc-ksnk-badge is-warn">${esc(
				__("{0} days left", [vendor.days_left])
			)}</span>`;
		}
		if (vendor.state === "Valid") {
			return `<span class="tc-ksnk-badge is-pass">${esc(__("Valid"))}</span>`;
		}
		return `<span class="tc-ksnk-badge is-neutral">${esc(__("No license date"))}</span>`;
	},

	vendorsHtml(data, esc) {
		const list = data.vendors || [];
		const unaudited = new Set(data.unaudited || []);
		const rows = list
			.map((v) => {
				const last = v.last_session
					? `<code class="tc-ksnk-code">${esc(v.last_session.name)}</code> · ${esc(
							TcKsnkScr54.num(v.last_session.score_pct, 0)
					  )} %`
					: "—";
				const waste = v.waste_vendor
					? ` <a href="/app/waste-treatment-vendor/${encodeURIComponent(
							v.waste_vendor
					  )}">${esc(__("Waste vendor record"))}</a>`
					: "";
				const flag = unaudited.has(v.name)
					? ` <span class="tc-ksnk-badge is-warn">${esc(
							__("Not audited this quarter")
					  )}</span>`
					: "";
				const contract =
					v.tc_contract_from || v.tc_contract_to
						? `${TcKsnkScr54.date(v.tc_contract_from)}–${TcKsnkScr54.date(
								v.tc_contract_to
						  )}`
						: "—";
				return (
					`<tr><td><a href="/app/supplier/${encodeURIComponent(v.name)}">${esc(
						v.supplier_name
					)}</a>${waste}</td>` +
					`<td>${esc(__(v.tc_ic_service_type))}</td><td><code class="tc-ksnk-code">${esc(
						v.tc_license_no || "—"
					)}</code></td>` +
					`<td>${esc(TcKsnkScr54.date(v.tc_license_expiry))}</td><td>${esc(
						contract
					)}</td><td>${last}${flag}</td>` +
					`<td>${TcKsnkScr54.vendorState(v, esc)}</td></tr>`
				);
			})
			.join("");
		const table = rows
			? `<table class="tc-ksnk-table"><thead><tr>` +
			  [
					__("Vendor"),
					__("Service"),
					__("License No"),
					__("License Expiry"),
					__("Contract"),
					__("Latest vendor audit"),
					__("Status"),
			  ]
					.map((label) => `<th scope="col">${esc(label)}</th>`)
					.join("") +
			  `</tr></thead><tbody>${rows}</tbody></table>`
			: `<div class="tc-ksnk-state is-empty">${esc(
					__(
						"No outsourced vendor yet. Set the outsourced service on the supplier form to follow its license."
					)
			  )}</div>`;
		const expired = list.filter((v) => v.state === "Expired");
		const alert = expired.length
			? `<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
					__("License expired: {0}.", [expired.map((v) => v.supplier_name).join(", ")])
			  )}</strong> ${esc(
					__(
						"The system only warns and logs it; stopping the contract is a hospital decision. Reminders come 60, 30 and 7 days before."
					)
			  )}</div>`
			: "";
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Outsourced vendors"))} ` +
			`<code class="tc-ksnk-tag">${esc(
				__("ERPNext Supplier + license")
			)}</code></h3>${table}${alert}</section>`
		);
	},

	pageHtml(data, esc) {
		return (
			TcKsnkScr54.toolbarHtml(data, esc) +
			TcKsnkScr54.chemicalsHtml(data, esc) +
			TcKsnkScr54.vendorsHtml(data, esc)
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

	infoHtml(message, esc) {
		return `<div class="tc-ksnk-alert is-info" role="status">${esc(message)}</div>`;
	},

	importHtml(data, state, esc) {
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
					__("No mapping profile for chemical files yet.")
			  )} <a href="/app/import-mapping-profile/new">${esc(
					__("Create mapping profile")
			  )}</a></div>`;
		const check = state.check;
		const stats = check
			? `<div class="tc-ksnk-stats">` +
			  [
					[__("Total rows"), check.total, ""],
					[__("Valid"), check.valid, ""],
					[__("Already imported — skipped"), (check.existing || []).length, ""],
					[
						__("Errors"),
						(check.issues || []).length,
						(check.issues || []).length ? " is-fail" : "",
					],
			  ]
					.map(
						([label, value, cls]) =>
							`<div class="tc-ksnk-stat${cls}"><span class="tc-ksnk-stat-value">${esc(
								value
							)}</span><span>${esc(label)}</span></div>`
					)
					.join("") +
			  `</div>` +
			  TcKsnkScr54.issuesHtml(check.issues, esc)
			: "";
		const run =
			check && check.valid
				? `<button type="button" class="btn btn-primary" data-action="run">${esc(
						__("Save {0} valid rows", [check.valid])
				  )}</button>`
				: "";
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Import pharmacy file"))} ` +
			`<code class="tc-ksnk-tag">Import Batch</code></h3>${noProfile}` +
			`<div class="tc-ksnk-filters"><label>${esc(__("Mapping profile"))}` +
			`<select class="form-control" data-input="profile"><option value=""></option>${options}</select></label>` +
			`<label>${esc(
				__("File")
			)}<span><button type="button" class="btn btn-default" data-action="choose-file">${esc(
				__("Choose file")
			)}</button> <span class="tc-ksnk-code">${esc(
				state.file_name || ""
			)}</span></span></label></div>` +
			`<div class="tc-ksnk-actions"><button type="button" class="btn btn-default" data-action="check"${
				state.profile && state.file_url ? "" : " disabled"
			}>${esc(__("Check each row"))}</button> ${run}</div>` +
			`<div data-region="import-result">${stats}</div></section>`
		);
	},

	issuesHtml(issues, esc) {
		if (!issues || !issues.length) return "";
		const rows = issues
			.slice(0, TC_CHEM_ISSUE_LIMIT)
			.map(
				(issue) =>
					`<tr><td class="is-num">${esc(
						issue.row
					)}</td><td><code class="tc-ksnk-code">${esc(
						issue.field || ""
					)}</code></td><td>${esc(issue.reason)}</td></tr>`
			)
			.join("");
		return (
			`<div class="tc-ksnk-alert" role="alert"><strong>${esc(
				__("{0} row(s) with errors are not saved", [issues.length])
			)}</strong>` +
			`<div>${esc(__("Each error below gives the file row number and the reason."))}</div>` +
			`<div>${esc(
				__("Correct the file and check it again, or save only the valid rows.")
			)}</div></div>` +
			`<table class="tc-ksnk-table"><thead><tr><th scope="col" class="is-num">${esc(
				__("Row")
			)}</th><th scope="col">${esc(__("Column"))}</th><th scope="col">${esc(
				__("Reason")
			)}</th></tr></thead><tbody>${rows}</tbody></table>`
		);
	},

	manualHtml(data, ctx) {
		const esc = ctx.esc;
		const months = TcKsnkScr54.periodsOf(data)
			.map((p) => `<option value="${esc(p)}">${esc(TcKsnkScr54.month(p))}</option>`)
			.join("");
		const departments = (ctx.departments || [])
			.map((d) => `<option value="${esc(d.name)}">${esc(d.department_name)}</option>`)
			.join("");
		const items = (data.items || [])
			.map(
				(i) =>
					`<option value="${esc(i.name)}">${esc(i.item_name)} (${esc(
						i.stock_uom
					)})</option>`
			)
			.join("");
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Manual entry (with source)"))}</h3>` +
			`<div class="tc-ksnk-filters">` +
			`<label>${esc(
				__("Month")
			)} *<select class="form-control" data-manual="period">${months}</select></label>` +
			`<label>${esc(
				__("Department")
			)} *<select class="form-control" data-manual="department"><option value=""></option>${departments}</select></label>` +
			`<label>${esc(
				__("Item")
			)} *<select class="form-control" data-manual="item"><option value=""></option>${items}</select></label>` +
			`<label>${esc(
				__("Quantity")
			)} *<input type="number" min="0" step="any" class="form-control" data-manual="qty"></label>` +
			`<label>${esc(
				__("Source Note")
			)} *<input class="form-control" data-manual="source_note"></label></div>` +
			`<div class="tc-ksnk-actions"><button type="button" class="btn btn-default" data-action="preview">${esc(
				__("Check the entry")
			)}</button></div><div data-region="manual-result"></div></section>`
		);
	},

	periodsOf(data) {
		const q = Number(data.quarter);
		return [q * 3 - 2, q * 3 - 1, q * 3].map(
			(m) => `${data.year}-${String(m).padStart(2, "0")}`
		);
	},

	previewHtml(preview, esc) {
		const litres =
			preview.litres === null || preview.litres === undefined
				? __("No litre conversion")
				: __("{0} L", [TcKsnkScr54.num(preview.litres)]);
		const other = (preview.other_sources || []).length
			? `<div class="tc-ksnk-alert is-warn" role="status">${esc(
					__(
						"This month already has data from {0}; after saving, the item waits for a source to be chosen.",
						[preview.other_sources.map((s) => __(s)).join(", ")]
					)
			  )}</div>`
			: "";
		return (
			`<div class="tc-ksnk-alert is-info" role="status"><strong>${esc(
				__("Check before saving")
			)}</strong>` +
			`<div>${esc(TcKsnkScr54.month(preview.period))} · ${esc(
				preview.department_name
			)} · ${esc(preview.item_name)} · ` +
			`${esc(TcKsnkScr54.num(preview.qty, 2))} ${esc(preview.uom)} (${esc(litres)})</div>` +
			`<div>${esc(__("Source Note"))}: ${esc(preview.source_note)}</div></div>${other}` +
			`<div class="tc-ksnk-actions"><button type="button" class="btn btn-primary" data-action="confirm">${esc(
				__("Confirm and save")
			)}</button></div>`
		);
	},

	region(el, name, html) {
		const target = el.querySelector(`[data-region="${name}"]`);
		if (target) target.innerHTML = html;
	},

	manualValues(el) {
		const values = {};
		el.querySelectorAll("[data-manual]").forEach((input) => {
			values[input.dataset.manual] = input.value.trim() || null;
		});
		return values;
	},

	awaitingRows(data) {
		const rows = [];
		((data.summary && data.summary.departments) || []).forEach((d) => {
			(d.awaiting_items || []).forEach((item) => rows.push({ dept: d, item }));
		});
		return rows;
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
				TcKsnkScr54.showImport(el, ctx, state);
			},
		});
	},

	showImport(el, ctx, state) {
		TcKsnkScr54.region(el, "import", TcKsnkScr54.importHtml(state.data, state, ctx.esc));
		TcKsnkScr54.bind(el, ctx, state);
	},

	async check(el, ctx, state) {
		const outcome = await tracecore.codes.send(TC_CHEM_CHECK, null, {
			kind: state.data.import_kind,
			file_url: state.file_url,
			profile: state.profile,
		});
		if (!ctx.isCurrent()) return;
		state.check = outcome.ok ? outcome.data : null;
		TcKsnkScr54.showImport(el, ctx, state);
		if (!outcome.ok) {
			TcKsnkScr54.region(el, "import-result", TcKsnkScr54.blockHtml(outcome.error, ctx.esc));
		}
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
		const outcome = await tracecore.codes.send(TC_CHEM_RUN, state.pending);
		if (!ctx.isCurrent()) return;
		if (!outcome.ok) {
			if (!outcome.network) state.pending = null;
			TcKsnkScr54.region(el, "import-result", TcKsnkScr54.blockHtml(outcome.error, ctx.esc));
			return;
		}
		state.pending = null;
		const batch = await tracecore.codes.send(TC_CHEM_BATCH, null, {
			name: outcome.data.batch,
		});
		if (!ctx.isCurrent()) return;
		const b = batch.ok
			? batch.data
			: { name: outcome.data.batch, status: outcome.data.status };
		Object.assign(state, { file_url: null, file_name: null, check: null, panel: null });
		await TcKsnkScr54.load(el, ctx, state);
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
		TcKsnkScr54.region(el, "message", TcKsnkScr54.infoHtml(message, ctx.esc));
	},

	async preview(el, ctx, state) {
		const values = TcKsnkScr54.manualValues(el);
		const outcome = await tracecore.codes.send(TC_CHEM_PREVIEW, null, {
			values: JSON.stringify(values),
		});
		if (!ctx.isCurrent()) return;
		if (!outcome.ok) {
			state.manual = null;
			TcKsnkScr54.region(el, "manual-result", TcKsnkScr54.blockHtml(outcome.error, ctx.esc));
			return;
		}
		state.manual = tracecore.codes.new_request({ values: JSON.stringify(values), confirm: 1 });
		TcKsnkScr54.region(
			el,
			"manual-result",
			TcKsnkScr54.previewHtml(outcome.data.preview, ctx.esc)
		);
		TcKsnkScr54.bind(el, ctx, state);
	},

	async confirm(el, ctx, state) {
		if (!state.manual) return;
		const outcome = await tracecore.codes.send(TC_CHEM_MANUAL, state.manual);
		if (!ctx.isCurrent()) return;
		if (!outcome.ok) {
			if (!outcome.network) state.manual = null;
			TcKsnkScr54.region(el, "manual-result", TcKsnkScr54.blockHtml(outcome.error, ctx.esc));
			return;
		}
		state.manual = null;
		state.panel = null;
		await TcKsnkScr54.load(el, ctx, state);
		TcKsnkScr54.region(
			el,
			"message",
			TcKsnkScr54.infoHtml(
				__("Chemical consumption {0} saved.", [outcome.data.name]),
				ctx.esc
			)
		);
	},

	async choose(el, ctx, state, index) {
		const row = TcKsnkScr54.awaitingRows(state.data)[Number(index)];
		if (!row) return;
		const source = el.querySelector(`[data-choose-source="${index}"]`).value;
		const reason = el.querySelector(`[data-choose-reason="${index}"]`).value.trim();
		const outcome = await tracecore.codes.send(
			TC_CHEM_CHOOSE,
			tracecore.codes.new_request({
				period: row.item.period,
				department: row.dept.department,
				item: row.item.item,
				source,
				reason,
			})
		);
		if (!ctx.isCurrent()) return;
		if (!outcome.ok) {
			TcKsnkScr54.region(el, "message", TcKsnkScr54.blockHtml(outcome.error, ctx.esc));
			return;
		}
		await TcKsnkScr54.load(el, ctx, state);
		TcKsnkScr54.region(
			el,
			"message",
			TcKsnkScr54.infoHtml(
				__("Source kept; {0} record(s) of the other source cancelled.", [
					outcome.data.cancelled.length,
				]),
				ctx.esc
			)
		);
	},

	bind(el, ctx, state) {
		const self = TcKsnkScr54;
		el.querySelectorAll("[data-action]").forEach((button) => {
			if (button.dataset.bound) return;
			button.dataset.bound = "1";
			button.addEventListener("click", async () => {
				const action = button.dataset.action;
				if (action === "retry") return self.render(el, ctx);
				if (action === "import") {
					state.panel = "import";
					self.region(el, "manual", "");
					return self.showImport(el, ctx, state);
				}
				if (action === "manual") {
					state.panel = "manual";
					self.region(el, "import", "");
					self.region(el, "manual", self.manualHtml(state.data, ctx));
					return self.bind(el, ctx, state);
				}
				if (action === "choose-file") return self.chooseFile(el, ctx, state);
				button.disabled = true;
				if (action === "choose") await self.choose(el, ctx, state, button.dataset.index);
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
				if (input.dataset.input === "profile") {
					Object.assign(state, { profile: input.value, check: null, pending: null });
					return self.showImport(el, ctx, state);
				}
				const [year, quarter] = input.value.split("-");
				Object.assign(state, { year, quarter, panel: null });
				self.load(el, ctx, state);
			});
		});
	},

	async load(el, ctx, state) {
		const data = await ctx.get(TC_CHEM_OVERVIEW, {
			year: state.year || null,
			quarter: state.quarter || null,
		});
		if (!ctx.isCurrent()) return;
		state.data = data;
		state.year = data.year;
		state.quarter = data.quarter;
		if (!state.profile && (data.profiles || []).length) state.profile = data.profiles[0].name;
		el.innerHTML = TcKsnkScr54.pageHtml(data, ctx.esc);
		TcKsnkScr54.bind(el, ctx, state);
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
			await TcKsnkScr54.load(el, ctx, state);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
			TcKsnkScr54.bind(el, ctx, state);
		}
	},
};

window.TcKsnkScreens["hoa-chat"] = TcKsnkScr54;
window.TcKsnkScr54 = TcKsnkScr54;
