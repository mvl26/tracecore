/* global uuid4, clientTs, esc, TcWeighLine */
// Màn thu gom đồ vải theo khoa (SCR-16, FEAT-033, UC-16) trên Page station, trạm bước LIN.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// Một form chứng từ: chọn khoa, nhập người giao, thêm dòng loại đồ vải (số chiếc, kg từ cân hoặc nhập tay có xác nhận,
// nhiễm/không nhiễm), rồi Ghi sổ. Ô quét luôn ở đầu: gõ hoặc quét tên loại đồ vải để thêm dòng. Lỗi chặn = alert-error
// inline (kết quả → lý do → hành động). Không offline: mất mạng thì báo và không ghi (A-49 L8).

const LIN_CATALOG = "tracecore.v1.linen.catalog";
const LIN_COLLECT = "tracecore.v1.linen.collect";
const LIN_TOLERANCE = 0.15; // FR-M3-01.4: lệch quá 15 % so với kg quy đổi thì cần ghi chú

class LinenCollect {
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
		this.notice = null;
		this.errors = {}; // lỗi kiểm tra ở dòng: {rowId: {weight, note}}
		this.form = this.blankForm();
		this.updatePlaceholder();
		station.listen(this.result, "input", (event) => this.onInput(event));
		station.listen(this.result, "change", (event) => this.onInput(event));
	}

	blankForm() {
		return {
			department: "",
			delivered_by: "",
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
			linen_type: type,
			qty: "",
			weight: "",
			source: "",
			confirmed: false,
			contaminated: true,
			variance_note: "",
		};
	}

	get dialogOpen() {
		return false;
	}

	// Hết phiên trạm (rút thẻ, idle 10 phút, đổi người): xóa biểu mẫu và yêu cầu dở của người trước
	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.catalog = null;
		this.done = null;
		this.notice = null;
		this.errors = {};
		this.form = this.blankForm();
		this.updatePlaceholder();
	}

	updatePlaceholder() {
		const text = __("Type or scan a linen type name to add a line...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	typeInfo(name) {
		return ((this.catalog && this.catalog.types) || []).find((row) => row.name === name);
	}

	// ---- quét: tên loại đồ vải thêm một dòng ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		const wanted = raw.toLowerCase();
		const types = (this.catalog && this.catalog.types) || [];
		const found =
			types.find((row) => row.name.toLowerCase() === wanted) ||
			(types.filter((row) => row.name.toLowerCase().startsWith(wanted)).length === 1
				? types.find((row) => row.name.toLowerCase().startsWith(wanted))
				: null);
		this.done = null;
		if (!found) {
			this.notice = {
				variant: "error",
				title: __("Linen type not found"),
				reason: __("No linen type in use is called {0}.", [raw]),
				action: __("Choose the linen type from the list on the line."),
			};
			return this.show();
		}
		this.notice = null;
		const blank = this.form.lines.find(
			(line) => !line.linen_type && !line.qty && !line.weight
		);
		if (blank) blank.linen_type = found.name;
		else this.form.lines.push(this.blankLine(found.name));
		this.show();
		this.focusField(
			this.form.lines.find((line) => line.linen_type === found.name && !line.qty),
			"qty"
		);
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
		const checkbox = target.type === "checkbox";
		if (field === "department") this.form.department = target.value;
		else if (field === "delivered_by") this.form.delivered_by = target.value;
		else if (field === "note") this.form.note = target.value;
		else if (field === "total_kg") this.form.total_kg = target.value;
		else if (line)
			this.onLineInput(event, line, field, checkbox ? target.checked : target.value);
	}

	onLineInput(event, line, field, value) {
		if (field === "contaminated") line.contaminated = Boolean(value);
		else if (field === "confirmed") line.confirmed = Boolean(value);
		else if (field === "variance_note") line.variance_note = value;
		else if (field === "linen_type") {
			line.linen_type = value;
			this.refreshHint(line);
		} else if (field === "qty") {
			line.qty = value;
			this.refreshHint(line);
		} else if (field === "weight_kg") {
			line.weight = value;
			// gõ lại kg thì không còn là số của cân: nhập tay, phải xác nhận lại
			line.source = value.trim() ? "Manual" : "";
			line.confirmed = false;
			delete (this.errors[line.id] || {}).weight;
			this.refreshHint(line);
			this.refreshWeigh(line);
		}
	}

	// Gợi ý quy đổi và ô ghi chú lệch của một dòng, dựng lại riêng vùng đó khi số đổi
	refreshHint(line) {
		const box = this.result.querySelector(`[data-hint="${line.id}"]`);
		if (box) box.innerHTML = this.hintHtml(line);
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

	// ---- số liệu một dòng ----
	numbers(line) {
		const info = this.typeInfo(line.linen_type);
		const qty = line.qty === "" ? null : Number(line.qty);
		const weight = TcWeighLine.parse(line.weight);
		return { info, qty: Number.isFinite(qty) ? qty : null, weight };
	}

	// Độ lệch tương đối giữa kg nhập và kg quy đổi, hoặc null khi chưa đủ hai số
	variance(line) {
		const { info, qty, weight } = this.numbers(line);
		if (!info || !qty || qty <= 0 || weight == null) return null;
		const expected = qty * info.std_weight_kg;
		return Math.abs(weight - expected) / expected;
	}

	overTolerance(line) {
		if (this.form.total_mode) return false; // chia cân tổng: lệch chung cả xe, ghi chú ở ô ghi chú phiếu
		const variance = this.variance(line);
		return variance != null && Math.round(variance * 1e9) / 1e9 > LIN_TOLERANCE;
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
				reason: __("This account cannot record linen collections at this station."),
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
		this.request(LIN_CATALOG, { station: this.station.station }, (res) => {
			this.catalog = { types: res.types || [], departments: res.departments || [] };
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
		this.focusField(this.form.lines[this.form.lines.length - 1], "linen_type");
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
		this.notice = null;
		this.errors = {};
		this.form = this.blankForm();
		this.show();
	}

	print() {
		if (!this.done) return;
		const query = new URLSearchParams({
			doctype: "Linen Collection",
			name: this.done.collection,
			format: "TC Linen Receipt",
			trigger_print: "1",
			no_letterhead: "1",
		});
		window.open(`/printview?${query}`, "_blank", "noopener");
	}

	// ---- kiểm tra trước khi gửi và ghi sổ ----
	problems() {
		const items = [];
		const errors = {};
		if (!this.form.department) items.push(__("Choose the department."));
		if (!this.form.delivered_by.trim())
			items.push(__("Type the name of the person who hands the linen over."));
		const filled = this.form.lines.filter(
			(line) => line.linen_type || line.qty || line.weight
		);
		if (!filled.length) items.push(__("Add at least one linen type with pieces or weight."));
		const total = TcWeighLine.parse(this.form.total_kg);
		if (this.form.total_mode && (total == null || total <= 0))
			items.push(__("Enter the total weight of the cart."));
		for (const line of filled) {
			const { qty, weight } = this.numbers(line);
			const where = this.typeInfo(line.linen_type)
				? line.linen_type
				: __("a line without a linen type");
			if (!this.typeInfo(line.linen_type)) {
				items.push(__("Choose a linen type for {0}.", [where]));
				continue;
			}
			if (this.form.total_mode) {
				if (!qty || qty <= 0) items.push(__("Enter the pieces of {0}.", [where]));
				continue;
			}
			if ((!qty || qty <= 0) && weight == null) {
				items.push(__("Enter the pieces or the weight of {0}.", [where]));
			} else if (line.source === "Manual" && weight != null && !line.confirmed) {
				errors[line.id] = { weight: __("Tick to confirm the typed weight.") };
				items.push(__("Confirm the typed weight of {0}.", [where]));
			}
			if (this.overTolerance(line) && !line.variance_note.trim()) {
				errors[line.id] = { ...(errors[line.id] || {}), note: __("Required") };
				items.push(
					__("{0}: the weight differs by more than 15 %, enter a note.", [where])
				);
			}
		}
		this.errors = errors;
		return items;
	}

	payload() {
		const filled = this.form.lines.filter(
			(line) => line.linen_type || line.qty || line.weight
		);
		const lines = filled.map((line) => {
			const { qty, weight } = this.numbers(line);
			const row = { linen_type: line.linen_type, contaminated: line.contaminated ? 1 : 0 };
			if (qty != null && qty > 0) row.qty = qty;
			if (!this.form.total_mode && weight != null) {
				row.weight_kg = weight;
				row.weight_source = line.source === "Scale" ? "Scale" : "Manual";
			}
			if (line.variance_note.trim()) row.variance_note = line.variance_note.trim();
			return row;
		});
		const args = {
			station: this.station.station,
			department: this.form.department,
			delivered_by: this.form.delivered_by.trim(),
			lines,
		};
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
		this.request(LIN_COLLECT, this.payload(), (res) => {
			this.done = res.collection;
			this.form = this.blankForm();
			this.errors = {};
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
			`<div class="tc-linen">
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.done ? this.doneHtml() : this.catalog ? this.formHtml() : ""}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
		if (!this.done && this.catalog) this.form.lines.forEach((line) => this.refreshWeigh(line));
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		const items = (notice.items || []).map((item) => `<li>${esc(item)}</li>`).join("");
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(notice.title)}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${items ? `<ul class="tc-alert-items">${items}</ul>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
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
				reason: __("Recording linen collections needs a network connection."),
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
				title: __("No linen types yet"),
				reason: __("The catalogue has no linen type in use."),
				action: __("Ask R02 to add linen types in the Linen Type list."),
			});
		}
		return html;
	}

	formHtml() {
		if (!this.catalog.types.length) return "";
		const departments = this.catalog.departments
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						this.form.department === row.name ? " selected" : ""
					}>${esc(row.department_name || row.name)}</option>`
			)
			.join("");
		return `<section class="tc-t6-block" aria-label="${esc(__("Linen collection"))}">
			<div class="tc-linen-head">
				<div class="tc-field">
					<label for="tc-lin-department">${esc(__("Department"))} *</label>
					<select id="tc-lin-department" data-field="department">
						<option value="">${esc(__("Choose the department"))}</option>${departments}
					</select>
				</div>
				<div class="tc-field">
					<label for="tc-lin-deliverer">${esc(__("Delivered By"))} *</label>
					<input id="tc-lin-deliverer" type="text" autocomplete="off" data-field="delivered_by" value="${esc(
						this.form.delivered_by
					)}">
				</div>
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
				<label for="tc-lin-note">${esc(__("Note"))}</label>
				<textarea id="tc-lin-note" rows="2" data-field="note">${esc(this.form.note)}</textarea>
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
			<label for="tc-lin-total">${esc(__("Total weight of the cart (kg)"))} *</label>
			<input id="tc-lin-total" type="text" inputmode="decimal" autocomplete="off" data-field="total_kg" value="${esc(
				this.form.total_kg
			)}">
			<p class="tc-t6-hint">${esc(
				__("The weight is shared between the lines by the standard weight.")
			)}</p>
		</div>`;
	}

	lineHtml(line) {
		const errors = this.errors[line.id] || {};
		const options = this.catalog.types
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						line.linen_type === row.name ? " selected" : ""
					}>${esc(row.name)}</option>`
			)
			.join("");
		return `<div class="tc-linen-line" data-line="${esc(line.id)}">
			<div class="tc-field">
				<label for="tc-lin-type-${esc(line.id)}">${esc(__("Linen Type"))}</label>
				<select id="tc-lin-type-${esc(line.id)}" data-field="linen_type" data-row="${esc(line.id)}">
					<option value="">${esc(__("Choose the linen type"))}</option>${options}
				</select>
			</div>
			<div class="tc-field">
				<label for="tc-lin-qty-${esc(line.id)}">${esc(__("Pieces"))}</label>
				<input id="tc-lin-qty-${esc(line.id)}" type="text" inputmode="numeric" autocomplete="off"
					data-field="qty" data-row="${esc(line.id)}" value="${esc(line.qty)}">
			</div>
			<div data-weigh="${esc(line.id)}"${this.form.total_mode ? " hidden" : ""}>${this.weighHtml(
			line
		)}</div>
			<label class="tc-linen-flag"><input type="checkbox" data-field="contaminated" data-row="${esc(
				line.id
			)}"${line.contaminated ? " checked" : ""}> ${esc(__("Contaminated"))}</label>
			<div class="tc-linen-hint" data-hint="${esc(line.id)}">${this.hintHtml(line, errors)}</div>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="remove-line" data-row="${esc(
				line.id
			)}">${esc(__("Remove line"))}</button>
		</div>`;
	}

	weighHtml(line) {
		return TcWeighLine.html(line.id, this.weighState(line));
	}

	// Quy đổi khi chỉ có một số, cảnh báo và ô ghi chú khi lệch quá 15 %
	hintHtml(line, errors = this.errors[line.id] || {}) {
		const { info, qty, weight } = this.numbers(line);
		if (!info) return "";
		let html = "";
		if (!this.form.total_mode && qty && weight == null) {
			html += `<p class="tc-t6-hint">${esc(
				__("Converted weight: {0} kg", [TcWeighLine.format(qty * info.std_weight_kg)])
			)}</p>`;
		} else if (!this.form.total_mode && !qty && weight != null) {
			html += `<p class="tc-t6-hint">${esc(
				__("Converted pieces: {0}", [Math.round(weight / info.std_weight_kg)])
			)}</p>`;
		}
		if (this.overTolerance(line)) {
			const percent = Math.round(this.variance(line) * 100);
			html += `<div class="tc-alert tc-alert-warn" role="status">
				<p class="tc-alert-title"><span aria-hidden="true">!</span> ${esc(
					__("The weight differs from the standard by {0} %", [percent])
				)}</p>
				<div class="tc-field">
					<label for="tc-lin-vnote-${esc(line.id)}">${esc(__("Variance Note"))} *</label>
					<textarea id="tc-lin-vnote-${esc(line.id)}" rows="2" data-field="variance_note" data-row="${esc(
				line.id
			)}"${errors.note ? ' class="is-error"' : ""}>${esc(line.variance_note)}</textarea>
					${errors.note ? `<p class="tc-field-error">${esc(errors.note)}</p>` : ""}
				</div>
			</div>`;
		}
		return html;
	}

	doneHtml() {
		const done = this.done;
		const rows = done.lines
			.map(
				(row) => `<tr>
				<td>${esc(row.linen_type)}</td>
				<td>${esc(row.qty)}</td>
				<td>${esc(TcWeighLine.format(row.weight_kg))}</td>
				<td>${esc(row.contaminated ? __("Contaminated") : __("Clean"))}</td>
				<td>${esc(TcWeighLine.sourceLabel(row.weight_source))}</td>
			</tr>`
			)
			.join("");
		return `<section class="tc-t6-block">
			${this.alertHtml({
				variant: "ok",
				title: __("Collection {0} recorded", [done.collection]),
				reason: __("{0} pieces, {1} kg from {2}.", [
					done.total_qty,
					TcWeighLine.format(done.total_weight_kg),
					done.department,
				]),
				action: __("Print the receipt for the person who delivered the linen."),
			})}
			<table class="tc-t6-table">
				<thead><tr>
					<th scope="col">${esc(__("Linen Type"))}</th>
					<th scope="col">${esc(__("Pieces"))}</th>
					<th scope="col">${esc(__("Weight (kg)"))}</th>
					<th scope="col">${esc(__("Contaminated"))}</th>
					<th scope="col">${esc(__("Weight Source"))}</th>
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
