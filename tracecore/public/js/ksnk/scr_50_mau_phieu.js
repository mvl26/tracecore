/* global tracecore, TcKsnk */
// SCR-50 Mẫu phiếu giám sát & lịch giám sát (FEAT-060; UC-43; FR-M12-01, FR-M12-03; BRU-AUD-001; ADR-015; A-131, A-134).
// Trái: danh sách phiên bản mẫu với trạng thái bằng chữ (Nháp / Đã duyệt / Chờ hiệu lực / Hết hiệu lực). Phải: mẫu đang chọn;
// bản Nháp sửa được (mục, trọng số, trọng yếu), bản đã duyệt bị khóa và chỉ "Tạo phiên bản mới". Dưới: lịch giám sát kỳ hiện tại
// với độ bao phủ bằng số. Ghi qua RPC tracecore.v1.audit.*; lỗi hiện alert-error inline (kết quả → lý do → hành động).

const TC_AUD_TEMPLATES = "tracecore.v1.audit.template_board";
const TC_AUD_SAVE = "tracecore.v1.audit.save_template";
const TC_AUD_APPROVE = "tracecore.v1.audit.approve_template";
const TC_AUD_REVISE = "tracecore.v1.audit.new_version";
const TC_AUD_SCHEDULES = "tracecore.v1.audit.schedule_board";
const TC_AUD_SAVE_SCHEDULE = "tracecore.v1.audit.save_schedule";
const TC_AUD_ITEM_FIELDS = [
	"item_code",
	"section",
	"question",
	"answer_type",
	"weight",
	"is_critical",
];

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr50 = {
	statusBadge(status) {
		if (status === "Approved") return { cls: "is-pass", label: __("Approved") };
		if (status === "Draft") return { cls: "is-neutral", label: __("Draft") };
		if (status === "Scheduled") return { cls: "is-info", label: __("Not yet effective") };
		if (status === "Superseded") return { cls: "is-neutral", label: __("Superseded") };
		return { cls: "", label: status ? __(status) : "—" };
	},

	coverageText(row) {
		return __("{0} % ({1})", [
			row.coverage_pct,
			(row.coverage || []).map((cell) => cell.label).join(" · "),
		]);
	},

	call(method, args) {
		return new Promise((resolve) => {
			tracecore.desk_call({
				method,
				args,
				on_ok: (result) => resolve(result),
				on_block: (error) => resolve({ ok: false, error }),
				on_fail: () =>
					resolve({
						ok: false,
						error: {
							title: __("Not saved"),
							reason: __("The server did not accept the request."),
							action: __("Retry, or call R10 if it happens again."),
						},
					}),
			});
		});
	},

	alertHtml(error, esc) {
		if (!error) return "";
		return (
			`<div class="tc-ksnk-alert is-error" role="alert"><b>${esc(error.title || "")}</b> ` +
			`${esc(error.reason || "")} ${esc(error.action || "")}</div>`
		);
	},

	listHtml(data, selected, esc) {
		const rows = (data.templates || [])
			.map((row) => {
				const badge = TcKsnkScr50.statusBadge(row.status);
				const on = selected && selected.name === row.name;
				return (
					`<tr class="tc-ksnk-row${on ? " is-selected" : ""}" data-template="${esc(
						row.name
					)}" tabindex="0">` +
					`<td>${esc(row.title)}<br><code class="tc-ksnk-code">MP-${esc(
						row.template_code
					)}</code></td>` +
					`<td>V${esc(row.version_no)}</td>` +
					`<td><span class="tc-ksnk-badge ${badge.cls}">${esc(
						badge.label
					)}</span></td></tr>`
				);
			})
			.join("");
		return (
			`<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(__("Template"))}</th>` +
			`<th scope="col">${esc(__("Version"))}</th><th scope="col">${esc(
				__("Status")
			)}</th></tr></thead>` +
			`<tbody>${rows}</tbody></table>`
		);
	},

	selectHtml(field, options, value, esc, disabled) {
		const opts = options
			.map(
				(opt) =>
					`<option value="${esc(opt)}"${opt === value ? " selected" : ""}>${esc(
						__(opt)
					)}</option>`
			)
			.join("");
		return `<select class="form-control" data-field="${field}"${
			disabled ? " disabled" : ""
		}>${opts}</select>`;
	},

	detailHtml(detail, options, esc) {
		const self = TcKsnkScr50;
		if (!detail)
			return `<div class="tc-ksnk-state is-empty">${esc(__("No template yet."))}</div>`;
		const off = !detail.can_edit;
		const input = (field, label, type = "text") =>
			`<label>${esc(
				label
			)}<input class="form-control" type="${type}" data-field="${field}" value="${esc(
				detail[field] === null || detail[field] === undefined ? "" : detail[field]
			)}"${off || (field === "template_code" && detail.name) ? " disabled" : ""}></label>`;
		const badge = self.statusBadge(detail.status);
		const locked = off
			? `<div class="tc-ksnk-alert is-info" role="status">${esc(
					__(
						"Version {0} is approved and locked; any change needs a new version. Audits already filled keep their copy of {0}.",
						[detail.name || ""]
					)
			  )}</div>`
			: "";
		const items = (detail.items || [])
			.map((item, index) => {
				const cell = (field, type = "text") =>
					`<input class="form-control" type="${type}" data-item="${index}" data-item-field="${field}" value="${esc(
						item[field] === null || item[field] === undefined ? "" : item[field]
					)}"${off ? " disabled" : ""}>`;
				const answer = off
					? esc(__(item.answer_type))
					: `<select class="form-control" data-item="${index}" data-item-field="answer_type">${(
							options.answer_types || []
					  )
							.map(
								(opt) =>
									`<option value="${esc(opt)}"${
										opt === item.answer_type ? " selected" : ""
									}>${esc(__(opt))}</option>`
							)
							.join("")}</select>`;
				const critical = `<label><input type="checkbox" data-item="${index}" data-item-field="is_critical"${
					item.is_critical ? " checked" : ""
				}${off ? " disabled" : ""}> ${esc(
					item.is_critical ? __("Yes") : __("No")
				)}</label>`;
				return (
					`<tr><td>${
						off
							? `<code class="tc-ksnk-code">${esc(item.item_code)}</code>`
							: cell("item_code")
					}</td>` +
					`<td>${off ? esc(item.section || "") : cell("section")}</td>` +
					`<td>${off ? esc(item.question) : cell("question")}</td><td>${answer}</td>` +
					`<td class="is-num">${
						off ? esc(item.weight) : cell("weight", "number")
					}</td><td>${critical}</td>` +
					`<td>${
						off
							? ""
							: `<button type="button" class="btn btn-default btn-sm" data-action="remove-item" data-item="${index}">${esc(
									__("Remove")
							  )}</button>`
					}</td></tr>`
				);
			})
			.join("");
		return (
			`<div class="tc-ksnk-head"><h3>${esc(detail.title || __("New template"))}</h3>` +
			(detail.name ? `<code class="tc-ksnk-tag">${esc(detail.name)}</code>` : "") +
			` <span class="tc-ksnk-badge ${badge.cls}">${esc(badge.label)}</span></div>${locked}` +
			`<div class="tc-ksnk-filters">` +
			input("template_code", __("Template Code")) +
			input("title", __("Title")) +
			`<label>${esc(__("Audit Type"))}${self.selectHtml(
				"audit_type",
				options.audit_types || [],
				detail.audit_type,
				esc,
				off
			)}</label>` +
			`<label>${esc(__("Scoring Method"))}${self.selectHtml(
				"scoring_method",
				options.scoring_methods || [],
				detail.scoring_method,
				esc,
				off
			)}</label>` +
			input("min_sample", __("Minimum sample per department and month"), "number") +
			input("effective_from", __("Effective From"), "date") +
			input("pass_threshold", __("Pass Threshold"), "number") +
			input("legal_ref", __("Legal Reference")) +
			`</div><table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
				__("Code")
			)}</th>` +
			`<th scope="col">${esc(__("Section"))}</th><th scope="col">${esc(
				__("Question")
			)}</th>` +
			`<th scope="col">${esc(__("Answer Type"))}</th><th scope="col" class="is-num">${esc(
				__("Weight", null, "Audit Template Item")
			)}</th>` +
			`<th scope="col">${esc(
				__("Critical")
			)}</th><th scope="col"></th></tr></thead><tbody>${items}</tbody></table>` +
			(off
				? ""
				: `<button type="button" class="btn btn-default btn-sm" data-action="add-item">${esc(
						__("+ Add item")
				  )}</button>`)
		);
	},

	schedulesHtml(data, esc) {
		const rows = (data.schedules || [])
			.map(
				(row) =>
					`<tr><td><code class="tc-ksnk-code">${esc(row.name)}</code></td><td>${esc(
						row.template_title || row.template_code
					)}</td>` +
					`<td>${esc(
						(row.coverage || []).map((cell) => cell.department).join(", ")
					)}</td>` +
					`<td>${esc(__(row.frequency))}</td><td class="is-num">${esc(
						row.target_count
					)}</td>` +
					`<td>${esc(row.assignee_name || row.assignee)}</td>` +
					`<td><span class="tc-ksnk-progress" role="progressbar" aria-valuenow="${esc(
						row.coverage_pct || 0
					)}" aria-valuemin="0" aria-valuemax="100"><span style="width: ${esc(
						Math.min(100, Number(row.coverage_pct) || 0)
					)}%"></span></span> ${esc(TcKsnkScr50.coverageText(row))}</td></tr>`
			)
			.join("");
		if (!rows)
			return `<div class="tc-ksnk-state is-empty">${esc(
				__("No active audit schedule.")
			)}</div>`;
		return (
			`<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(__("Code"))}</th>` +
			`<th scope="col">${esc(__("Template"))}</th><th scope="col">${esc(
				__("Departments")
			)}</th>` +
			`<th scope="col">${esc(__("Frequency"))}</th><th scope="col" class="is-num">${esc(
				__("Target")
			)}</th>` +
			`<th scope="col">${esc(__("Assignee"))}</th><th scope="col">${esc(
				__("Coverage")
			)}</th></tr></thead>` +
			`<tbody>${rows}</tbody></table>`
		);
	},

	scheduleFormHtml(templates, departments, esc) {
		const approved = templates.filter((row) => row.status === "Approved");
		return (
			`<section class="tc-ksnk-card" data-region="schedule-form"><h3>${esc(
				__("New audit schedule")
			)}</h3>` +
			`<div class="tc-ksnk-filters"><label>${esc(
				__("Template")
			)}<select class="form-control" data-schedule="audit_template">` +
			approved
				.map(
					(row) =>
						`<option value="${esc(row.name)}">${esc(row.title)} (${esc(
							row.name
						)})</option>`
				)
				.join("") +
			`</select></label><label>${esc(
				__("Frequency")
			)}<select class="form-control" data-schedule="frequency">` +
			["Weekly", "Monthly", "Quarterly"]
				.map(
					(f) =>
						`<option value="${f}"${f === "Monthly" ? " selected" : ""}>${esc(
							__(f)
						)}</option>`
				)
				.join("") +
			`</select></label><label>${esc(
				__("Target per Department")
			)}<input class="form-control" type="number" min="1" data-schedule="target_count" value="30"></label>` +
			`<label>${esc(
				__("Assignee")
			)}<input class="form-control" data-schedule="assignee" placeholder="${esc(
				__("Employee ID", null, "Audit Schedule")
			)}"></label></div>` +
			`<fieldset class="tc-ksnk-checks"><legend>${esc(__("Departments"))}</legend>` +
			departments
				.map(
					(d) =>
						`<label><input type="checkbox" data-schedule-dept="${esc(d.name)}"> ${esc(
							d.department_name || d.name
						)}</label>`
				)
				.join("") +
			`</fieldset><button type="button" class="btn btn-primary btn-sm" data-action="save-schedule">${esc(
				__("Save schedule")
			)}</button></section>`
		);
	},

	actionsHtml(detail, data, schedules, esc, readOnly) {
		const buttons = [];
		if (detail && detail.name)
			buttons.push(
				TcKsnk.recordActions(
					{
						doctype: "Audit Template",
						name: detail.name,
						docstatus: detail.docstatus,
						can_write: !readOnly && !!detail.can_write,
					},
					false
				)
			);
		if (readOnly) {
			return buttons.length ? `<div class="tc-ksnk-actions">${buttons.join("")}</div>` : "";
		}
		if (detail && detail.can_approve)
			buttons.push(
				`<button type="button" class="btn btn-primary" data-action="approve">${esc(
					__("Approve template {0} (post)", [detail.name])
				)}</button>`
			);
		if (detail && detail.can_edit)
			buttons.push(
				`<button type="button" class="btn btn-default" data-action="save">${esc(
					__("Save draft")
				)}</button>`
			);
		if (detail && detail.can_revise)
			buttons.push(
				`<button type="button" class="btn btn-default" data-action="revise">${esc(
					__("Create version V{0}", [(detail.version_no || 0) + 1])
				)}</button>`
			);
		if (data.can_create)
			buttons.push(
				`<button type="button" class="btn btn-default" data-action="new">${esc(
					__("New template")
				)}</button>`
			);
		if (schedules.can_create)
			buttons.push(
				`<button type="button" class="btn btn-default" data-action="schedule">${esc(
					__("Create audit schedule")
				)}</button>`
			);
		if (!buttons.length) return "";
		return `<div class="tc-ksnk-actions">${buttons.join("")}<span class="tc-ksnk-note">${esc(
			__("Only R01 approves templates; a failed critical item fails the audit.")
		)}</span></div>`;
	},

	collect(el, detail) {
		const values = { name: detail.name || undefined };
		el.querySelectorAll("[data-field]").forEach((input) => {
			values[input.dataset.field] = input.value;
		});
		values.items = (detail.items || []).map((item, index) => {
			const row = { ...item };
			TC_AUD_ITEM_FIELDS.forEach((field) => {
				const input = el.querySelector(
					`[data-item="${index}"][data-item-field="${field}"]`
				);
				if (!input) return;
				row[field] = input.type === "checkbox" ? (input.checked ? 1 : 0) : input.value;
			});
			return row;
		});
		return values;
	},

	async render(el, ctx, state = {}) {
		const self = TcKsnkScr50;
		const esc = ctx.esc;
		el.innerHTML = ctx.state("loading");
		let data;
		let schedules;
		try {
			[data, schedules] = await Promise.all([
				ctx.get(TC_AUD_TEMPLATES, { template: state.template || undefined }),
				ctx.get(TC_AUD_SCHEDULES, {}),
			]);
		} catch (error) {
			if (ctx.isCurrent()) el.innerHTML = ctx.state("error", (error && error.message) || "");
			return;
		}
		if (!ctx.isCurrent()) return;
		const detail = state.draft || data.selected;
		const period = ((schedules.schedules || [])[0] || {}).period || "";
		el.innerHTML =
			self.alertHtml(state.error, esc) +
			`<div class="tc-ksnk-grid">` +
			`<section class="tc-ksnk-card" data-region="list"><h3>${esc(
				__("Templates", null, "Audit Template")
			)} <code class="tc-ksnk-tag">Audit Template</code></h3>` +
			`${
				(data.templates || []).length
					? self.listHtml(data, detail, esc)
					: ctx.state("empty", __("No template yet."))
			}` +
			`<p class="tc-ksnk-note">${esc(
				__(
					"Starter templates come with the app as drafts; app upgrades never overwrite templates edited by the hospital."
				)
			)}</p></section>` +
			`<section class="tc-ksnk-card" data-region="detail">${self.detailHtml(
				detail,
				data.options || {},
				esc
			)}</section>` +
			`</div>` +
			(state.scheduleForm
				? self.scheduleFormHtml(data.templates || [], ctx.departments || [], esc)
				: "") +
			`<section class="tc-ksnk-card"><h3>${esc(
				__("Audit schedule for period {0}", [period])
			)} ` +
			`<code class="tc-ksnk-tag">Audit Schedule · LGS-</code></h3>${self.schedulesHtml(
				schedules,
				esc
			)}</section>` +
			self.actionsHtml(detail, data, schedules, esc, ctx.readOnly);

		const rerender = (next) => self.render(el, ctx, next);
		const result = async (promise, next) => {
			const res = await promise;
			if (!ctx.isCurrent()) return;
			if (res && res.ok === false) rerender({ ...state, ...next.keep, error: res.error });
			else rerender({ template: (res && res.name) || next.template });
		};
		// một handler cho cả màn (gán lại mỗi lần vẽ, không cộng dồn listener)
		el.onclick = (event) => {
			const row = event.target.closest("[data-template]");
			if (row) return rerender({ template: row.dataset.template });
			const button = event.target.closest("[data-action]");
			if (!button) return;
			const action = button.dataset.action;
			if (action === "retry") return rerender(state);
			if (action === "add-item" || action === "remove-item") {
				const draft = self.collect(el, detail);
				if (action === "add-item")
					draft.items.push({
						item_code: "",
						question: "",
						answer_type: "Pass/Fail",
						weight: 1,
						is_critical: 0,
					});
				else draft.items.splice(Number(button.dataset.item), 1);
				return rerender({ template: detail.name, draft: { ...detail, ...draft } });
			}
			if (action === "save") {
				const values = self.collect(el, detail);
				return result(self.call(TC_AUD_SAVE, { values: JSON.stringify(values) }), {
					keep: { draft: { ...detail, ...values } },
				});
			}
			if (action === "approve")
				return result(self.call(TC_AUD_APPROVE, { template: detail.name }), {
					template: detail.name,
				});
			if (action === "revise")
				return result(self.call(TC_AUD_REVISE, { template: detail.name }), {
					template: detail.name,
				});
			if (action === "new")
				return rerender({
					draft: {
						title: "",
						template_code: "",
						audit_type: "Standard Precautions - PPE",
						scoring_method: "Weighted Score",
						min_sample: 0,
						items: [],
						status: "Draft",
						can_edit: true,
					},
				});
			if (action === "schedule") return rerender({ ...state, scheduleForm: true });
			if (action === "save-schedule") {
				const form = el.querySelector('[data-region="schedule-form"]');
				const values = { departments: [] };
				form.querySelectorAll("[data-schedule]").forEach((input) => {
					values[input.dataset.schedule] = input.value;
				});
				form.querySelectorAll("[data-schedule-dept]").forEach((box) => {
					if (box.checked)
						values.departments.push({ department: box.dataset.scheduleDept });
				});
				return result(
					self.call(TC_AUD_SAVE_SCHEDULE, { values: JSON.stringify(values) }),
					{
						keep: { scheduleForm: true },
					}
				);
			}
		};
	},
};

window.TcKsnkScreens["mau-phieu"] = TcKsnkScr50;
window.TcKsnkScr50 = TcKsnkScr50;
