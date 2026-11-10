/* global tracecore */
// SCR-47 Cơ cấu KSNK của bệnh viện (FEAT-057; UC-40; FR-M11-01..03; BRU-ICP-001..003; A-131).
// Cài đặt chương trình (R10/R01), bảng trạng thái cơ cấu bắt buộc, Hội đồng hiệu lực, mạng lưới theo khoa.
// Trạng thái luôn có chữ (server đã dịch: Đủ / Thiếu … / Không áp dụng / Không bắt buộc), không chỉ màu.
// Lỗi chặn hiện alert-error inline theo thứ tự kết quả → lý do → hành động (design.md §6).
// FEAT-094 (A-138): cột Lý do từng người chưa đạt, trạng thái chữ "Chưa xác minh", thông báo "Chưa duyệt bộ tiêu chí
// cơ cấu" kèm lối mở bộ tiêu chí, ô người đứng đầu cơ sở và cách làm tròn số giám sát viên.

const TC_STRUCT_STATUS = "tracecore.v1.ksnk_structure.status";
const TC_STRUCT_SAVE = "tracecore.v1.ksnk_structure.save_settings";
const TC_STRUCT_SUBMIT = "tracecore.v1.ksnk_structure.submit_committee";
const TC_FACILITY_LEVELS = ["Specialized Level", "Basic Level", "Primary Level"];
const TC_ROUNDING = ["Up", "Down"]; // FEAT-094

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr47 = {
	badge(status, label) {
		const cls =
			{ ok: "is-pass", missing: "is-fail", warning: "is-warn", unverified: "is-warn" }[
				status
			] || "is-neutral";
		return { cls, label: label || "—" };
	},

	badgeHtml(status, label, esc) {
		const b = TcKsnkScr47.badge(status, label);
		return `<span class="tc-ksnk-badge ${b.cls}">${esc(b.label)}</span>`;
	},

	date(value) {
		if (!value) return "…";
		const [y, m, d] = String(value).split("-");
		return `${d}/${m}/${y}`;
	},

	summaryText(data) {
		return data.missing_total
			? __("Missing {0} components", [data.missing_total])
			: __("Required structure complete");
	},

	summaryHtml(data, esc) {
		return `<p class="tc-ksnk-head">${TcKsnkScr47.badgeHtml(
			data.missing_total ? "missing" : "ok",
			TcKsnkScr47.summaryText(data),
			esc
		)}</p>`;
	},

	settingsHtml(data, readOnly, esc) {
		const s = data.settings || {};
		const editable = data.can_edit_settings && !readOnly;
		const dis = editable ? "" : " disabled";
		const levels = TC_FACILITY_LEVELS.map(
			(level) =>
				`<option value="${esc(level)}"${
					level === s.facility_level ? " selected" : ""
				}>${esc(__(level))}</option>`
		).join("");
		const inpatient = [
			[1, __("Yes")],
			[0, __("No")],
		]
			.map(
				([value, label]) =>
					`<option value="${value}"${
						Number(s.has_inpatient) === value ? " selected" : ""
					}>${esc(label)}</option>`
			)
			.join("");
		const rounding = TC_ROUNDING.map(
			(value) =>
				`<option value="${esc(value)}"${
					value === (s.surveillance_rounding || "Up") ? " selected" : ""
				}>${esc(__(value, null, "IC Program Settings"))}</option>`
		).join("");
		const save = editable
			? `<button type="button" class="btn btn-primary" data-action="save-settings">${esc(
					__("Save settings")
			  )}</button>`
			: "";
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Program settings"))} ` +
			`<code class="tc-ksnk-tag">IC Program Settings</code></h3>` +
			`<div class="tc-ksnk-filters">` +
			`<label>${esc(
				__("Planned Beds")
			)} *<input type="number" min="0" class="form-control" ` +
			`data-setting="bed_count" value="${esc(s.bed_count)}"${dis}></label>` +
			`<label>${esc(
				__("Facility Level")
			)} *<select class="form-control" data-setting="facility_level"${dis}>${levels}</select></label>` +
			`<label>${esc(
				__("Has Inpatient Care")
			)}<select class="form-control" data-setting="has_inpatient"${dis}>${inpatient}</select></label>` +
			`<label>${esc(__("Beds per Surveillance Officer"))}<input type="number" min="1" ` +
			`class="form-control" data-setting="surveillance_ratio_beds" value="${esc(
				s.surveillance_ratio_beds
			)}"${dis}></label>` +
			`<label>${esc(
				__("Surveillance Officer Rounding")
			)}<select class="form-control" data-setting="surveillance_rounding"${dis}>${rounding}</select></label>` +
			`<label>${esc(__("Head of Facility"))}<input type="text" class="form-control" ` +
			`data-setting="director" value="${esc(s.director || "")}"${dis}>` +
			`<span class="tc-ksnk-note">${esc(s.director_name || "")}</span></label>` +
			`</div><div data-region="settings-alert"></div>${save}` +
			`<p class="tc-ksnk-note"><a href="/app/ic-program-settings">${esc(
				__(
					"Infection control unit and surveillance staff are edited in the settings form."
				)
			)}</a></p></section>`
		);
	},

	profileHtml(data, esc) {
		const link = data.can_open_profile
			? ` <a href="/app/ic-structure-profile">${esc(__("Open structure criteria"))}</a>`
			: "";
		if (data.profile_notice) {
			return (
				`<div class="tc-ksnk-alert is-warn" role="status"><strong>${esc(
					data.profile_notice
				)}</strong> ` +
				`${esc(
					__(
						"Only counts are checked until R01 reviews and approves the draft criteria (TT 16/2018)."
					)
				)}${link}</div>`
			);
		}
		const p = data.profile;
		if (!p) return "";
		return (
			`<p class="tc-ksnk-note">${esc(__("Structure criteria"))}: ` +
			`<code class="tc-ksnk-code">${esc(p.name)}</code> ${esc(p.profile_name || "")} · ` +
			`${esc(__("Version {0}", [p.version_no]))} · ${esc(__("Effective From"))} ${esc(
				TcKsnkScr47.date(p.effective_from)
			)}${link}</p>`
		);
	},

	componentsHtml(data, esc) {
		const rows = data.components
			.map(
				(c) =>
					`<tr><td>${esc(c.label)}</td><td>${esc(c.requirement)}</td>` +
					`<td>${esc(c.current)}</td><td>${TcKsnkScr47.badgeHtml(
						c.status,
						c.status_label,
						esc
					)}</td><td>${esc(c.reasons || "—")}</td></tr>`
			)
			.join("");
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("Required structure status"))} ` +
			`<code class="tc-ksnk-tag">BRU-ICP-001 · TT 16/2018</code></h3>` +
			`<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
				__("Component", null, "IC Structure")
			)}</th>` +
			`<th scope="col">${esc(__("Requirement"))}</th><th scope="col">${esc(
				__("Current", null, "IC Structure")
			)}</th>` +
			`<th scope="col">${esc(__("Status"))}</th><th scope="col">${esc(
				__("Reason", null, "IC Structure")
			)}</th></tr></thead><tbody>${rows}</tbody></table>` +
			`${TcKsnkScr47.profileHtml(data, esc)}</section>`
		);
	},

	committeeHtml(data, esc) {
		const c = data.committee;
		const head = `<h3>${esc(__("IC Committee"))}${
			c
				? ` <code class="tc-ksnk-tag">${esc(c.name)}</code> ${TcKsnkScr47.badgeHtml(
						"ok",
						__("Submitted", null, "IC Structure"),
						esc
				  )}`
				: ""
		}</h3>`;
		if (!c) {
			return (
				`<section class="tc-ksnk-card">${head}<p class="tc-ksnk-note">${esc(
					__("No committee in force.")
				)} ` +
				`<a href="/app/ic-committee/new">${esc(__("Create committee"))}</a></p></section>`
			);
		}
		const members = c.members
			.map(
				(m) =>
					`<tr><td>${esc(m.employee_name || m.employee)}</td><td>${esc(
						__(m.committee_role)
					)}</td>` + `<td>${esc(__(m.representing))}</td></tr>`
			)
			.join("");
		const problems = (c.problems || []).map((p) => p.text);
		if (!c.problems && c.missing_representatives.length) {
			problems.push(
				__("Missing representative: {0}", [
					c.missing_representatives.map((g) => __(g)).join(", "),
				])
			);
		}
		const warning = problems.length
			? `<div class="tc-ksnk-alert is-warn"><strong>${esc(problems.join(" "))}</strong> ` +
			  `${esc(
					__("The committee is still recorded; the warning is kept in the Audit Log.")
			  )} ` +
			  `<a href="/app/ic-committee/${encodeURIComponent(c.name)}">${esc(
					__("Add member")
			  )}</a></div>`
			: "";
		return (
			`<section class="tc-ksnk-card">${head}` +
			`<p>${esc(__("Decision No."))}: <code class="tc-ksnk-code">${esc(
				c.decision_no
			)}</code> · ` +
			`${esc(__("Validity"))}: ${esc(TcKsnkScr47.date(c.valid_from))} – ${esc(
				TcKsnkScr47.date(c.valid_to)
			)}</p>` +
			`<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(__("Member"))}</th>` +
			`<th scope="col">${esc(__("Committee Role"))}</th><th scope="col">${esc(
				__("Representing")
			)}</th></tr></thead>` +
			`<tbody>${members}</tbody></table>${warning}</section>`
		);
	},

	networkHtml(data, esc) {
		const rows = data.departments
			.map(
				(d) =>
					`<tr><td>${esc(d.department_name)}</td><td class="is-num">${esc(
						d.doctors
					)}</td>` +
					`<td class="is-num">${esc(d.nurses)}</td><td>${TcKsnkScr47.badgeHtml(
						d.status,
						d.status_label,
						esc
					)}</td></tr>`
			)
			.join("");
		const table = rows
			? `<table class="tc-ksnk-table"><thead><tr><th scope="col">${esc(
					__("Department")
			  )}</th>` +
			  `<th scope="col" class="is-num">${esc(__("Doctors"))}</th>` +
			  `<th scope="col" class="is-num">${esc(__("Nurses / midwives / technicians"))}</th>` +
			  `<th scope="col">${esc(
					__("Status")
			  )}</th></tr></thead><tbody>${rows}</tbody></table>`
			: `<p class="tc-ksnk-note">${esc(
					__(
						"No department is marked as requiring a network. Mark clinical and paraclinical departments in the Department form."
					)
			  )}</p>`;
		return (
			`<section class="tc-ksnk-card"><h3>${esc(__("IC network by department"))} ` +
			`<code class="tc-ksnk-tag">BRU-ICP-003</code></h3>${table}` +
			`<div class="tc-ksnk-alert">${esc(
				__(
					"Deactivating the last member of a group puts the department on the missing list and alerts R01."
				)
			)}</div>` +
			`<p class="tc-ksnk-note"><a href="/app/ic-network-member/new">${esc(
				__("Add network member")
			)}</a></p></section>`
		);
	},

	actionsHtml(data, readOnly, esc) {
		const submit =
			!readOnly && data.can_submit_committee && data.draft_committee
				? `<button type="button" class="btn btn-primary" data-action="submit-committee" ` +
				  `data-name="${esc(data.draft_committee)}">${esc(
						__("Submit committee composition")
				  )} <code class="tc-ksnk-code">${esc(data.draft_committee)}</code></button> `
				: "";
		return (
			`<div class="tc-ksnk-filters" data-region="actions">${submit}` +
			`<a class="btn btn-default" href="/app/ic-network-member/view/report">${esc(
				__("Export network list (Excel)")
			)}</a>` +
			`<span class="tc-ksnk-note">${esc(
				__("R01 edits; R13 views; R12 sees only their own department.")
			)}</span></div>` +
			`<div data-region="actions-alert"></div>`
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

	warningsHtml(warnings, esc) {
		return (warnings || [])
			.map((w) => `<div class="tc-ksnk-alert is-warn" role="status">${esc(w)}</div>`)
			.join("");
	},

	pageHtml(data, readOnly, esc) {
		const self = TcKsnkScr47;
		return (
			self.summaryHtml(data, esc) +
			self.settingsHtml(data, readOnly, esc) +
			self.componentsHtml(data, esc) +
			self.committeeHtml(data, esc) +
			self.networkHtml(data, esc) +
			self.actionsHtml(data, readOnly, esc)
		);
	},

	settingsValues(el) {
		const values = {};
		el.querySelectorAll("[data-setting]").forEach((input) => {
			const key = input.dataset.setting;
			const text = ["facility_level", "surveillance_rounding", "director"].includes(key);
			values[key] = text ? input.value.trim() : Number(input.value);
		});
		return values;
	},

	bind(el, ctx, data) {
		const self = TcKsnkScr47;
		const esc = ctx.esc;
		const show = (region, html) => {
			const target = el.querySelector(`[data-region="${region}"]`);
			if (target) target.innerHTML = html;
		};
		el.querySelectorAll("[data-action]").forEach((button) => {
			button.addEventListener("click", () => {
				const action = button.dataset.action;
				if (action === "retry") {
					self.render(el, ctx);
					return;
				}
				button.disabled = true;
				const call =
					action === "save-settings"
						? {
								method: TC_STRUCT_SAVE,
								args: { values: self.settingsValues(el) },
								region: "settings-alert",
						  }
						: {
								method: TC_STRUCT_SUBMIT,
								args: { name: button.dataset.name },
								region: "actions-alert",
						  };
				tracecore.desk_call({
					method: call.method,
					args: call.args,
					on_ok: (result) => {
						if (!ctx.isCurrent()) return;
						self.paint(el, ctx, result.status || data);
						show("actions-alert", self.warningsHtml(result.warnings, esc));
					},
					on_block: (error) => {
						button.disabled = false;
						show(call.region, self.blockHtml(error, esc));
					},
					on_fail: () => {
						button.disabled = false;
					},
				});
			});
		});
	},

	paint(el, ctx, data) {
		el.innerHTML = TcKsnkScr47.pageHtml(data, ctx.readOnly, ctx.esc);
		TcKsnkScr47.bind(el, ctx, data);
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		try {
			const data = await ctx.get(TC_STRUCT_STATUS, {});
			if (!ctx.isCurrent()) return;
			TcKsnkScr47.paint(el, ctx, data);
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
			TcKsnkScr47.bind(el, ctx, null);
		}
	},
};

window.TcKsnkScreens["co-cau"] = TcKsnkScr47;
window.TcKsnkScr47 = TcKsnkScr47;
