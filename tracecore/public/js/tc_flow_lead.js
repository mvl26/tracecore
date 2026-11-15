/* global TcFlow */
// Khu Trưởng khoa KSNK của Page tc-flow (FEAT-102, A-162, FR-M9-33, SCR-73): phần dựng HTML thuần của 7 mục theo
// prototype #17. Chỉ hiển thị số liệu máy chủ trả về (tracecore.v1.lead.*), không tự tính quy tắc nghiệp vụ.
// `h` do Page truyền vào: { esc(value), day(value), time(value), hour(value) }. Test: tracecore/tests/test_tc_flow_page.py.

const TcFlowLead = {
	// mục → RPC đọc và tiêu đề
	PANES: {
		overview: { method: "tracecore.v1.lead.overview", label: "Today's overview" },
		overrides: { method: "tracecore.v1.lead.overrides", label: "Par level overrides" },
		recalls: { method: "tracecore.v1.lead.recalls", label: "Recalls & incidents" },
		costs: { method: "tracecore.v1.lead.costs", label: "Reprocessing cost" },
		equipment: { method: "tracecore.v1.lead.equipment", label: "Equipment & daily tests" },
		staff: { method: "tracecore.v1.lead.staff", label: "Staff & certificates" },
		log: {
			method: "tracecore.v1.lead.sterilization_log",
			label: "Electronic sterilization log",
		},
	},

	label(pane) {
		const entry = TcFlowLead.PANES[pane];
		return entry ? __(entry.label) : "";
	},

	badge(h, text, state) {
		return `<span class="tcf-badge" data-tone="${TcFlow.leadTone(state)}">${h.esc(
			text
		)}</span>`;
	},

	table(h, columns, rows, empty) {
		if (!rows) return `<p class="tcf-empty">${h.esc(empty)}</p>`;
		return `<table class="tcf-table"><thead><tr>${columns
			.map((column) => `<th scope="col">${h.esc(column)}</th>`)
			.join("")}</tr></thead><tbody>${rows}</tbody></table>`;
	},

	card(h, heading, body) {
		return `<section class="tcf-card">${
			heading ? `<h3>${h.esc(heading)}</h3>` : ""
		}${body}</section>`;
	},

	kpi(h, value, text, tone, format) {
		const shown = format === "vnd" ? TcFlow.vnd(value) : value;
		const extra = format ? ` data-format="${format}"` : "";
		return `<div class="tcf-kpi" data-tone="${tone}"><b data-count="${h.esc(
			value
		)}"${extra}>${h.esc(shown)}</b><small>${h.esc(text)}</small></div>`;
	},

	// số việc chờ ở thanh bên, lấy từ Tổng quan hôm nay
	badges(overview) {
		const decisions = (overview && overview.decisions) || {};
		const kpis = (overview && overview.kpis) || {};
		const count = (block) => (block && block.count) || 0;
		return {
			overrides: count(decisions.overrides),
			recalls: count(decisions.recalls) + (kpis.open_nc || 0),
		};
	},

	// ---- 1. Tổng quan hôm nay ----
	decisionsHtml(h, decisions) {
		const line = (tone, text, pane, action) =>
			`<li class="tcf-decision" data-tone="${tone}"><span>${text}</span>${
				pane
					? ` <button type="button" class="tcf-btn" data-action="tcf-lead-pane" data-pane="${pane}">${h.esc(
							action
					  )}</button>`
					: ""
			}</li>`;
		const code = (value) => `<span class="tcf-code">${h.esc(value)}</span>`;
		const items = [];
		for (const row of (decisions.overrides && decisions.overrides.rows) || [])
			items.push(
				line(
					"fail",
					`${h.esc(__("Par level override request for set"))} ${code(
						row.set_unit
					)} — ${h.esc(row.reason || "")}`,
					"overrides",
					__("Review and decide")
				)
			);
		for (const row of (decisions.recalls && decisions.recalls.rows) || [])
			items.push(
				line(
					"fail",
					`${h.esc(__("Recall"))} ${code(row.name)} ${h.esc(
						__("is open: {0}/{1} packs not confirmed", [
							(row.pack_count || 0) - (row.confirmed_count || 0),
							row.pack_count || 0,
						])
					)} — ${h.esc(__(row.trigger || "", null, "Recall"))}`,
					"recalls",
					__("Follow up")
				)
			);
		for (const row of (decisions.equipment && decisions.equipment.rows) || []) {
			const parts = [];
			if (row.status === "Locked" || row.status === "Repair")
				parts.push(
					`${__(row.status, null, "Equipment")}${
						row.lock_reason ? `: ${__(row.lock_reason, null, "Equipment")}` : ""
					}`
				);
			if (row.due_in !== null && row.due_in !== undefined)
				parts.push(
					row.due_in < 0
						? __("inspection or calibration overdue by {0} days", [-row.due_in])
						: __("inspection or calibration due in {0} days", [row.due_in])
				);
			items.push(
				line(
					"warn",
					`${code(row.name)} ${h.esc(row.equipment_name || "")} — ${h.esc(
						parts.join("; ")
					)}`,
					"equipment",
					__("See equipment")
				)
			);
		}
		const certificates = decisions.certificates || {};
		if (certificates.count)
			items.push(
				line(
					"warn",
					h.esc(
						__("{0} certificates expired or expiring within 60 days ({1})", [
							certificates.count,
							(certificates.rows || [])
								.map(
									(row) =>
										`${row.employee_name || row.employee} ${h.day(
											row.expires_on
										)}`
								)
								.join("; "),
						])
					),
					"staff",
					__("See staff")
				)
			);
		return TcFlowLead.card(
			h,
			__("Decisions for the head of infection control"),
			items.length
				? `<ul class="tcf-decisions">${items.join("")}</ul>`
				: `<p class="tcf-empty">${h.esc(__("Nothing is waiting for a decision."))}</p>`
		);
	},

	overviewHtml(h, data) {
		const kpis = data.kpis || {};
		const kpi = (...args) => TcFlowLead.kpi(h, ...args);
		const output = (data.output || [])
			.map(
				(row) => `<tr>
					<td>${h.esc(
						row.station_no &&
							!String(row.station_name).startsWith(`T${row.station_no}`)
							? `T${row.station_no} ${row.station_name}`
							: row.station_name
					)}</td>
					<td>${h.esc(row.count)}</td>
					<td>${h.esc((row.people || []).join(", "))}</td>
				</tr>`
			)
			.join("");
		const stateText = {
			within: __("Within par level"),
			below: __("Below minimum"),
			above: __("Above maximum"),
			none: __("No par level set"),
		};
		const departments = (data.departments || [])
			.map(
				(row) => `<tr>
					<td>${h.esc(row.department_name)}</td>
					<td>${h.esc(row.stock)}</td>
					<td>${h.esc(`${row.min}–${row.max}`)}</td>
					<td>${TcFlowLead.badge(h, stateText[row.state] || row.state, row.state)}</td>
				</tr>`
			)
			.join("");
		return `${TcFlowLead.decisionsHtml(h, data.decisions || {})}
			<div class="tcf-kpis">
				${kpi(kpis.reprocessing || 0, __("Sets being reprocessed"), "info")}
				${kpi(
					kpis.loads_today || 0,
					__("Loads today · {0} waiting for release", [kpis.loads_waiting || 0]),
					"pass"
				)}
				${kpi(kpis.par_blocked || 0, __("Sets at par level, waiting for disposal or override"), "fail")}
				${kpi(kpis.par_warn || 0, __("Sets close to par level"), "warn")}
				${kpi(kpis.sterile || 0, __("Packs in the sterile store"), "info")}
				${kpi(kpis.expiring || 0, __("Packs expiring within 7 days"), "warn")}
				${kpi(kpis.cost_per_pack || 0, __("Average cost per pack this month"), "info", "vnd")}
				${kpi(kpis.open_nc || 0, __("Open incidents / NC"), "fail")}
			</div>
			<div class="tcf-two">
				${TcFlowLead.card(
					h,
					__("Output by station today"),
					TcFlowLead.table(
						h,
						[__("Station"), __("Sets / packs"), __("People")],
						output,
						__("No station has recorded a passed step today.")
					)
				)}
				${TcFlowLead.card(
					h,
					__("Sets at departments against par level"),
					TcFlowLead.table(
						h,
						[
							__("Department", null, "Zone Station"),
							__("Stock", null, "TC Lead"),
							__("Par level", null, "TC Lead"),
							__("Status"),
						],
						departments,
						__("No department has a par level set.")
					)
				)}
			</div>`;
	},

	// ---- 2. Ghi đè cơ số ----
	cycles(h, row) {
		const percent = row.max_cycles
			? Math.round(((row.cycles_used || 0) * 100) / row.max_cycles)
			: null;
		return h.esc(
			__("{0}/{1} cycles", [row.cycles_used || 0, row.max_cycles || 0]) +
				(percent === null ? "" : ` (${percent}%)`)
		);
	},

	overridesHtml(h, data) {
		const requests = (data.requests || [])
			.map((row) => {
				const decide = data.can_decide
					? `<button type="button" class="tcf-btn" data-action="tcf-override-open" data-kind="approve"
							data-override="${h.esc(row.name)}">${h.esc(__("Approve (PIN)"))}</button>
						<button type="button" class="tcf-btn tcf-btn-secondary" data-action="tcf-override-open"
							data-kind="reject" data-override="${h.esc(row.name)}">${h.esc(__("Reject"))}</button>`
					: TcFlowLead.badge(h, __("Waiting for the head of infection control"), "warn");
				return `<tr>
					<td class="tcf-code">${h.esc(row.name)}</td>
					<td><b class="tcf-code">${h.esc(row.set_id)}</b><br />${h.esc(
					[row.set_name, row.department_name].filter(Boolean).join(" · ")
				)}</td>
					<td>${TcFlowLead.cycles(h, row)}</td>
					<td>${h.esc(row.requested_by_name || "")}<br />${h.esc(row.reason || "")}</td>
					<td>${h.esc(h.time(row.requested_at))}</td>
					<td class="tcf-actions">${decide}</td>
				</tr>`;
			})
			.join("");
		const stateText = {
			blocked: __("At par level"),
			warn: __("Close to par level"),
			override: __("Override in effect"),
		};
		const sets = (data.sets || [])
			.map((row) => {
				const ahead = row.forecast;
				const [year, month] = ahead ? ahead.month.split("-") : [];
				const forecast = ahead
					? `${__("Month {0}", [`${Number(month)}/${year}`])}${
							ahead.price ? ` · ${TcFlow.vnd(ahead.price)}` : ""
					  }`
					: "—";
				return `<tr>
					<td class="tcf-code">${h.esc(row.set_id)}</td>
					<td>${h.esc(row.set_name || "")}</td>
					<td>${h.esc(row.department_name || "")}</td>
					<td>${TcFlowLead.cycles(h, row)}</td>
					<td>${TcFlowLead.badge(h, stateText[row.state] || row.state, row.state)}</td>
					<td>${h.esc(forecast)}</td>
				</tr>`;
			})
			.join("");
		return `<p class="tcf-lead-note" role="note">${h.esc(
			__(
				"Only the head of infection control (or an authorized head nurse) approves. An override has extra cycles and an end date; when they run out the set is blocked again. Every decision is written to the audit log."
			)
		)}</p>
			${TcFlowLead.card(
				h,
				__("Requests waiting for approval"),
				`<div class="tcf-override-alert"></div>${TcFlowLead.table(
					h,
					[
						__("Code", null, "TC Lead"),
						__("Instrument set"),
						__("Cycles"),
						__("Requested by · reason"),
						__("Requested at"),
						__("Decision"),
					],
					requests,
					__("No override request is waiting for approval.")
				)}<div class="tcf-override-form"></div>`
			)}
			${TcFlowLead.card(
				h,
				__("Sets at or close to par level"),
				TcFlowLead.table(
					h,
					[
						__("Set ID"),
						__("Set type"),
						__("Department", null, "Zone Station"),
						__("Cycles"),
						__("Status"),
						__("Replacement forecast"),
					],
					sets,
					__("No set is at or close to its par level.")
				)
			)}`;
	},

	// form duyệt / từ chối: số chu trình thêm, thời hạn, lý do, PIN (UC-31)
	overrideFormHtml(h, kind, override, today) {
		const approve = kind === "approve";
		const extra = approve
			? `<label class="tcf-field"><span>${h.esc(__("Extra cycles"))}</span>
					<input class="tcf-input tcf-override-cycles" type="number" inputmode="numeric" min="1" step="1" value="5" /></label>
				<label class="tcf-field"><span>${h.esc(__("Valid until"))}</span>
					<input class="tcf-input tcf-override-until" type="date" min="${h.esc(today)}" /></label>`
			: "";
		return `<div class="tcf-override-box" data-kind="${kind}" data-override="${h.esc(
			override
		)}">
			<h4>${h.esc(
				approve
					? __("Approve override {0}", [override])
					: __("Reject override {0}", [override])
			)}</h4>
			<div class="tcf-form">
				${extra}
				<label class="tcf-field"><span>${h.esc(__("Reason for the decision"))}</span>
					<input class="tcf-input tcf-override-reason" type="text" maxlength="140" autocomplete="off" /></label>
				<label class="tcf-field"><span>${h.esc(__("Your PIN"))}</span>
					<input class="tcf-input tcf-override-pin" type="password" inputmode="numeric" autocomplete="off" /></label>
			</div>
			<div class="tcf-actions">
				<button type="button" class="tcf-btn" data-action="tcf-override-send">${h.esc(
					approve ? __("Confirm approval") : __("Confirm rejection")
				)}</button>
				<button type="button" class="tcf-btn tcf-btn-secondary" data-action="tcf-override-cancel">${h.esc(
					__("Cancel", null, "TC Lead")
				)}</button>
			</div>
		</div>`;
	},

	// ---- 3. Thu hồi và sự cố ----
	recallsHtml(h, data) {
		const orders = (data.orders || [])
			.map((order) => {
				const rows = (order.lines || [])
					.map((line) => {
						const state = [
							__(line.status_at_recall || "", null, "Pack"),
							line.patient_code_masked,
						]
							.filter(Boolean)
							.join(" · ");
						const confirm = line.confirmed
							? `${TcFlowLead.badge(
									h,
									__("Confirmed", null, "Recall"),
									"Confirmed"
							  )} ${h.esc(
									[line.confirmed_by_name, h.time(line.confirmed_at)]
										.filter(Boolean)
										.join(" · ")
							  )}`
							: TcFlowLead.badge(
									h,
									line.action === "Notify Physician"
										? __("Waiting for the physician to be informed")
										: __("Waiting for the department"),
									"Pending"
							  );
						return `<tr>
							<td class="tcf-code">${h.esc(line.pack)}</td>
							<td>${h.esc(line.department_name || line.department || __("Sterile store"))}</td>
							<td>${h.esc(state)}</td>
							<td>${confirm}</td>
						</tr>`;
					})
					.join("");
				const source = [
					__(order.trigger || "", null, "Recall"),
					order.sterilization_load &&
						__("load {0}", [order.sterilization_load]) +
							(order.equipment_name ? ` (${order.equipment_name})` : ""),
					order.reason,
					order.opened_at && __("opened at {0}", [h.time(order.opened_at)]),
				]
					.filter(Boolean)
					.join(" · ");
				return `<section class="tcf-card">
					<h3>${h.esc(__("Recall order {0}", [order.name]))} ${TcFlowLead.badge(
					h,
					__("Recalling: {0}/{1} confirmed", [
						order.confirmed_count || 0,
						order.pack_count || 0,
					]),
					"warn"
				)}</h3>
					<p class="tcf-sub-line">${h.esc(source)}</p>
					${TcFlowLead.table(
						h,
						[
							__("Cycle ID"),
							__("Department / location"),
							__("Status at recall"),
							__("Confirmation"),
						],
						rows,
						__("This recall order has no pack.")
					)}
					<p class="tcf-note">${h.esc(
						__(
							"Patient codes are shown masked. The order closes only when every pack is confirmed and the corrective action of its incident is complete."
						)
					)}</p>
				</section>`;
			})
			.join("");
		const incidents = (data.incidents || [])
			.map(
				(row) => `<tr>
					<td class="tcf-code">${h.esc(row.name)}</td>
					<td>${h.esc(__(row.incident_type || ""))}</td>
					<td>${TcFlowLead.badge(h, __(row.severity || "", null, "Incident CAPA"), row.severity)}</td>
					<td>${h.esc(row.description || "")}</td>
					<td>${TcFlowLead.badge(h, __(row.status || "", null, "Incident CAPA"), row.status)}</td>
				</tr>`
			)
			.join("");
		return `${
			orders ||
			TcFlowLead.card(
				h,
				__("Recall orders"),
				`<p class="tcf-empty">${h.esc(__("No recall order is open."))}</p>`
			)
		}
			${TcFlowLead.card(
				h,
				__("Open incidents / nonconformities"),
				TcFlowLead.table(
					h,
					[
						__("Code", null, "TC Lead"),
						__("Type"),
						__("Severity"),
						__("Description"),
						__("Status"),
					],
					incidents,
					__("No incident is open.")
				)
			)}`;
	},

	// ---- 4. Giá thành tái xử lý ----
	monthText(month) {
		const [year, index] = String(month || "").split("-");
		return `${Number(index)}/${year}`;
	},

	costsToolsHtml(h, month) {
		return `<button type="button" class="tcf-btn tcf-btn-secondary" data-action="tcf-lead-month"
				data-month="${h.esc(TcFlow.monthShift(month, -1))}">${h.esc(__("Previous month"))}</button>
			<button type="button" class="tcf-btn tcf-btn-secondary" data-action="tcf-lead-month"
				data-month="${h.esc(TcFlow.monthShift(month, 1))}">${h.esc(__("Next month"))}</button>`;
	},

	costsHtml(h, data) {
		const kpi = (...args) => TcFlowLead.kpi(h, ...args);
		const change = TcFlow.signedPct(data.change_pct);
		const types = (data.set_types || [])
			.map(
				(row) => `<tr>
					<td>${h.esc(row.set_name)}</td>
					<td>${h.esc(row.packs)}</td>
					<td>${h.esc(TcFlow.vnd(row.total))}</td>
					<td>${h.esc(TcFlow.vnd(row.average))}</td>
				</tr>`
			)
			.join("");
		const components = (data.components || [])
			.map(
				(row) => `<tr>
					<td>${h.esc(__(row.component || "", null, "Cost Sheet Line"))}</td>
					<td>${h.esc(TcFlow.vnd(row.amount))}</td>
					<td>${h.esc(`${String(row.share).replace(".", ",")}%`)}</td>
				</tr>`
			)
			.join("");
		const inputs = (data.inputs || [])
			.map(
				(row) => `<tr>
					<td>${h.esc(__(row.category || ""))}</td>
					<td>${h.esc(__(row.source || "", null, "Cost Entry"))}</td>
					<td>${h.esc(TcFlow.vnd(row.amount))}</td>
				</tr>`
			)
			.join("");
		return `<div class="tcf-kpis">
				${kpi(data.per_load || 0, __("Average cost of one steam sterilization load"), "info", "vnd")}
				${kpi(data.per_pack || 0, __("Average sterilization cost per pack"), "info", "vnd")}
				${kpi(data.packs || 0, __("Packs costed in {0} loads", [data.loads || 0]), "info")}
				<div class="tcf-kpi" data-tone="pass"><b>${h.esc(change)}</b><small>${h.esc(
			__("Cost per pack against the previous month")
		)}</small></div>
			</div>
			<div class="tcf-two">
				${TcFlowLead.card(
					h,
					__("Cost by set type"),
					TcFlowLead.table(
						h,
						[
							__("Set type"),
							__("Packs"),
							__("Total cost", null, "TC Lead"),
							__("Cost per pack", null, "TC Lead"),
						],
						types,
						__("No pack was costed this month.")
					)
				)}
				${TcFlowLead.card(
					h,
					__("Cost structure of the month"),
					TcFlowLead.table(
						h,
						[
							__("Cost item"),
							__("Amount", null, "TC Lead"),
							__("Share", null, "TC Lead"),
						],
						components,
						__("No cost sheet this month.")
					)
				)}
			</div>
			${TcFlowLead.card(
				h,
				__("Input costs of the month (entered)"),
				TcFlowLead.table(
					h,
					[__("Cost item"), __("Source"), __("Amount", null, "TC Lead")],
					inputs,
					__("No input cost was entered for this month.")
				)
			)}`;
	},

	// ---- 5. Thiết bị và test hằng ngày ----
	equipmentHtml(h, data) {
		const rows = (data.rows || [])
			.map((row) => {
				const tests = (row.tests || [])
					.map((test) => {
						const result = test.result
							? __(test.result, null, "Sterilization Log")
							: __("running", null, "TC Lead");
						return `${__(test.test_type || "", null, "Daily Test")}: ${result}${
							test.tested_at ? ` ${h.hour(test.tested_at)}` : ""
						}`;
					})
					.join("; ");
				const tested = tests || (row.daily_test_required ? __("Not tested today") : "—");
				const due = row.inspection_due
					? `${h.esc(h.day(row.inspection_due))}${
							row.expiring
								? ` ${TcFlowLead.badge(
										h,
										row.inspection_days < 0
											? __("Overdue")
											: __("Due in {0} days", [row.inspection_days]),
										row.inspection_days < 0 ? "expired" : "expiring"
								  )}`
								: ""
					  }`
					: "—";
				const status =
					__(row.status || "", null, "Equipment") +
					(row.lock_reason ? ` · ${__(row.lock_reason, null, "Equipment")}` : "");
				return `<tr>
					<td><b class="tcf-code">${h.esc(row.name)}</b><br />${h.esc(
					[row.equipment_name, row.model, row.capacity].filter(Boolean).join(" · ")
				)}</td>
					<td>${h.esc(__(row.equipment_type || "", null, "Equipment"))}</td>
					<td>${h.esc(
						[
							row.is_connected
								? __("Automatic (agent)")
								: __("Manual entry with confirmation"),
							row.has_printout ? __("has printout") : null,
						]
							.filter(Boolean)
							.join(" · ")
					)}</td>
					<td>${TcFlowLead.badge(h, status, row.status)}</td>
					<td>${h.esc(tested)}</td>
					<td>${due}</td>
					<td>${h.esc((row.programs || []).join("; "))}</td>
				</tr>`;
			})
			.join("");
		return TcFlowLead.card(
			h,
			"",
			`${TcFlowLead.table(
				h,
				[
					__("Machine", null, "TC Lead"),
					__("Type"),
					__("Cycle data"),
					__("Status"),
					__("Tests on {0}", [h.day(data.date)]),
					__("Inspection due"),
					__("Programs", null, "TC Lead"),
				],
				rows,
				__("No equipment is set up yet.")
			)}
			<p class="tcf-note">${h.esc(
				__(
					"A locked machine cannot be chosen when a load is created. The head nurse can unlock it for up to 24 hours with a reason, except when the pressure equipment inspection is overdue."
				)
			)}</p>`
		);
	},

	// ---- 6. Nhân sự, chứng chỉ và năng lực trạm ----
	staffHtml(h, data) {
		const text = (row) => {
			if (row.state === "none") return __("No certificate");
			if (row.state === "expired") return __("Certificate expired");
			if (row.state === "expiring") return __("Expiring in {0} days", [row.days_left]);
			return __("Valid", null, "Certificate");
		};
		const rows = (data.rows || [])
			.map((row) => {
				const stations = TcFlow.stationCodes(row.stations);
				return `<tr>
					<td><span class="tcf-code">${h.esc(row.employee)}</span> ${h.esc(row.employee_name)}</td>
					<td>${h.esc(row.designation || "")}</td>
					<td>${h.esc((row.certificates || []).join("; ") || __("No certificate"))}</td>
					<td>${h.esc(row.expires_on ? h.day(row.expires_on) : "—")}</td>
					<td>${h.esc(stations || __("Not assigned"))}</td>
					<td>${TcFlowLead.badge(h, text(row), row.state)}${
					stations ? "" : ` ${h.esc(__("cannot log in at a station"))}`
				}</td>
				</tr>`;
			})
			.join("");
		return TcFlowLead.card(
			h,
			"",
			TcFlowLead.table(
				h,
				[
					__("Employee"),
					__("Position", null, "TC Lead"),
					__("Certificates"),
					__("Expiry"),
					__("Station competency"),
					__("Status"),
				],
				rows,
				__("No employee has a certificate or a station competency yet.")
			)
		);
	},

	// ---- 7. Sổ tiệt khuẩn điện tử ----
	logToolsHtml(h, data) {
		const options = [`<option value="">${h.esc(__("All sterilizers"))}</option>`]
			.concat(
				(data.machines || []).map(
					(row) =>
						`<option value="${h.esc(row.name)}"${
							row.name === data.equipment ? " selected" : ""
						}>${h.esc(
							[row.name, row.equipment_name].filter(Boolean).join(" · ")
						)}</option>`
				)
			)
			.join("");
		return `<label class="tcf-sr" for="tcf-log-machine">${h.esc(
			__("Machine", null, "TC Lead")
		)}</label>
			<select id="tcf-log-machine" class="tcf-select tcf-log-machine">${options}</select>
			<label class="tcf-sr" for="tcf-log-date">${h.esc(__("Date", null, "TC Lead"))}</label>
			<input id="tcf-log-date" class="tcf-input tcf-log-date" type="date" value="${h.esc(
				data.date
			)}" />`;
	},

	logReportUrl(data) {
		const query = new URLSearchParams({ from_date: data.date, to_date: data.date });
		if (data.equipment) query.set("equipment", data.equipment);
		return `/app/query-report/Sterilization Log?${query.toString()}`;
	},

	logHtml(h, data) {
		const rows = (data.rows || [])
			.map(
				(row) => `<tr>
					<td class="tcf-code">${h.esc(row.load)}</td>
					<td>${h.esc(row.equipment)}</td>
					<td>${h.esc(h.hour(row.started_at))}</td>
					<td>${h.esc(row.program_name || "")}</td>
					<td>${h.esc(row.params || "")}</td>
					<td>${h.esc(row.indicators || "—")}</td>
					<td>${h.esc(row.pack_count)}</td>
					<td>${h.esc(row.operator_name || "")}</td>
					<td>${h.esc(
						row.released_by_name
							? `${row.released_by_name} ${h.hour(row.released_at)}`
							: "—"
					)}</td>
					<td>${TcFlowLead.badge(h, __(row.result || "", null, "Sterilization Log"), row.result)}</td>
				</tr>`
			)
			.join("");
		return TcFlowLead.card(
			h,
			"",
			`${TcFlowLead.table(
				h,
				[
					__("Load"),
					__("Machine", null, "TC Lead"),
					__("Time", null, "TC Lead"),
					__("Program"),
					__("Parameters", null, "TC Lead"),
					__("Indicators"),
					__("Packs"),
					__("Operator", null, "TC Lead"),
					__("Released by"),
					__("Result"),
				],
				rows,
				__("No finished load on this day.")
			)}
			<div class="tcf-actions">
				<button type="button" class="tcf-btn" data-action="tcf-log-report">${h.esc(
					__("Open the report to export PDF / Excel")
				)}</button>
			</div>`
		);
	},
};

window.TcFlowLead = TcFlowLead;
