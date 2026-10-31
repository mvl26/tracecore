/* global uuid4, clientTs, esc, TcWeighLine, wasteTabs */
// Màn bàn giao chất thải (SCR-40, FEAT-049, UC-36, A-62) trên Page station, trạm bước WST, tab Bàn giao.
// Frappe nối file này sau station_waste_store.js (hook page_js). Chọn đơn vị → quét túi hoặc thêm cả loại theo FIFO → kg theo
// loại → chứng từ, biển số, chữ ký → ghi sổ. Scan chứng từ và ảnh biên bản đính trên Desk (A-62 d). Lỗi chặn = alert-error
// inline (kết quả → lý do → hành động). Không offline: mất mạng thì báo và không ghi.

const WSH_VENDORS = "tracecore.v1.waste.handover_vendors";
const WSH_CREATE = "tracecore.v1.waste.handover_create";
const WSH_ADD = "tracecore.v1.waste.handover_add";
const WSH_REMOVE = "tracecore.v1.waste.handover_remove";
const WSH_SIGN = "tracecore.v1.waste.handover_sign";
const WSH_SUBMIT = "tracecore.v1.waste.handover_submit";
const WSH_APPROVER = "tracecore.v1.station.verify_approver";

class WasteHandoverScreen {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.clearSession();
		station.listen(this.result, "input", (event) => this.onInput(event));
		station.listen(this.result, "change", (event) => this.onInput(event));
	}

	get dialogOpen() {
		return false;
	}

	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.options = null;
		this.doc = null;
		this.done = null;
		this.notice = null;
		this.vendor = "";
		this.strokes = 0;
		this.signature = null;
		this.form = {
			weights: {},
			hazard_document_no: "",
			transporter: "",
			contract_no: "",
			vehicle_plate: "",
			vendor_signer: "",
			variance_reason: "",
			fifo_reason: "",
			document_pending: false,
			card: "",
			pin: "",
		};
	}

	updatePlaceholder() {
		const text = this.doc
			? __("Scan a waste bag to add it...")
			: __("Choose the treatment vendor");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	onInput(event) {
		const target = event.target;
		const field = target && target.dataset && target.dataset.wsh;
		if (!field) return;
		if (field === "vendor") this.vendor = target.value;
		else if (field === "kg") {
			this.weight(target.dataset.type).kg = target.value;
			this.weight(target.dataset.type).source = "Manual";
			this.weight(target.dataset.type).confirmed = false;
		} else if (field === "confirm")
			this.weight(target.dataset.type).confirmed = target.checked;
		else if (field === "document_pending") this.form.document_pending = target.checked;
		else this.form[field] = target.value;
	}

	weight(type) {
		if (!this.form.weights[type])
			this.form.weights[type] = { kg: "", source: "", confirmed: false };
		return this.form.weights[type];
	}

	scan(raw) {
		const code = (raw || "").trim().toUpperCase();
		this.input.value = "";
		if (!code) return this.station.focus();
		this.notice = null;
		if (!this.doc || !code.startsWith("CT-")) {
			this.notice = {
				variant: "error",
				title: __("Waste bag code expected"),
				reason: this.doc
					? __("{0} is not a location, a waste bag or a collection.", [code])
					: __("Choose the treatment vendor"),
				action: __("Scan a CT- bag code."),
			};
			return this.show();
		}
		return this.request(WSH_ADD, this.args({ container: code }), (res) => this.loaded(res));
	}

	args(extra = {}) {
		return {
			station: this.station.station,
			handover_name: this.doc && this.doc.name,
			...extra,
		};
	}

	loaded(res) {
		this.doc = res.handover;
		this.show();
	}

	async request(method, args, onOk) {
		if (this.busy || !this.station.session) return;
		const version = this.station.sessionVersion;
		const sig = method + JSON.stringify(args);
		if (!this.pending || this.pending.sig !== sig) {
			this.pending = { sig, method, args, onOk, key: uuid4(), ts: clientTs() };
		}
		const pending = this.pending;
		this.busy = method;
		let response = null;
		let failure = null;
		try {
			response = await this.station.rpc(
				method,
				{ ...args, client_ts: pending.ts },
				pending.key
			);
		} catch (error) {
			failure = error;
		}
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		if (!failure) this.pending = null;
		this.busy = null;
		if (failure) this.failure(failure);
		else if (response && response.ok === false) {
			this.notice = { variant: "error", ...response.error };
			this.show();
		} else onOk(response);
		this.station.focus();
	}

	retry() {
		this.station.manualOffline = false;
		if (!navigator.onLine) return this.station.setOffline(true);
		this.station.setOffline(false);
		const pending = this.pending;
		if (pending) return this.request(pending.method, pending.args, pending.onOk);
		this.notice = null;
		this.show();
	}

	failure(error) {
		if (error.offline && navigator.onLine === false) return this.station.setOffline(true);
		if (error.status >= 400 && error.status < 500) this.pending = null;
		let notice;
		if (error.offline) {
			notice = {
				title: __("No answer from the server"),
				reason: __(
					"The request got no answer in time; the server may already have recorded it."
				),
				action: __("Retry: the same request is sent again and is never recorded twice."),
			};
		} else if (error.status === 403) {
			notice = {
				title: __("Not permitted"),
				reason: __("This account cannot use waste handover at this station."),
				action: __("Log in with the station account or call R10."),
			};
		} else {
			notice = {
				title: __("Server error"),
				reason: __("The server could not process the request ({0}).", [
					error.status || "?",
				]),
				action: __("Retry, or call R02 if it happens again."),
			};
		}
		this.notice = { variant: "error", technical: true, ...notice };
		this.show();
	}

	onAction(action, button) {
		const handlers = {
			retry: () => this.retry(),
			"wsh-start": () =>
				this.request(
					WSH_CREATE,
					{ station: this.station.station, vendor: this.vendor },
					(res) => this.loaded(res)
				),
			"wsh-add-type": () =>
				this.request(WSH_ADD, this.args({ waste_type: button.dataset.type }), (res) =>
					this.loaded(res)
				),
			"wsh-remove": () =>
				this.request(WSH_REMOVE, this.args({ container: button.dataset.bag }), (res) =>
					this.loaded(res)
				),
			"wsh-weigh": () => this.weigh(button.dataset.type),
			"wsh-clear": () => this.clearPad(),
			"wsh-record": () => this.record(),
			"wsh-print": () => this.print(),
			"wsh-new": () => {
				this.clearSession();
				this.show();
			},
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	async weigh(type) {
		const reading = await TcWeighLine.read();
		if (!this.station.session) return;
		if (reading.ok) {
			Object.assign(this.weight(type), {
				kg: TcWeighLine.format(reading.kg),
				source: "Scale",
				confirmed: false,
			});
			this.notice = null;
		} else {
			this.notice = {
				variant: "warn",
				title: __("The scale did not answer"),
				reason: __("The station agent could not read the scale in 2 seconds."),
				action: __("Type the weight by hand and tick the confirmation."),
			};
		}
		this.show();
	}

	payload() {
		const canvas = this.result.querySelector("#tc-wsh-pad");
		if (canvas && this.strokes > 0) this.signature = canvas.toDataURL("image/png");
		const values = {};
		for (const key of [
			"hazard_document_no",
			"transporter",
			"contract_no",
			"vehicle_plate",
			"vendor_signer",
			"variance_reason",
			"fifo_reason",
		])
			values[key] = this.form[key];
		if (this.signature) values.vendor_signature = this.signature;
		const weights = this.doc.lines
			.map((line) => {
				const row = this.weight(line.waste_type);
				return {
					waste_type: line.waste_type,
					handover_kg: TcWeighLine.parse(row.kg),
					weight_source: row.source === "Scale" ? "Scale" : "Manual",
					weight_confirmed: row.confirmed ? 1 : 0,
				};
			})
			.filter((row) => row.handover_kg != null);
		return this.args({
			weights,
			values,
			document_pending: this.form.document_pending ? 1 : 0,
		});
	}

	// Ghi kg + chứng từ + chữ ký trước, rồi xin proof R02 nếu đã nhập thẻ + PIN, rồi ghi sổ
	record() {
		this.notice = null;
		this.request(WSH_SIGN, this.payload(), (res) => {
			this.doc = res.handover;
			if (this.form.card && this.form.pin) return this.approve();
			return this.submit(null);
		});
	}

	approve() {
		this.request(
			WSH_APPROVER,
			{
				token: this.station.session.token,
				card_id: this.form.card,
				pin: this.form.pin,
				role: "TC R02",
			},
			(res) => {
				this.form.pin = "";
				this.submit(res.proof);
			}
		);
	}

	submit(proof) {
		const extra = proof ? { approver_proof: proof } : {};
		this.request(WSH_SUBMIT, this.args(extra), (res) => {
			this.done = res.handover;
			this.doc = null;
			this.show();
		});
	}

	print() {
		const query = new URLSearchParams({
			doctype: "Waste Handover",
			name: this.done.name,
			format: "TC Waste Handover",
			trigger_print: "1",
			no_letterhead: "1",
		});
		window.open(`/printview?${query}`, "_blank", "noopener");
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		if (this.offline) return this.station.setState("offline", this.offlineHtml());
		const failed = this.notice && this.notice.variant === "error";
		if (!this.options && !this.busy && !failed) {
			this.request(WSH_VENDORS, { station: this.station.station }, (res) => {
				this.options = res;
				this.show();
			});
			return this.station.renderLoading();
		}
		const empty = this.options && !this.options.vendors.length && !this.doc && !this.done;
		const state = failed ? "error" : empty ? "empty" : "result";
		let body = "";
		if (this.done) body = this.doneHtml();
		else if (this.doc) body = this.docHtml();
		else if (this.options) body = this.vendorHtml();
		this.station.setState(
			state,
			`<div class="tc-linen tc-waste">
				${wasteTabs("handover")}
				<div data-region="notice">${this.noticeHtml()}</div>
				${body}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
		this.bindPad();
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(tcErrorTitle(notice))}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
			${tcGuideButton(notice)}
			${buttons}
		</div>`;
	}

	standardButtons() {
		return `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
				__("Retry")
			)}</button>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
				__("Call R02")
			)}</button>
		</div>`;
	}

	offlineHtml() {
		return this.alertHtml(
			{
				variant: "info",
				title: __("Station offline"),
				reason: __("Waste handover needs a network connection."),
				action: __("Retry when the connection returns."),
			},
			this.standardButtons()
		);
	}

	noticeHtml() {
		let html = "";
		if (this.busy) {
			html += `<p class="tc-loading" role="status" aria-busy="true">${esc(
				__("Loading...")
			)}</p>`;
		}
		if (this.notice)
			html += this.alertHtml(
				this.notice,
				this.notice.technical ? this.standardButtons() : ""
			);
		if (this.options && !this.options.vendors.length && !this.doc && !this.done) {
			html += this.alertHtml({
				variant: "info",
				title: __("No valid vendor"),
				reason: __("No vendor has a valid license and contract."),
				action: __("Ask R09 to update the vendors."),
			});
		}
		return html;
	}

	vendorHtml() {
		if (!this.options.vendors.length) return "";
		const options = this.options.vendors
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						this.vendor === row.name ? " selected" : ""
					}>${esc(row.vendor_name)}</option>`
			)
			.join("");
		return `<section class="tc-t6-block">
			<div class="tc-field">
				<label for="tc-wsh-vendor">${esc(__("Treatment Vendor"))}</label>
				<select id="tc-wsh-vendor" data-wsh="vendor">
					<option value="">${esc(__("Choose the treatment vendor"))}</option>${options}
				</select>
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="wsh-start">${esc(
					__("Start handover")
				)}</button>
			</div>
		</section>`;
	}

	fifoHtml() {
		const rows = this.doc.waste_types
			.map((type) => {
				const bags = (this.options.fifo[type] || []).filter(
					(bag) => !this.doc.containers.includes(bag.name)
				);
				if (!bags.length) return "";
				const codes = bags
					.slice(0, 5)
					.map((bag) => esc(bag.name))
					.join(", ");
				return `<div class="tc-linen-line">
					<p><strong>${esc(type)}</strong></p>
					<p class="tc-mono">${codes}</p>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="wsh-add-type" data-type="${esc(
						type
					)}">${esc(__("Add all of {0}", [type]))}</button>
				</div>`;
			})
			.join("");
		return rows
			? `<section class="tc-t6-block" aria-label="${esc(
					__("Suggested first (oldest first)")
			  )}"><h3>${esc(__("Suggested first (oldest first)"))}</h3>${rows}</section>`
			: "";
	}

	bagsHtml() {
		if (!this.doc.containers.length) return "";
		const rows = this.doc.containers
			.map(
				(bag) => `<tr>
				<td class="tc-mono">${esc(bag)}</td>
				<td><button type="button" class="tc-btn tc-btn-secondary" data-action="wsh-remove" data-bag="${esc(
					bag
				)}">${esc(__("Remove", null, "Waste Handover"))}</button></td>
			</tr>`
			)
			.join("");
		return `<table class="tc-t6-table" aria-label="${esc(__("Bags on this handover"))}">
			<tbody>${rows}</tbody>
		</table>`;
	}

	linesHtml() {
		return this.doc.lines
			.map((line) => {
				const row = this.weight(line.waste_type);
				const type = esc(line.waste_type);
				const over = this.doc.over_limit.includes(line.waste_type);
				return `<div class="tc-linen-line">
					<p><strong>${type}</strong>: ${esc(line.qty)} - ${esc(TcWeighLine.format(line.collected_kg))} kg${
					over
						? ` <span class="tc-badge-danger">&#10005; ${esc(
								__("Above the difference limit")
						  )}</span>`
						: ""
				}</p>
					<div class="tc-field">
						<label for="tc-wsh-kg-${type}">${esc(__("Handed over (kg)"))} *</label>
						<input id="tc-wsh-kg-${type}" type="text" inputmode="decimal" autocomplete="off"
							data-wsh="kg" data-type="${type}" value="${esc(row.kg)}">
					</div>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="wsh-weigh" data-type="${type}">${esc(
					__("Weigh")
				)}</button>
					<label class="tc-linen-flag"><input type="checkbox" data-wsh="confirm" data-type="${type}"${
					row.confirmed ? " checked" : ""
				}> ${esc(__("Confirm the typed weight"))}</label>
				</div>`;
			})
			.join("");
	}

	textField(key, label) {
		return `<div class="tc-field">
			<label for="tc-wsh-${key}">${esc(label)}</label>
			<input id="tc-wsh-${key}" type="text" autocomplete="off" data-wsh="${key}" value="${esc(
			this.form[key]
		)}">
		</div>`;
	}

	documentHtml() {
		if (!this.doc.needs_document) return this.textField("vehicle_plate", __("Vehicle Plate"));
		return `${this.textField("hazard_document_no", __("Hazardous Waste Document No"))}
			${this.textField("transporter", __("Transporter", null, "Waste Handover"))}
			${this.textField("contract_no", __("Contract No"))}
			${this.textField("vehicle_plate", __("Vehicle Plate"))}
			<label class="tc-linen-flag"><input type="checkbox" data-wsh="document_pending"${
				this.form.document_pending ? " checked" : ""
			}> ${esc(__("Document comes later"))}</label>
			<p class="tc-t6-hint">${esc(__("Scan and minutes photo are attached on the Desk form."))}</p>`;
	}

	approvalHtml() {
		if (!this.doc.over_limit.length) return "";
		return `${this.textField("variance_reason", __("Weight Difference Reason"))}
			${this.textField("card", __("R02 card"))}
			<div class="tc-field">
				<label for="tc-wsh-pin">${esc(__("R02 PIN"))}</label>
				<input id="tc-wsh-pin" type="password" inputmode="numeric" autocomplete="off" data-wsh="pin" value="">
			</div>`;
	}

	docHtml() {
		const skipped = this.doc.fifo_skipped.length
			? `${this.alertHtml({
					variant: "warn",
					title: __("Older bags were skipped"),
					reason: __("Older bags stay in the store: {0}.", [
						this.doc.fifo_skipped.join(", "),
					]),
			  })}${this.textField("fifo_reason", __("Reason for Skipping Older Bags"))}`
			: "";
		const hasBags = this.doc.containers.length > 0;
		return `<section class="tc-t6-block">
			<p><strong>${esc(__("Treatment Vendor"))}:</strong> ${esc(
			this.doc.vendor
		)} <span class="tc-mono">${esc(this.doc.name)}</span></p>
			${this.fifoHtml()}
			${this.bagsHtml()}
			${skipped}
			${
				hasBags
					? `${this.linesHtml()}
			${this.documentHtml()}
			${this.approvalHtml()}
			${this.textField("vendor_signer", __("Vendor Representative"))}
			<canvas id="tc-wsh-pad" class="tc-t7-pad" width="600" height="200" aria-label="${esc(
				__("Vendor signature box")
			)}"></canvas>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-secondary" data-action="wsh-clear">${esc(
					__("Clear signature")
				)}</button>
				<button type="button" class="tc-btn tc-btn-primary" data-action="wsh-record">${esc(
					this.doc.over_limit.length ? __("Approve and record") : __("Record handover")
				)}</button>
			</div>`
					: ""
			}
		</section>`;
	}

	doneHtml() {
		return `<section class="tc-t6-block">
			${this.alertHtml({
				variant: "ok",
				title: __("Handover {0} recorded", [this.done.name]),
				reason: __("Treatment cost: {0} VND.", [
					Math.round(this.done.total_cost || 0).toLocaleString("vi-VN"),
				]),
			})}
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="wsh-print">${esc(
					__("Print handover")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="wsh-new">${esc(
					__("New handover")
				)}</button>
			</div>
		</section>`;
	}

	// Khung ký cảm ứng theo cùng cách với biên nhận đồ vải (FR-M10-04.2); ký xong giữ lại khi màn vẽ lại
	bindPad() {
		const canvas = this.result.querySelector("#tc-wsh-pad");
		if (!canvas) return;
		const ctx = canvas.getContext("2d");
		ctx.lineWidth = 2;
		ctx.strokeStyle = getComputedStyle(canvas).color;
		if (this.signature) {
			const image = new Image();
			image.onload = () => ctx.drawImage(image, 0, 0);
			image.src = this.signature;
		}
		const point = (event) => {
			const box = canvas.getBoundingClientRect();
			return {
				x: ((event.clientX - box.left) * canvas.width) / box.width,
				y: ((event.clientY - box.top) * canvas.height) / box.height,
			};
		};
		let drawing = false;
		canvas.addEventListener("pointerdown", (event) => {
			drawing = true;
			canvas.setPointerCapture(event.pointerId);
			const at = point(event);
			ctx.beginPath();
			ctx.moveTo(at.x, at.y);
		});
		canvas.addEventListener("pointermove", (event) => {
			if (!drawing) return;
			const at = point(event);
			ctx.lineTo(at.x, at.y);
			ctx.stroke();
		});
		for (const name of ["pointerup", "pointercancel"]) {
			canvas.addEventListener(name, () => {
				if (drawing) this.strokes += 1;
				drawing = false;
				this.signature = canvas.toDataURL("image/png");
			});
		}
	}

	clearPad() {
		this.signature = null;
		this.strokes = 0;
		this.show();
	}
}
