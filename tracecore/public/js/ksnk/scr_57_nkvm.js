/* global tracecore, TcKsnk */
// SCR-57 Giám sát NKVM (FEAT-064; UC-49; FR-M13-07, 07.1, 07.2, 08, 08.1, 09; BRU-HAI-003, 004, 005; A-147 k).
// 4 KPI (ca đang theo dõi, tỷ lệ NKVM tháng trước, KSDP đúng thời điểm, cuộc gọi theo dõi hôm nay); form đăng ký phẫu
// thuật (mã BN chỉ nhập mới — ca có sẵn hiện bản che), NNIS và cửa sổ do server tính; lịch theo dõi sau ra viện (ghi
// kết quả, tạo ca NKBV khi nghi ngờ, đóng ca ra viện sau cửa sổ); ca phẫu thuật gần đây; lần theo dõi đến hạn.
// Lỗi chặn hiện alert đỏ inline (kết quả → lý do → hành động). Trạng thái luôn có chữ, không chỉ màu.

const TC_SSI = "tracecore.v1.ssi.";
const TC_SSI_WOUNDS = ["Clean", "Clean-Contaminated", "Contaminated", "Dirty"];
const TC_SSI_RESULTS = ["Negative", "SSI suspected", "Unreachable"];
// giá trị Select của NKVM dịch theo context DocType (vd "Late" = "Muộn (sau rạch da)", khác "Báo muộn")
const TC_SSI_CTX = "Surgical Surveillance";

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr57 = {
	selected: null,

	date(value) {
		if (!value) return "—";
		const [y, m, d] = String(value).slice(0, 10).split("-");
		return `${d}/${m}/${y}`;
	},

	pct(value) {
		if (value === null || value === undefined) return __("Not calculated");
		return `${Number(value).toFixed(1).replace(".", ",")} %`;
	},

	month(value) {
		if (!value) return "—";
		const [y, m] = String(value).split("-");
		return `${m}/${y}`;
	},

	outcomeBadge(outcome, esc) {
		const tone =
			{ "No SSI": "is-pass", SSI: "is-fail", "Lost to Follow-up": "is-neutral" }[outcome] ||
			"is-info";
		return `<span class="tc-ksnk-badge ${tone}">${esc(
			__(outcome || "Under Surveillance", null, TC_SSI_CTX)
		)}</span>`;
	},

	timingBadge(timing, esc) {
		const tone =
			{ "On time": "is-pass", Late: "is-warn", "Too early": "is-warn" }[timing] ||
			"is-neutral";
		return `<span class="tc-ksnk-badge ${tone}">${esc(
			__(timing || "Not assessed", null, TC_SSI_CTX)
		)}</span>`;
	},

	followupBadge(row, esc, today) {
		if (row.done_on) {
			const tone =
				{ Negative: "is-pass", "SSI suspected": "is-fail" }[row.result] || "is-neutral";
			return `<span class="tc-ksnk-badge ${tone}">${esc(
				__(row.result, null, TC_SSI_CTX)
			)}</span>`;
		}
		const due = String(row.due_date).slice(0, 10);
		if (due === today)
			return `<span class="tc-ksnk-badge is-warn">${esc(__("Due today"))}</span>`;
		if (due < today) return `<span class="tc-ksnk-badge is-fail">${esc(__("Overdue"))}</span>`;
		return `<span class="tc-ksnk-badge is-neutral">${esc(__("Not yet due"))}</span>`;
	},

	today() {
		return frappe.datetime.get_today();
	},

	kpisHtml(k, esc) {
		const self = TcKsnkScr57;
		const tile = (label, value, tone) =>
			`<div class="tc-ksnk-kpi${tone ? ` ${tone}` : ""}"><span>${esc(
				label
			)}</span><strong>${esc(value)}</strong></div>`;
		return (
			`<div class="tc-ksnk-kpis">` +
			tile(__("Surgeries under surveillance"), String(k.under_surveillance || 0)) +
			tile(
				__("SSI rate ({0})", [self.month(k.ssi_month)]),
				self.pct(k.ssi_rate),
				"is-pass"
			) +
			tile(__("Prophylaxis on time"), self.pct(k.on_time_rate), "is-pass") +
			tile(
				__("Follow-up calls today"),
				String(k.due_today || 0),
				k.due_today ? "is-warn" : ""
			) +
			`</div>`
		);
	},

	option(value, label, chosen, esc) {
		return `<option value="${esc(value)}"${
			String(value) === String(chosen ?? "") ? " selected" : ""
		}>${esc(label)}</option>`;
	},

	field(label, control, esc, required) {
		return `<label>${esc(label)}${required ? " *" : ""}${control}</label>`;
	},

	formHtml(data, d, departments, esc) {
		const self = TcKsnkScr57;
		const v = d || {};
		const input = (name, type, value, extra) =>
			`<input class="form-control" type="${type}" data-field="${name}" value="${esc(
				value ?? ""
			)}"${extra || ""}>`;
		const select = (name, options, chosen, required) =>
			`<select class="form-control" data-field="${name}"${
				required ? ' aria-required="true"' : ""
			}><option value="">${esc(__("— Choose —"))}</option>${options
				.map(([value, label]) => self.option(value, label, chosen, esc))
				.join("")}</select>`;
		const groups = (data.groups || []).map((g) => [
			g.name,
			g.t_time_minutes
				? `${g.group_name} — T ${g.t_time_minutes}${
						g.has_implant ? ` (${__("implant")})` : ""
				  }`
				: `${g.group_name} — ${__("no T")}`,
		]);
		const depts = (departments || []).map((x) => [x.name, x.department_name || x.name]);
		const check = (name, label, value) =>
			`<label class="tc-ksnk-inline"><input type="checkbox" data-field="${name}"${
				Number(value) ? " checked" : ""
			}> ${esc(label)}</label>`;
		const code = d
			? `<input class="form-control tc-ksnk-code" type="text" data-field="patient_code" value="" placeholder="${esc(
					v.patient_code_masked || ""
			  )}" autocomplete="off" aria-label="${esc(
					__("New patient code (leave empty to keep)")
			  )}">`
			: input("patient_code", "text", "", ' autocomplete="off" aria-required="true"');
		const nnis =
			v.nnis_index === "" || v.nnis_index === null || v.nnis_index === undefined
				? `<span>${esc(
						d ? v.nnis_note || __("Not calculated") : __("Calculated when saved")
				  )}</span>`
				: `<b>${esc(v.nnis_index)}</b> <small>${esc(v.nnis_note || "")}</small>`;
		const window = d
			? `<b>${esc(self.date(v.window_end))}</b> <small>${esc(
					__("({0} days)", [v.window_days])
			  )}</small>`
			: `<span>${esc(__("Calculated when saved"))}</span>`;
		const timing = d
			? `${esc(
					v.prophylaxis_minutes_before_incision === null ||
						v.prophylaxis_minutes_before_incision === undefined ||
						v.prophylaxis_minutes_before_incision === ""
						? "—"
						: __("{0} min before incision", [v.prophylaxis_minutes_before_incision])
			  )} ${self.timingBadge(v.prophylaxis_timing, esc)}`
			: `<span>${esc(
					data.threshold === null || data.threshold === undefined
						? __("No on-time threshold set")
						: __("On time: 0 to {0} min before incision", [data.threshold])
			  )}</span>`;
		const locked = d && d.period_locked;
		return (
			`<section class="tc-ksnk-card" data-region="form"><h3>${esc(
				__("Register surgery under surveillance")
			)} ${
				d
					? `<span class="tc-ksnk-code">${esc(d.name)}</span> ${self.outcomeBadge(
							d.outcome,
							esc
					  )}`
					: ""
			}</h3>` +
			(locked
				? `<div class="tc-ksnk-alert is-info">${esc(
						__(
							"The reporting period of this surgery is locked: only discharge and follow-ups can change."
						)
				  )}</div>`
				: "") +
			(d && !d.data_complete
				? `<div class="tc-ksnk-alert is-warn">${esc(
						__(
							"Imported without ASA, wound class or duration: complete them to calculate the NNIS index."
						)
				  )}</div>`
				: "") +
			`<div class="tc-ksnk-form4">` +
			self.field(__("Patient Code"), code, esc, !d) +
			self.field(
				__("Birth Year"),
				input("birth_year", "number", v.birth_year || "", ' min="1900"'),
				esc
			) +
			self.field(
				__("Sex"),
				select(
					"sex",
					[
						["Male", __("Male")],
						["Female", __("Female")],
						["Other", __("Other")],
					],
					v.sex
				),
				esc
			) +
			self.field(
				__("Department"),
				select("department", depts, v.department, true),
				esc,
				true
			) +
			self.field(
				__("Procedure Group"),
				select("procedure_group", groups, v.procedure_group, true),
				esc,
				true
			) +
			self.field(
				__("Surgery Date"),
				input("surgery_date", "date", v.surgery_date || ""),
				esc,
				true
			) +
			self.field(
				__("ASA Score"),
				select(
					"asa_score",
					[1, 2, 3, 4, 5].map((n) => [n, String(n)]),
					v.asa_score || "",
					true
				),
				esc,
				true
			) +
			self.field(
				__("Wound Class"),
				select(
					"wound_class",
					TC_SSI_WOUNDS.map((w) => [w, __(w, null, TC_SSI_CTX)]),
					v.wound_class,
					true
				),
				esc,
				true
			) +
			self.field(
				__("Duration (minutes)"),
				input("duration_min", "number", v.duration_min || "", ' min="1"'),
				esc,
				true
			) +
			check("has_implant", __("Implant"), v.has_implant) +
			check("prophylaxis_given", __("Prophylaxis Given"), d ? v.prophylaxis_given : 1) +
			self.field(
				__("Antibiotic"),
				input("prophylaxis_agent", "text", v.prophylaxis_agent || ""),
				esc
			) +
			self.field(
				__("Minutes before Incision"),
				input(
					"prophylaxis_minutes_before_incision",
					"number",
					v.prophylaxis_minutes_before_incision ?? ""
				),
				esc
			) +
			self.field(
				__("Discharge Date"),
				input("discharge_date", "date", v.discharge_date || ""),
				esc
			) +
			`</div><div class="tc-ksnk-form4 tc-ksnk-computed">` +
			`<div><span>${esc(__("NNIS index (calculated)"))}</span><div>${nnis}</div></div>` +
			`<div><span>${esc(__("Surveillance window end"))}</span><div>${window}</div></div>` +
			`<div><span>${esc(__("Prophylaxis timing"))}</span><div>${timing}</div></div>` +
			`</div><div data-region="form-alert"></div></section>`
		);
	},

	followupsHtml(d, data, esc) {
		const self = TcKsnkScr57;
		const today = self.today();
		if (!d)
			return `<section class="tc-ksnk-card"><h3>${esc(
				__("Follow-ups due")
			)}</h3>${self.dueHtml(data.due || [], esc)}</section>`;
		const rows = d.followups || [];
		const body = rows.length
			? `<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Due Date"))}</th><th>${esc(
					__("Method")
			  )}</th><th>${esc(__("Done On"))}</th><th>${esc(
					__("Result")
			  )}</th><th></th></tr></thead><tbody>${rows
					.map(
						(r) =>
							`<tr><td>${esc(self.date(r.due_date))}${
								r.is_final ? ` <small>${esc(__("(last)"))}</small>` : ""
							}</td><td>${esc(__(r.method, null, TC_SSI_CTX))}</td><td>${esc(
								self.date(r.done_on)
							)}</td><td>${self.followupBadge(r, esc, today)}</td><td>${
								r.done_on
									? ""
									: `<button type="button" class="btn btn-default btn-sm" data-action="record" data-row="${esc(
											r.name
									  )}">${esc(__("Record result"))}</button>`
							}</td></tr>`
					)
					.join("")}</tbody></table>`
			: `<p class="tc-ksnk-state">${esc(
					d.discharge_date
						? __(
								"Discharged after the window end: follow up as an inpatient, then close the surgery."
						  )
						: __("The schedule is created when the discharge date is entered.")
			  )}</p>`;
		const suspected = rows.some((r) => r.result === "SSI suspected");
		const caseLine = d.hai_case
			? `<div class="tc-ksnk-alert is-info">${esc(
					__("{0}: HAI case", [d.name])
			  )} <span class="tc-ksnk-code">${esc(d.hai_case)}</span> ${esc(
					d.case_status ? __(d.case_status.status) : ""
			  )} ${TcKsnk.recordActions(
					{
						doctype: "HAI Case",
						name: d.hai_case,
						docstatus: d.case_status ? d.case_status.docstatus : undefined,
						can_write: false,
						can_create: false,
						can_print: false,
					},
					false
			  )}</div>`
			: "";
		const actions = [];
		if (suspected && !d.hai_case && (data.definitions || []).length)
			actions.push(
				`<button type="button" class="btn btn-primary" data-action="case">${esc(
					__("Create HAI case")
				)}</button>`
			);
		if (d.window_over && !rows.length && d.outcome === "Under Surveillance")
			actions.push(
				`<button type="button" class="btn btn-default" data-action="close-nossi">${esc(
					__("Close: No SSI")
				)}</button>`,
				`<button type="button" class="btn btn-default" data-action="close-lost">${esc(
					__("Close: Lost to Follow-up")
				)}</button>`
			);
		return (
			`<section class="tc-ksnk-card" data-region="followups"><h3>${esc(
				__("Follow-up after discharge")
			)} <span class="tc-ksnk-tag">SSI Follow-up</span></h3>${body}${caseLine}` +
			(actions.length ? `<div class="tc-ksnk-actions">${actions.join("")}</div>` : "") +
			`<div data-region="followup-alert"></div></section>`
		);
	},

	dueHtml(rows, esc) {
		const self = TcKsnkScr57;
		if (!rows.length)
			return `<p class="tc-ksnk-state">${esc(__("No follow-up due today."))}</p>`;
		return `<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Surgery"))}</th><th>${esc(
			__("Patient Code")
		)}</th><th>${esc(__("Procedure Group"))}</th><th>${esc(__("Due Date"))}</th><th>${esc(
			__("Method")
		)}</th></tr></thead><tbody>${rows
			.map(
				(r) =>
					`<tr class="tc-ksnk-row" data-open="${esc(
						r.name
					)}"><td class="tc-ksnk-code">${esc(r.name)}</td><td class="tc-ksnk-code">${esc(
						r.patient_code_masked
					)}</td><td>${esc(r.group_name || r.procedure_group)}</td><td>${esc(
						self.date(r.due_date)
					)}</td><td>${esc(__(r.method, null, TC_SSI_CTX))}</td></tr>`
			)
			.join("")}</tbody></table>`;
	},

	recentHtml(rows, selected, esc) {
		const self = TcKsnkScr57;
		const body = rows.length
			? `<table class="tc-ksnk-table"><thead><tr><th>${esc(__("Surgery"))}</th><th>${esc(
					__("Procedure Group")
			  )}</th><th class="is-num">NNIS</th><th>${esc(__("Prophylaxis"))}</th><th>${esc(
					__("Outcome")
			  )}</th></tr></thead><tbody>${rows
					.map(
						(r) =>
							`<tr class="tc-ksnk-row${
								r.name === selected ? " is-selected" : ""
							}" data-open="${esc(r.name)}"><td class="tc-ksnk-code">${esc(
								r.name
							)}</td><td>${esc(
								r.group_name || r.procedure_group
							)}</td><td class="is-num">${esc(
								r.nnis_index === "" || r.nnis_index === null ? "—" : r.nnis_index
							)}</td><td>${self.timingBadge(
								r.prophylaxis_timing,
								esc
							)}</td><td>${self.outcomeBadge(r.outcome, esc)}</td></tr>`
					)
					.join("")}</tbody></table>`
			: `<p class="tc-ksnk-state">${esc(__("No surgery under surveillance yet."))}</p>`;
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Recent surgeries")
		)}</h3>${body}</section>`;
	},

	recordActionsHtml(d, data) {
		// Ca đang chọn: xem/sửa chi tiết trên form Desk (ADR-002) và In; quyền thật kiểm ở DocPerm.
		if (!d || !d.name) return "";
		return (
			TcKsnk.recordActions(
				{
					doctype: "Surgical Surveillance",
					name: d.name,
					docstatus: d.docstatus === undefined ? 0 : d.docstatus,
					can_write: !!(data && data.can_write),
					can_create: false,
				},
				false
			) + " "
		);
	},

	actionsHtml(d, esc, data) {
		return (
			`<div class="tc-ksnk-actions">` +
			TcKsnkScr57.recordActionsHtml(d, data) +
			`<button type="button" class="btn btn-primary btn-lg" data-action="save">${esc(
				__("Save surgery")
			)}</button>` +
			(d
				? `<button type="button" class="btn btn-default" data-action="new">${esc(
						__("New surgery")
				  )}</button>`
				: "") +
			`<button type="button" class="btn btn-default" data-action="import">${esc(
				__("Import surgery list (file)")
			)}</button>` +
			`<button type="button" class="btn btn-default" data-action="export">${esc(
				__("Export SSI report")
			)}</button>` +
			`<span class="tc-ksnk-note">${esc(
				__(
					"Surgery lists from HIS come in only as files through an Import Mapping Profile (D3)."
				)
			)}</span></div>`
		);
	},

	pageHtml(data, departments, esc) {
		const self = TcKsnkScr57;
		const d = data.detail || null;
		return (
			self.kpisHtml(data.kpis || {}, esc) +
			self.formHtml(data, d, departments, esc) +
			`<div class="tc-ksnk-cols"><div>${self.followupsHtml(
				d,
				data,
				esc
			)}</div><div>${self.recentHtml(data.recent || [], d && d.name, esc)}</div></div>` +
			self.actionsHtml(d, esc, data)
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

	values(el) {
		const out = {};
		el.querySelectorAll('[data-region="form"] [data-field]').forEach((input) => {
			const key = input.dataset.field;
			if (input.type === "checkbox") out[key] = input.checked ? 1 : 0;
			else out[key] = input.value.trim() === "" ? null : input.value.trim();
		});
		return out;
	},

	call(method, args, region, esc, onOk, button) {
		if (button) button.disabled = true;
		tracecore.desk_call({
			method: TC_SSI + method,
			args,
			// create_case tự báo "ca NKBV … đã tạo"; thao tác khác dùng thông báo chung của trang
			success: method === "create_case" ? false : undefined,
			on_ok: (result) => {
				if (button) button.disabled = false;
				onOk(result);
			},
			on_block: (error) => {
				if (button) button.disabled = false;
				if (region) region.innerHTML = TcKsnkScr57.blockHtml(error, esc);
			},
			on_fail: () => {
				if (button) button.disabled = false;
			},
		});
	},

	recordDialog(row, done) {
		const dialog = new frappe.ui.Dialog({
			title: __("Record follow-up result"),
			fields: [
				{
					fieldname: "done_on",
					fieldtype: "Date",
					label: __("Done On"),
					reqd: 1,
					default: frappe.datetime.get_today(),
				},
				{
					fieldname: "result",
					fieldtype: "Select",
					label: __("Result"),
					reqd: 1,
					options: ["", ...TC_SSI_RESULTS].map((value) => ({
						value,
						label: value ? __(value, null, TC_SSI_CTX) : "",
					})),
				},
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
			],
			primary_action_label: __("Save"),
			primary_action: (values) => {
				dialog.hide();
				done(values);
			},
		});
		dialog.show();
	},

	caseDialog(data, done) {
		const dialog = new frappe.ui.Dialog({
			title: __("Create HAI case"),
			fields: [
				{
					fieldname: "def_code",
					fieldtype: "Select",
					label: __("Case Definition"),
					reqd: 1,
					options: (data.definitions || []).map((row) => ({
						value: row.def_code,
						label: `${row.def_code} — ${row.title}`,
					})),
				},
				{ fieldname: "onset_date", fieldtype: "Date", label: __("Onset Date"), reqd: 1 },
			],
			primary_action_label: __("Create"),
			primary_action: (values) => {
				dialog.hide();
				done(values);
			},
		});
		dialog.show();
	},

	bind(el, ctx, data) {
		const self = TcKsnkScr57;
		const d = data.detail;
		const formAlert = el.querySelector('[data-region="form-alert"]');
		const followAlert = el.querySelector('[data-region="followup-alert"]');
		const reload = (name) => {
			self.selected = name || null;
			self.render(el, ctx);
		};
		el.querySelectorAll("[data-open]").forEach((row) =>
			row.addEventListener("click", () => reload(row.dataset.open))
		);
		el.querySelectorAll("[data-action]").forEach((button) => {
			button.addEventListener("click", () => {
				const action = button.dataset.action;
				if (action === "save") {
					self.call(
						"save",
						{ values: JSON.stringify(self.values(el)), name: d ? d.name : null },
						formAlert,
						ctx.esc,
						(result) => reload(result.detail.name),
						button
					);
				} else if (action === "new") reload(null);
				else if (action === "import") frappe.set_route("tc-import");
				else if (action === "export") frappe.set_route("tc-ksnk", "bao-cao-nkbv");
				else if (action === "record")
					self.recordDialog(button.dataset.row, (values) =>
						self.call(
							"record_followup",
							{ name: d.name, row: button.dataset.row, ...values },
							followAlert,
							ctx.esc,
							() => reload(d.name),
							button
						)
					);
				else if (action === "case")
					self.caseDialog(data, (values) =>
						self.call(
							"create_case",
							{ name: d.name, ...values },
							followAlert,
							ctx.esc,
							(result) => {
								frappe.show_alert({
									message: __("HAI case {0} created", [result.case]),
									indicator: "green",
								});
								reload(d.name);
							},
							button
						)
					);
				else if (action === "close-nossi" || action === "close-lost")
					self.call(
						"close",
						{
							name: d.name,
							outcome: action === "close-nossi" ? "No SSI" : "Lost to Follow-up",
						},
						followAlert,
						ctx.esc,
						() => reload(d.name),
						button
					);
			});
		});
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_SSI + "screen", { name: TcKsnkScr57.selected || "" });
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr57.pageHtml(data, ctx.departments, ctx.esc);
			TcKsnkScr57.bind(el, ctx, data);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
		}
	},
};

window.TcKsnkScreens.nkvm = TcKsnkScr57;
window.TcKsnkScr57 = TcKsnkScr57;
