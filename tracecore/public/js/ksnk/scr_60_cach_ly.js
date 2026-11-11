/* global tracecore */
// SCR-60 Lệnh cách ly & phòng cách ly — view WEB trong Page tc-ksnk (FEAT-068; UC-52; FR-M14-06, .1, FR-M14-07;
// BRU-MDR-003; A-146). R01/R11: tạo lệnh (điền sẵn từ chủng đa kháng ?isolate=), danh sách đang cách ly mọi khoa, kết
// thúc (bắt buộc lý do), hủy nhập nhầm; R13: chỉ phòng cách ly và tỷ lệ khoa có phòng đạt. Mã BN chỉ dạng che. Lỗi
// chặn = alert inline (kết quả → lý do → hành động); trạng thái luôn có chữ, không chỉ màu.

const TC_ISO_OVERVIEW = "tracecore.v1.isolation.overview";
const TC_ISO_CREATE = "tracecore.v1.isolation.create_order";
const TC_ISO_CLOSE = "tracecore.v1.isolation.close_order";
const TC_ISO_CANCEL = "tracecore.v1.isolation.cancel_order";
const TC_ISO_CONTEXT = "Isolation Order";
const TC_ISO_ROOM_CONTEXT = "Isolation Room";

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnkScr60 = {
	uuid() {
		const bytes = crypto.getRandomValues(new Uint8Array(16));
		bytes[6] = (bytes[6] & 0x0f) | 0x40;
		bytes[8] = (bytes[8] & 0x3f) | 0x80;
		const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
		return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(
			16,
			20
		)}-${hex.slice(20)}`;
	},

	iso(date = new Date()) {
		const pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
		const offset = -date.getTimezoneOffset();
		return (
			`${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
			`T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
			`${offset >= 0 ? "+" : "-"}${pad(offset / 60)}:${pad(offset % 60)}`
		);
	},

	date(value) {
		if (!value) return "—";
		const [y, m, d] = String(value).slice(0, 10).split("-");
		return `${d}/${m}/${y}`;
	},

	opt(value, context) {
		return value ? __(value, null, context || TC_ISO_CONTEXT) : "—";
	},

	yesNo(value) {
		return value ? __("Yes") : __("No");
	},

	// POST @idempotent: khóa giữ nguyên khi bấm lại cùng dữ liệu (thử lại sau lỗi mạng)
	post(method, args, handlers) {
		const sig = JSON.stringify([method, args]);
		if (!TcKsnkScr60.pending || TcKsnkScr60.pending.sig !== sig)
			TcKsnkScr60.pending = { sig, key: TcKsnkScr60.uuid(), ts: TcKsnkScr60.iso() };
		const pending = TcKsnkScr60.pending;
		const handle = (result) => {
			if (result && result.ok === false) {
				TcKsnkScr60.pending = null;
				handlers.on_block(result.error || {});
				return;
			}
			TcKsnkScr60.pending = null;
			tracecore.saved_notice(handlers.success);
			handlers.on_ok(result || {});
		};
		frappe.call({
			method,
			args: { ...args, client_ts: pending.ts },
			headers: { "X-Idempotency-Key": pending.key },
			callback: (response) => handle(response.message),
			error: (xhr) => {
				const body = xhr && xhr.responseJSON && xhr.responseJSON.message;
				if (body && body.ok === false) return handle(body);
				handlers.on_fail && handlers.on_fail();
			},
		});
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

	selectHtml(field, options, chosen, esc, required, context) {
		const items = options
			.map(
				(value) =>
					`<option value="${esc(value)}"${value === chosen ? " selected" : ""}>${esc(
						TcKsnkScr60.opt(value, context)
					)}</option>`
			)
			.join("");
		return `<select class="form-control" data-field="${esc(field)}"${
			required ? ' aria-required="true"' : ""
		}><option value="">${esc(__("— Choose —"))}</option>${items}</select>`;
	},

	roomOptions(data, department, esc) {
		const rooms = (data.rooms || []).filter((room) => room.department === department);
		const options = rooms
			.map((room) => {
				const label = `${room.room_code} (${
					room.meets_standard ? __("meets standard") : __("does not meet standard")
				}, ${room.free ? __("{0} free", [room.free]) : __("full")})`;
				return `<option value="${esc(room.name)}">${esc(label)}</option>`;
			})
			.join("");
		return `<option value="">${esc(__("No room — bedside isolation"))}</option>${options}`;
	},

	formHtml(data, esc) {
		const self = TcKsnkScr60;
		if (!data.can_write) return "";
		const p = data.prefill || {};
		const department = p.department || (data.departments[0] || {}).name || "";
		const departments = data.departments
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						row.name === department ? " selected" : ""
					}>${esc(row.label)}</option>`
			)
			.join("");
		const patient = p.isolate
			? `<div class="form-control tc-ksnk-code" aria-readonly="true">${esc(
					p.patient_code_masked
			  )} · ${esc(p.isolate)} · ${esc(p.mdro_flags || p.organism_name || "")}</div>`
			: `<input type="text" class="form-control" data-field="patient_code" autocomplete="off" maxlength="64">`;
		return `<section class="tc-ksnk-card" data-region="create">
			<h3>${esc(
				__("Create isolation order")
			)} <span class="tc-ksnk-tag tc-ksnk-code">Isolation Order · CL-</span></h3>
			<div class="tc-ksnk-form tc-ksnk-stack">
				<label>${esc(
					p.isolate
						? __("Patient (from multidrug-resistant isolate)")
						: __("Patient Code")
				)}${patient}</label>
				<p class="tc-ksnk-note">${esc(
					__(
						"The patient code is encrypted and shown masked. Do not enter the patient name."
					)
				)}</p>
				<label>${esc(__("Department"))}<select class="form-control" data-field="department"${
			p.isolate ? " disabled" : ""
		}>${departments}</select></label>
				<label>${esc(__("Precaution Type"))} *${self.selectHtml(
			"precaution_type",
			data.precautions,
			p.precaution_type,
			esc,
			true
		)}</label>
				<label>${esc(__("Reason"))} *${self.selectHtml(
			"reason",
			data.reasons,
			p.reason,
			esc,
			true
		)}</label>
				<label>${esc(
					__("Reason Details")
				)}<input type="text" class="form-control" data-field="reason_detail" maxlength="500"></label>
				<label>${esc(
					__("Isolation Room")
				)}<select class="form-control" data-field="isolation_room">${self.roomOptions(
			data,
			department,
			esc
		)}</select></label>
				<label>${esc(
					__("Start At")
				)}<input type="datetime-local" class="form-control" data-field="start_at"></label>
			</div>
			<div data-region="create-alert"></div>
			<div class="tc-ksnk-actions">
				<button type="button" class="btn btn-primary" data-action="create">${esc(
					__("Create isolation order")
				)}</button>
				<button type="button" class="btn btn-default" data-action="reset">${esc(__("Cancel"))}</button>
			</div>
		</section>`;
	},

	ordersHtml(data, esc) {
		const self = TcKsnkScr60;
		if (!data.can_read_orders) return "";
		const rows = data.orders || [];
		const body = rows
			.map((r) => {
				const flags = (r.mdro_history || []).length
					? ` <span class="tc-ksnk-badge is-fail">${esc(__("MDRO"))}: ${esc(
							r.mdro_history.join(", ")
					  )}</span>`
					: r.is_mdro
					? ` <span class="tc-ksnk-badge is-fail">${esc(__("MDRO"))}</span>`
					: "";
				const room = r.room_code
					? `<span class="tc-ksnk-code">${esc(r.room_code)}</span>`
					: `<span class="tc-ksnk-badge is-warn">${esc(__("Bedside"))}</span>`;
				const closable = !r.is_mdro || data.mdro_close;
				const close = closable
					? `<button type="button" class="btn btn-link" data-action="close" data-name="${esc(
							r.name
					  )}">${esc(__("End isolation"))}</button>`
					: `<span class="tc-ksnk-note">${esc(__("Infection control closes"))}</span>`;
				const cancel = data.can_cancel
					? ` <button type="button" class="btn btn-link" data-action="cancel" data-name="${esc(
							r.name
					  )}">${esc(__("Cancel entry"))}</button>`
					: "";
				return `<tr>
					<td class="tc-ksnk-code">${esc(r.name)}</td>
					<td class="tc-ksnk-code">${esc(r.patient_code_masked || "—")}${flags}</td>
					<td>${esc(r.department_name || r.department)}</td>
					<td>${esc(self.opt(r.precaution_type))}</td>
					<td>${room}</td>
					<td>${esc(self.date(r.start_at))}</td>
					<td class="is-num">${esc(r.days)}</td>
					<td>${close}${cancel}</td>
				</tr>`;
			})
			.join("");
		const table = rows.length
			? `<table class="tc-ksnk-table"><thead><tr>
				<th>${esc(__("Isolation order no."))}</th><th>${esc(__("Patient Code"))}</th><th>${esc(
					__("Department")
			  )}</th>
				<th>${esc(__("Precaution"))}</th><th>${esc(__("Room"))}</th><th>${esc(__("From"))}</th>
				<th>${esc(__("Days"))}</th><th></th></tr></thead><tbody>${body}</tbody></table>`
			: `<p class="tc-ksnk-state">${esc(__("No patient in isolation."))}</p>`;
		return `<section class="tc-ksnk-card" data-region="orders">
			<h3>${esc(__("In isolation"))} <span class="tc-ksnk-badge is-warn">${esc(
			__("{0} patients", [rows.length])
		)}</span></h3>
			<div data-region="orders-alert"></div>${table}
			<div class="tc-ksnk-alert is-info" role="note">${esc(
				__(
					"Departments (R08/R12) create and end isolation orders on the department portal; infection control follows all departments."
				)
			)}</div></section>`;
	},

	roomsHtml(data, esc) {
		const self = TcKsnkScr60;
		const cov = data.coverage || {};
		const rate = cov.rate === null || cov.rate === undefined ? "—" : `${cov.rate} %`;
		const kpi = `<div class="tc-ksnk-kpis"><div class="tc-ksnk-kpi${
			cov.missing && cov.missing.length ? " is-warn" : " is-pass"
		}"><span>${esc(
			__("Clinical departments with at least 1 isolation room meeting the standard")
		)}</span>
			<strong>${esc(cov.covered)}/${esc(cov.total)}</strong><small>${esc(rate)}</small></div></div>`;
		const condition = (room) =>
			room.meets_standard
				? `<span class="tc-ksnk-badge is-pass">${esc(__("Meets standard"))}</span>`
				: room.checked_on
				? `<span class="tc-ksnk-badge is-fail">${esc(__("Not met"))} — ${esc(
						room.standard_note || ""
				  )}</span>`
				: `<span class="tc-ksnk-badge is-neutral">${esc(__("Not checked"))}</span>`;
		const roomRows = (data.rooms || [])
			.map(
				(room) => `<tr>
				<td class="tc-ksnk-code"><a href="/app/isolation-room/${encodeURIComponent(room.name)}">${esc(
					room.room_code
				)}</a></td>
				<td>${esc(room.department_name || room.department)}</td>
				<td>${esc(self.opt(room.room_type, TC_ISO_ROOM_CONTEXT))}</td>
				<td class="is-num">${esc(room.beds)}</td>
				<td>${esc(self.yesNo(room.negative_pressure))}</td>
				<td>${esc(self.yesNo(room.has_hand_sink))}</td>
				<td>${esc(self.yesNo(room.has_anteroom))}</td>
				<td>${esc(
					room.occupied
						? __("In use ({0}/{1})", [room.occupied, room.beds])
						: __("Room free")
				)}</td>
				<td>${condition(room)}<div class="tc-ksnk-note">${esc(self.date(room.checked_on))}</div></td>
			</tr>`
			)
			.join("");
		const missingRows = (cov.missing || [])
			.map(
				(row) => `<tr><td>—</td><td>${esc(row.department_name)}</td>
				<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>
				<td><span class="tc-ksnk-badge is-fail">${esc(
					__("No room meeting the standard")
				)}</span></td></tr>`
			)
			.join("");
		const add = data.can_edit_rooms
			? `<div class="tc-ksnk-actions"><a class="btn btn-default" href="${esc(
					data.room_form
			  )}">${esc(__("Add isolation room"))}</a></div>`
			: "";
		return `<section class="tc-ksnk-card"><h3>${esc(
			__("Isolation rooms by department")
		)} <span class="tc-ksnk-tag tc-ksnk-code">Isolation Room · PCL-</span></h3>${kpi}
			<table class="tc-ksnk-table"><thead><tr>
				<th>${esc(__("Room"))}</th><th>${esc(__("Department"))}</th><th>${esc(__("Type"))}</th>
				<th>${esc(__("Beds"))}</th><th>${esc(__("Negative Pressure"))}</th><th>${esc(
			__("Own Hand-Wash Sink")
		)}</th>
				<th>${esc(__("Anteroom"))}</th><th>${esc(__("Room status"))}</th><th>${esc(__("Condition"))}</th>
			</tr></thead><tbody>${roomRows}${missingRows}</tbody></table>
			<p class="tc-ksnk-note">${esc(
				__(
					"Whether a room meets the standard is set by the head of infection control against the hospital criteria."
				)
			)}</p>${add}</section>`;
	},

	pageHtml(data, esc) {
		const self = TcKsnkScr60;
		const top =
			data.can_write || data.can_read_orders
				? `<div class="tc-ksnk-cols"><div>${self.formHtml(
						data,
						esc
				  )}</div><div>${self.ordersHtml(data, esc)}</div></div>`
				: "";
		return top + self.roomsHtml(data, esc);
	},

	values(region) {
		const out = {};
		region.querySelectorAll("[data-field]").forEach((input) => {
			out[input.dataset.field] = input.value;
		});
		return out;
	},

	askReason(title, label, done) {
		frappe.prompt(
			[{ fieldname: "reason", fieldtype: "Small Text", label, reqd: 1 }],
			(values) => done(values.reason),
			title,
			__("Confirm")
		);
	},

	bind(el, ctx, data, isolate) {
		const self = TcKsnkScr60;
		const form = el.querySelector('[data-region="create"]');
		if (form) {
			const department = form.querySelector('[data-field="department"]');
			if (department)
				department.addEventListener("change", () => {
					form.querySelector('[data-field="isolation_room"]').innerHTML =
						self.roomOptions(data, department.value, ctx.esc);
				});
			form.querySelector('[data-action="reset"]').addEventListener("click", () => {
				if (isolate) frappe.set_route("tc-ksnk", "cach-ly");
				else self.render(el, ctx);
			});
			form.querySelector('[data-action="create"]').addEventListener("click", (event) => {
				const button = event.currentTarget;
				const alert = form.querySelector('[data-region="create-alert"]');
				const args = { ...self.values(form), isolate: isolate || "" };
				button.disabled = true;
				self.post(TC_ISO_CREATE, args, {
					success: false, // tự báo "Đã tạo lệnh cách ly {0}"
					on_ok: (result) => {
						if (!ctx.isCurrent()) return;
						const warn = (result.warnings || []).join(" ");
						frappe.show_alert({
							message:
								__("Isolation order {0} created.", [result.order.name]) +
								" " +
								warn,
							indicator: warn ? "orange" : "green",
						});
						if (isolate) frappe.set_route("tc-ksnk", "cach-ly");
						else self.render(el, ctx);
					},
					on_block: (error) => {
						button.disabled = false;
						alert.innerHTML = self.blockHtml(error, ctx.esc);
						const field = {
							ISOLATION_PRECAUTION_REQUIRED: "precaution_type",
							ISOLATION_REASON_REQUIRED: "reason",
							ISOLATION_PATIENT_REQUIRED: "patient_code",
						}[error.code];
						form.querySelectorAll(".is-invalid").forEach((input) =>
							input.classList.remove("is-invalid")
						);
						const input = field && form.querySelector(`[data-field="${field}"]`);
						if (input) {
							input.classList.add("is-invalid");
							input.focus();
						}
					},
					on_fail: () => {
						button.disabled = false;
					},
				});
			});
		}
		const orders = el.querySelector('[data-region="orders"]');
		if (orders)
			orders.querySelectorAll("[data-action]").forEach((button) =>
				button.addEventListener("click", () => {
					const alert = orders.querySelector('[data-region="orders-alert"]');
					const cancel = button.dataset.action === "cancel";
					self.askReason(
						cancel ? __("Cancel this isolation order") : __("End isolation"),
						cancel ? __("Reason") : __("End Reason"),
						(reason) =>
							self.post(
								cancel ? TC_ISO_CANCEL : TC_ISO_CLOSE,
								cancel
									? { order: button.dataset.name, reason }
									: { order: button.dataset.name, end_reason: reason },
								{
									on_ok: () => ctx.isCurrent() && self.render(el, ctx),
									on_block: (error) => {
										alert.innerHTML = self.blockHtml(error, ctx.esc);
									},
								}
							)
					);
				})
			);
		el.querySelectorAll('[data-action="retry"]').forEach((button) =>
			button.addEventListener("click", () => self.render(el, ctx))
		);
	},

	async render(el, ctx) {
		el.innerHTML = ctx.state("loading");
		const isolate = new URLSearchParams(window.location.search).get("isolate") || "";
		try {
			const data = await ctx.get(TC_ISO_OVERVIEW, { isolate });
			if (!ctx.isCurrent()) return;
			el.innerHTML = TcKsnkScr60.pageHtml(data, ctx.esc);
			TcKsnkScr60.bind(el, ctx, data, data.prefill ? isolate : "");
		} catch (error) {
			if (!ctx.isCurrent()) return;
			el.innerHTML = ctx.state("error", (error && error.message) || "");
			TcKsnkScr60.bind(el, ctx, null, "");
		}
	},
};

window.TcKsnkScreens["cach-ly"] = TcKsnkScr60;
window.TcKsnkScr60 = TcKsnkScr60;
