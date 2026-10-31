/* global uuid4, clientTs, esc, TcWeighLine, wasteTabs */
// Màn thu gom chất thải theo khoa (SCR-38, FEAT-047, UC-34, A-60) trên Page station, trạm bước WST (kiosk và PDA).
// Frappe nối file này sau tc_weigh_line.js (hook page_js) nên dùng chung uuid4/clientTs/esc/TcWeighLine.
// Ô quét luôn ở đầu: quét thẻ người giao trước (khoa lấy từ thẻ), rồi quét hoặc gõ tên loại để thêm dòng; sau khi ghi sổ
// quét lại thẻ để xác nhận biên nhận. Mỗi dòng đúng một loại (BRU-WST-001). Lỗi chặn = alert-error inline (kết quả → lý
// do → hành động). Không offline: mất mạng thì báo và không ghi (A-60 W2).

const WST_CATALOG = "tracecore.v1.waste.catalog";
const WST_GIVER = "tracecore.v1.waste.giver";
const WST_COLLECT = "tracecore.v1.waste.collect";
const WST_ACKNOWLEDGE = "tracecore.v1.waste.acknowledge";

class WasteCollect {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.rows = 0;
		this.offline = false;
		this.busy = null;
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.catalog = null;
		this.done = null; // phiếu vừa ghi sổ
		this.acknowledged = false;
		this.notice = null;
		this.errors = {};
		this.form = this.blankForm();
		this.updatePlaceholder();
		station.listen(this.result, "input", (event) => this.onInput(event));
		station.listen(this.result, "change", (event) => this.onInput(event));
	}

	blankForm() {
		return {
			card: null, // thẻ người giao chỉ giữ trong bộ nhớ, không dựng vào màn
			giver: null,
			total_mode: false,
			total_kg: "",
			note: "",
			lines: [this.blankLine()],
		};
	}

	blankLine(type = "") {
		this.rows += 1;
		return {
			id: String(this.rows),
			waste_type: type,
			qty: "",
			weight: "",
			source: "",
			confirmed: false,
			misclassified: false,
			misclass_note: "",
		};
	}

	get dialogOpen() {
		return false;
	}

	// Hết phiên trạm (rút thẻ, idle 10 phút, đổi người): xóa biểu mẫu, thẻ người giao và yêu cầu dở của người trước
	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.catalog = null;
		this.done = null;
		this.acknowledged = false;
		this.notice = null;
		this.errors = {};
		this.form = this.blankForm();
		this.updatePlaceholder();
	}

	updatePlaceholder() {
		let text = __("Type or scan a waste type name to add a line...");
		if (this.done && !this.acknowledged) text = __("Scan the ward card to acknowledge...");
		else if (!this.form.giver) text = __("Scan the card of the ward staff...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	typeInfo(name) {
		return ((this.catalog && this.catalog.types) || []).find((row) => row.name === name);
	}

	// ---- quét: thẻ người giao → loại chất thải; sau khi ghi sổ là thẻ xác nhận biên nhận ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.done) return this.acknowledge(raw);
		if (!this.form.giver) return this.scanGiver(raw);
		return this.scanType(raw);
	}

	scanGiver(card) {
		this.notice = null;
		return this.request(WST_GIVER, { station: this.station.station, card }, (res) => {
			this.form.card = card;
			this.form.giver = res.giver;
			this.show();
		});
	}

	acknowledge(card) {
		if (this.acknowledged) return this.station.focus();
		this.notice = null;
		return this.request(
			WST_ACKNOWLEDGE,
			{ station: this.station.station, collection: this.done.name, card },
			() => {
				this.acknowledged = true;
				this.show();
			}
		);
	}

	scanType(raw) {
		const wanted = raw.toLowerCase();
		const types = (this.catalog && this.catalog.types) || [];
		const starts = types.filter((row) => row.name.toLowerCase().startsWith(wanted));
		const found =
			types.find((row) => row.name.toLowerCase() === wanted) ||
			(starts.length === 1 ? starts[0] : null);
		if (!found) {
			this.notice = {
				variant: "error",
				title: __("Waste type not found"),
				reason: __("No waste type in use is called {0}.", [raw]),
				action: __("Choose the waste type from the list on the line."),
			};
			return this.show();
		}
		this.notice = null;
		let line = this.form.lines.find((row) => !row.waste_type && !row.qty && !row.weight);
		if (line) line.waste_type = found.name;
		else {
			line = this.blankLine(found.name);
			this.form.lines.push(line);
		}
		this.show();
		this.focusField(line, "qty");
	}

	focusField(line, field) {
		if (!line) return;
		const box = this.result.querySelector(`[data-field="${field}"][data-row="${line.id}"]`);
		if (box) box.focus();
	}

	// ---- gõ vào form: cập nhật trạng thái, không dựng lại cả màn (giữ con trỏ) ----
	onInput(event) {
		const target = event.target;
		const field = target && target.dataset && target.dataset.field;
		if (!field || !this.station.session) return;
		const line = this.form.lines.find((row) => row.id === target.dataset.row);
		if (field === "note") this.form.note = target.value;
		else if (field === "total_kg") this.form.total_kg = target.value;
		else if (line) this.onLineInput(event, line, field, target);
	}

	onLineInput(event, line, field, target) {
		if (field === "waste_type") {
			line.waste_type = target.value;
			this.refreshColor(line);
		} else if (field === "qty") line.qty = target.value;
		else if (field === "misclass_note") line.misclass_note = target.value;
		else if (field === "confirmed") line.confirmed = target.checked;
		else if (field === "misclassified") {
			line.misclassified = target.checked;
			if (event.type === "change") this.show();
		} else if (field === "weight_kg") {
			line.weight = target.value;
			// gõ lại kg thì không còn là số của cân: nhập tay, phải xác nhận lại
			line.source = target.value.trim() ? "Manual" : "";
			line.confirmed = false;
			delete (this.errors[line.id] || {}).weight;
			this.refreshWeigh(line);
		}
	}

	refreshColor(line) {
		const box = this.result.querySelector(`[data-color="${line.id}"]`);
		if (box) box.innerHTML = this.colorHtml(line);
	}

	weighState(line) {
		return {
			kg: line.weight,
			source: line.source,
			confirmed: line.confirmed,
			error: (this.errors[line.id] || {}).weight,
		};
	}

	// Nhãn nguồn, ô xác nhận và lỗi của dòng cân cập nhật tại chỗ để ô kg không mất focus
	refreshWeigh(line) {
		TcWeighLine.sync(
			this.result.querySelector(`[data-weigh="${line.id}"] .tc-weigh`),
			this.weighState(line)
		);
	}

	// ---- gọi RPC ----
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
		const started = performance.now();
		try {
			response = await this.station.rpc(
				method,
				{ ...args, client_ts: pending.ts },
				pending.key
			);
		} catch (error) {
			failure = error;
		}
		// phiên đã kết thúc hoặc đổi người trong lúc chờ: clearSession đã xóa màn, bỏ câu trả lời cũ
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		if (!failure) {
			this.pending = null;
			this.result.dataset.ms = String(Math.round(performance.now() - started));
		}
		this.busy = null;
		if (!failure) this.markOnline();
		if (failure) this.failure(failure);
		else if (response && response.ok === false) this.reject(response.error);
		else onOk(response);
		this.station.focus();
	}

	markOnline() {
		if (!this.offline) return;
		this.offline = false;
		this.station.manualOffline = false;
		this.station.banner.hidden = true;
		this.station.root.dataset.offline = "0";
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
				reason: __("This account cannot record waste collections at this station."),
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

	reject(error) {
		this.notice = { variant: "error", ...error };
		this.show();
	}

	loadCatalog() {
		if (this.busy) return;
		this.request(WST_CATALOG, { station: this.station.station }, (res) => {
			this.catalog = { types: res.types || [] };
			this.show();
		});
	}

	// ---- thao tác trên màn ----
	onAction(action, button) {
		const handlers = {
			retry: () => this.retry(),
			"add-line": () => this.addLine(),
			"remove-line": () => this.removeLine(button.dataset.row),
			weigh: () => this.weigh(button.dataset.row),
			"toggle-total": () => this.toggleTotal(),
			"change-giver": () => this.changeGiver(),
			record: () => this.record(),
			"new-collection": () => this.newCollection(),
			print: () => this.print(),
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	addLine() {
		this.form.lines.push(this.blankLine());
		this.show();
		this.focusField(this.form.lines[this.form.lines.length - 1], "waste_type");
	}

	removeLine(id) {
		if (this.form.lines.length > 1)
			this.form.lines = this.form.lines.filter((line) => line.id !== id);
		else this.form.lines = [this.blankLine()];
		delete this.errors[id];
		this.show();
	}

	toggleTotal() {
		this.form.total_mode = !this.form.total_mode;
		this.show();
	}

	changeGiver() {
		this.form.card = null;
		this.form.giver = null;
		this.notice = null;
		this.show();
	}

	// Lấy cân: agent trả kg thì điền ô kg, nguồn Cân; không phản hồi thì báo và để nhập tay có xác nhận
	async weigh(id) {
		const line = this.form.lines.find((row) => row.id === id);
		if (!line || this.weighing) return;
		this.weighing = true;
		const reading = await TcWeighLine.read();
		this.weighing = false;
		if (!this.station.session) return;
		if (reading.ok) {
			line.weight = TcWeighLine.format(reading.kg);
			line.source = "Scale";
			line.confirmed = false;
			this.notice = null;
			delete this.errors[id];
		} else {
			this.notice = {
				variant: "warn",
				title: __("The scale did not answer"),
				reason: __("The station agent could not read the scale in 2 seconds."),
				action: __("Type the weight by hand and tick the confirmation."),
			};
		}
		this.show();
		this.focusField(line, "weight_kg");
	}

	newCollection() {
		this.done = null;
		this.acknowledged = false;
		this.notice = null;
		this.errors = {};
		this.form = this.blankForm();
		this.show();
	}

	print() {
		if (!this.done) return;
		const query = new URLSearchParams({
			doctype: "Waste Collection",
			name: this.done.name,
			format: "TC Waste Receipt",
			trigger_print: "1",
			no_letterhead: "1",
		});
		window.open(`/printview?${query}`, "_blank", "noopener");
	}

	// ---- kiểm tra trước khi gửi và ghi sổ ----
	filled() {
		return this.form.lines.filter((line) => line.waste_type || line.qty || line.weight);
	}

	problems() {
		const items = [];
		const errors = {};
		const filled = this.filled();
		if (!filled.length) items.push(__("Add at least one waste type with its bags."));
		const total = TcWeighLine.parse(this.form.total_kg);
		if (this.form.total_mode && (total == null || total <= 0))
			items.push(__("Enter the total weight of the cart."));
		for (const line of filled) {
			if (!this.typeInfo(line.waste_type)) {
				items.push(__("Choose a waste type for every line."));
				continue;
			}
			const qty = Number(line.qty);
			if (!Number.isInteger(qty) || qty <= 0)
				items.push(__("Enter the bags of {0}.", [line.waste_type]));
			if (
				!this.form.total_mode &&
				line.source === "Manual" &&
				TcWeighLine.parse(line.weight) != null &&
				!line.confirmed
			) {
				errors[line.id] = { weight: __("Tick to confirm the typed weight.") };
				items.push(__("Confirm the typed weight of {0}.", [line.waste_type]));
			}
			if (line.misclassified && !line.misclass_note.trim())
				items.push(__("Describe what is misclassified in {0}.", [line.waste_type]));
		}
		this.errors = errors;
		return items;
	}

	payload() {
		const lines = this.filled().map((line) => {
			const row = { waste_type: line.waste_type, qty: Number(line.qty) };
			const weight = TcWeighLine.parse(line.weight);
			if (!this.form.total_mode && weight != null) {
				row.weight_kg = weight;
				row.weight_source = line.source === "Scale" ? "Scale" : "Manual";
				row.weight_confirmed = line.confirmed ? 1 : 0;
			}
			if (line.misclassified) {
				row.misclassified = 1;
				row.misclass_note = line.misclass_note.trim();
			}
			return row;
		});
		const args = { station: this.station.station, card: this.form.card, lines };
		if (this.form.note.trim()) args.note = this.form.note.trim();
		if (this.form.total_mode) args.total_kg = TcWeighLine.parse(this.form.total_kg);
		return args;
	}

	record() {
		const items = this.problems();
		if (items.length) {
			this.notice = {
				variant: "error",
				title: __("The collection is not complete"),
				reason: __("Some required values are missing or need confirmation."),
				items,
				action: __("Fix the highlighted values, then record again."),
			};
			return this.show();
		}
		this.notice = null;
		this.request(WST_COLLECT, this.payload(), (res) => {
			this.done = res.collection;
			this.acknowledged = false;
			this.form = this.blankForm();
			this.errors = {};
			this.notice = res.collection.label_warning
				? { variant: "warn", ...res.collection.label_warning }
				: null;
			this.show();
		});
	}

	// ---- trạng thái mạng ----
	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		if (this.offline) {
			return this.station.setState("offline", this.offlineHtml());
		}
		if (!this.catalog && !this.notice && !this.busy) {
			this.loadCatalog();
			return this.station.renderLoading();
		}
		const failed = this.notice && this.notice.variant === "error";
		const state = failed
			? "error"
			: this.catalog && !this.catalog.types.length
			? "empty"
			: "result";
		this.station.setState(
			state,
			`<div class="tc-linen tc-waste">
				${typeof wasteTabs === "function" ? wasteTabs("collect") : ""}
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.done ? this.doneHtml() : this.catalog ? this.formHtml() : ""}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
		if (!this.done && this.catalog && this.form.giver)
			this.form.lines.forEach((line) => this.refreshWeigh(line));
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		const items = (notice.items || []).map((item) => `<li>${esc(item)}</li>`).join("");
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(tcErrorTitle(notice))}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${items ? `<ul class="tc-alert-items">${items}</ul>` : ""}
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
			<button type="button" class="tc-btn tc-btn-secondary" data-action="offline">${esc(
				__("Switch to offline")
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
				reason: __("Recording waste collections needs a network connection."),
				action: __("Retry when the connection returns."),
			},
			`<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
					__("Retry")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
					__("Call R02")
				)}</button>
			</div>`
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
		if (this.catalog && !this.catalog.types.length) {
			html += this.alertHtml({
				variant: "info",
				title: __("No waste types yet"),
				reason: __("The catalogue has no waste type in use."),
				action: __("Ask R02 to add waste types in the Waste Type list."),
			});
		}
		return html;
	}

	formHtml() {
		if (!this.catalog.types.length) return "";
		if (!this.form.giver) {
			return `<section class="tc-t6-block">
				<p class="tc-t6-hint">${esc(
					__("Scan the employee card of the person handing over the waste.")
				)}</p>
			</section>`;
		}
		const giver = this.form.giver;
		return `<section class="tc-t6-block" aria-label="${esc(__("Waste collection"))}">
			<div class="tc-linen-head">
				<p><strong>${esc(__("Delivered By"))}:</strong> ${esc(giver.employee_name)}</p>
				<p><strong>${esc(__("Department"))}:</strong> ${esc(giver.department)}</p>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="change-giver">${esc(
					__("Scan another card")
				)}</button>
			</div>
			<label class="tc-linen-mode"><input type="checkbox" data-action="toggle-total"${
				this.form.total_mode ? " checked" : ""
			}> ${esc(__("Only the total weight of the cart is known"))}</label>
			${this.form.total_mode ? this.totalHtml() : ""}
			<div class="tc-linen-lines">${this.form.lines.map((line) => this.lineHtml(line)).join("")}</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-secondary" data-action="add-line">${esc(
					__("Add a line")
				)}</button>
			</div>
			<div class="tc-field">
				<label for="tc-wst-note">${esc(__("Note"))}</label>
				<textarea id="tc-wst-note" rows="2" data-field="note">${esc(this.form.note)}</textarea>
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="record"${
					this.busy ? " disabled" : ""
				}>${esc(__("Record collection"))}</button>
			</div>
		</section>`;
	}

	totalHtml() {
		return `<div class="tc-field">
			<label for="tc-wst-total">${esc(__("Total weight of the cart (kg)"))} *</label>
			<input id="tc-wst-total" type="text" inputmode="decimal" autocomplete="off" data-field="total_kg" value="${esc(
				this.form.total_kg
			)}">
			<p class="tc-t6-hint">${esc(
				__("The weight is shared between the lines by the standard weight.")
			)}</p>
		</div>`;
	}

	// Mã màu luôn là chữ cỡ lớn, không chỉ bằng màu; palette không có màu riêng cho từng nhóm TT 20/2021
	colorHtml(line) {
		const info = this.typeInfo(line.waste_type);
		return info
			? `<span class="tc-waste-color">${esc(__(info.color_code, null, "Waste Type"))}</span>`
			: "";
	}

	lineHtml(line) {
		const id = esc(line.id);
		const options = this.catalog.types
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						line.waste_type === row.name ? " selected" : ""
					}>${esc(row.name)}</option>`
			)
			.join("");
		return `<div class="tc-linen-line" data-line="${id}">
			<div class="tc-field">
				<label for="tc-wst-type-${id}">${esc(__("Waste Type"))}</label>
				<select id="tc-wst-type-${id}" data-field="waste_type" data-row="${id}">
					<option value="">${esc(__("Choose the waste type"))}</option>${options}
				</select>
			</div>
			<div data-color="${id}">${this.colorHtml(line)}</div>
			<div class="tc-field">
				<label for="tc-wst-qty-${id}">${esc(__("Bags or Bins"))}</label>
				<input id="tc-wst-qty-${id}" type="text" inputmode="numeric" autocomplete="off"
					data-field="qty" data-row="${id}" value="${esc(line.qty)}">
			</div>
			<div data-weigh="${id}"${this.form.total_mode ? " hidden" : ""}>${TcWeighLine.html(
			line.id,
			this.weighState(line)
		)}</div>
			<label class="tc-linen-flag"><input type="checkbox" data-field="misclassified" data-row="${id}"${
			line.misclassified ? " checked" : ""
		}> ${esc(__("Misclassified"))}</label>
			${
				line.misclassified
					? `<div class="tc-field">
				<label for="tc-wst-mnote-${id}">${esc(__("Misclassification Note"))} *</label>
				<textarea id="tc-wst-mnote-${id}" rows="2" data-field="misclass_note" data-row="${id}">${esc(
							line.misclass_note
					  )}</textarea>
			</div>`
					: ""
			}
			<button type="button" class="tc-btn tc-btn-secondary" data-action="remove-line" data-row="${id}">${esc(
			__("Remove line")
		)}</button>
		</div>`;
	}

	doneHtml() {
		const done = this.done;
		const rows = done.containers
			.map(
				(row) => `<tr>
				<td class="tc-mono">${esc(row.name)}</td>
				<td>${esc(row.waste_type)}</td>
				<td>${esc(TcWeighLine.format(row.weight_kg))}</td>
				<td>${esc(row.status === "Held" ? __("On hold") : __("Collected"))}</td>
			</tr>`
			)
			.join("");
		return `<section class="tc-t6-block">
			${this.alertHtml({
				variant: "ok",
				title: __("Collection {0} recorded", [done.name]),
				reason: __("{0} bags, {1} kg from {2}.", [
					done.total_containers,
					TcWeighLine.format(done.total_weight_kg),
					done.department,
				]),
				action: this.acknowledged
					? __("The ward acknowledged this collection.")
					: __("Ask the ward staff to scan their card, then print the receipt."),
			})}
			<table class="tc-t6-table">
				<thead><tr>
					<th scope="col">${esc(__("Container Code"))}</th>
					<th scope="col">${esc(__("Waste Type"))}</th>
					<th scope="col">${esc(__("Weight (kg)"))}</th>
					<th scope="col">${esc(__("Status"))}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="print">${esc(
					__("Print receipt")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="new-collection">${esc(
					__("New collection")
				)}</button>
			</div>
		</section>`;
	}
}
