/* global uuid4, clientTs, esc, TcWeighLine, LinenCollect, LinenIssue */
// Màn lô giặt theo kg (SCR-17, FEAT-034, UC-17) trên Page station, trạm bước LIN, cạnh màn thu gom đồ vải.
// Frappe nối file này sau station_linen.js (hook page_js) nên dùng chung uuid4/clientTs/esc và LinenCollect.
// Hai bước: Bắt đầu lô (máy giặt, chương trình, nhiễm/không, kg, hóa chất) rồi Hoàn tất (máy sấy, nhiệt độ, thời gian, kết quả
// sạch/khô); hoàn tất trừ hóa chất và hiện chi phí/kg ngay. Lô Không đạt có nút Giặt lại (liên kết lô cũ). Lỗi chặn = alert-error
// inline (kết quả → lý do → hành động). Không offline: mất mạng thì báo và không ghi (A-50 D13).

const LAU_CONTEXT = "tracecore.v1.laundry.context";
const LAU_START = "tracecore.v1.laundry.start";
const LAU_COMPLETE = "tracecore.v1.laundry.complete";
const LAU_MIN_CONTAMINATED_C = 71; // FR-M3-03.2: đồ nhiễm giặt dưới 71 °C phải có hóa chất khử khuẩn

// Thanh chuyển giữa thu gom, lô giặt và cấp phát, nằm đầu mỗi màn của trạm đồ vải (xem LinenStation)
function linenTabs(active) {
	const tab = (mode, label) =>
		`<button type="button" class="tc-btn ${
			active === mode ? "tc-btn-primary" : "tc-btn-secondary"
		}" data-action="linen-mode" data-mode="${mode}" aria-pressed="${active === mode}">${esc(
			label
		)}</button>`;
	return `<div class="tc-linen-tabs" role="group" aria-label="${esc(__("Linen station"))}">
		${tab("collect", __("Collection"))}${tab("laundry", __("Laundry batch"))}${tab(
		"issue",
		__("Issue")
	)}
	</div>`;
}

class LaundryBatch {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.offline = false;
		this.busy = null;
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.ctx = null;
		this.mode = "start"; // start | finish | done
		this.done = null;
		this.notice = null;
		this.form = this.blankForm();
		this.finish = this.blankFinish("");
		station.listen(this.result, "input", (event) => this.onInput(event));
		station.listen(this.result, "change", (event) => this.onInput(event));
	}

	blankForm(redo = null) {
		return {
			batch_type: "In-house",
			equipment: "",
			program: "",
			contaminated: redo ? redo.contaminated : true,
			kg: redo ? TcWeighLine.format(redo.weight_kg) : "",
			vendor: "",
			price: "",
			redo_of: redo ? redo.name : "",
			chemicals: [],
			note: "",
		};
	}

	blankFinish(batch) {
		return {
			batch,
			dryer: "",
			dry_temp: "",
			dry_minutes: "",
			clean_ok: "",
			dry_ok: "",
			note: "",
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
		this.ctx = null;
		this.mode = "start";
		this.done = null;
		this.notice = null;
		this.form = this.blankForm();
		this.finish = this.blankFinish("");
	}

	updatePlaceholder() {
		const text = __("Type or scan the machine code to choose it...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	// ---- dữ liệu chọn ----
	washers() {
		return (this.ctx && this.ctx.washers) || [];
	}

	programsOf(equipment) {
		return ((this.ctx && this.ctx.programs) || []).filter(
			(row) => row.equipment === equipment
		);
	}

	programInfo() {
		return ((this.ctx && this.ctx.programs) || []).find(
			(row) => row.name === this.form.program
		);
	}

	chemicalInfo(item) {
		return ((this.ctx && this.ctx.chemicals) || []).find((row) => row.name === item);
	}

	// Có hóa chất khử khuẩn trong dòng đã chọn hoặc trong định mức của chương trình (cùng luật với máy chủ)
	hasDisinfectant() {
		const items = this.form.chemicals.map((row) => row.item).filter(Boolean);
		const program = this.programInfo();
		if (program) items.push(...(program.norms || []).map((norm) => norm.item));
		return items.some((item) => {
			const info = this.chemicalInfo(item);
			return info && info.tc_is_disinfectant;
		});
	}

	// ---- quét: mã hoặc tên máy giặt/sấy chọn máy ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		const wanted = raw.toLowerCase();
		const list = this.mode === "finish" ? (this.ctx && this.ctx.dryers) || [] : this.washers();
		const found = list.find(
			(row) =>
				row.name.toLowerCase() === wanted ||
				(row.equipment_name || "").toLowerCase() === wanted
		);
		if (!found) {
			this.notice = {
				variant: "error",
				title: __("Machine not found"),
				reason: __("No machine that is ready is called {0}.", [raw]),
				action: __("Choose the machine from the list."),
			};
			return this.show();
		}
		this.notice = null;
		if (this.mode === "finish") this.finish.dryer = found.name;
		else this.selectWasher(found.name);
		this.show();
	}

	selectWasher(name) {
		this.form.equipment = name;
		const programs = this.programsOf(name);
		this.form.program = programs.length === 1 ? programs[0].name : "";
	}

	// ---- gõ vào form: cập nhật trạng thái, không dựng lại cả màn (giữ con trỏ) ----
	onInput(event) {
		const target = event.target;
		const field = target && target.dataset && target.dataset.lf;
		if (!field || !this.station.session) return;
		const value = target.value;
		const row = this.form.chemicals[Number(target.dataset.row)];
		if (field === "batch_type") {
			this.form.batch_type = value;
			return this.show();
		}
		if (field === "equipment") {
			this.selectWasher(value);
			return this.show();
		}
		if (field === "program") this.form.program = value;
		else if (field === "contaminated") this.form.contaminated = value === "1";
		else if (field === "kg") this.form.kg = value;
		else if (field === "vendor") this.form.vendor = value;
		else if (field === "price") this.form.price = value;
		else if (field === "note") this.form.note = value;
		else if (field === "chem_item" && row) row.item = value;
		else if (field === "chem_qty" && row) row.qty = value;
		else if (field.startsWith("fin_")) this.finish[field.slice(4)] = value;
		this.refreshHint();
	}

	// Gợi ý theo chương trình và kg; dựng lại riêng vùng đó khi số đổi
	refreshHint() {
		const box = this.result.querySelector("[data-hint='batch']");
		if (box) box.innerHTML = this.hintHtml();
	}

	// ---- gọi RPC (khuôn request/retry dùng chung với LinenCollect, xem cuối file) ----
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
				reason: __("This account cannot record laundry batches at this station."),
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

	loadContext() {
		if (this.busy) return;
		this.request(LAU_CONTEXT, { station: this.station.station }, (res) => {
			this.ctx = res;
			this.show();
		});
	}

	// ---- thao tác trên màn ----
	onAction(action, button) {
		const handlers = {
			retry: () => this.retry(),
			"add-chemical": () => this.addChemical(),
			"remove-chemical": () => this.removeChemical(Number(button.dataset.row)),
			start: () => this.startBatch(),
			"open-finish": () => this.openFinish(button.dataset.batch),
			back: () => this.backToStart(),
			complete: () => this.completeBatch(),
			"new-batch": () => this.newBatch(),
			redo: () => this.redo(),
		};
		if (!handlers[action]) return false; // offline, call-r02, linen-mode: TraceCoreStation và LinenStation xử lý
		handlers[action]();
		return true;
	}

	addChemical() {
		this.form.chemicals.push({ item: "", qty: "" });
		this.show();
	}

	removeChemical(index) {
		this.form.chemicals.splice(index, 1);
		this.show();
	}

	openFinish(batch) {
		this.mode = "finish";
		this.finish = this.blankFinish(batch);
		this.notice = null;
		this.show();
	}

	backToStart() {
		this.mode = "start";
		this.notice = null;
		this.show();
	}

	newBatch() {
		this.mode = "start";
		this.done = null;
		this.notice = null;
		this.ctx = null; // tải lại để lô vừa xong biến khỏi danh sách đang chạy
		this.form = this.blankForm();
		this.show();
	}

	redo() {
		if (!this.done) return;
		this.form = this.blankForm({
			name: this.done.name,
			contaminated: this.done.contaminated,
			weight_kg: this.done.weight_kg,
		});
		this.mode = "start";
		this.done = null;
		this.ctx = null;
		this.notice = null;
		this.show();
	}

	// ---- kiểm tra trước khi gửi ----
	startProblems() {
		const items = [];
		const form = this.form;
		const kg = TcWeighLine.parse(form.kg);
		if (kg == null || kg <= 0) items.push(__("Enter the weight in kg of the linen."));
		if (form.batch_type === "Outsourced") {
			if (!form.vendor.trim()) items.push(__("Type the name of the vendor."));
			const price = TcWeighLine.parse(form.price);
			if (price == null || price <= 0) items.push(__("Enter the price per kg."));
			return items;
		}
		if (!form.equipment) items.push(__("Choose the washer."));
		else if (!form.program) items.push(__("Choose the program."));
		const washer = this.washers().find((row) => row.name === form.equipment);
		if (washer && washer.capacity_kg && kg != null && kg > washer.capacity_kg)
			items.push(
				__("The load is over the machine capacity of {0} kg.", [washer.capacity_kg])
			);
		const program = this.programInfo();
		if (
			program &&
			form.contaminated &&
			(program.temperature || 0) < LAU_MIN_CONTAMINATED_C &&
			!this.hasDisinfectant()
		)
			items.push(
				__("Contaminated linen below {0} C needs a disinfectant chemical.", [
					LAU_MIN_CONTAMINATED_C,
				])
			);
		form.chemicals.forEach((row, index) => {
			if (row.item && row.qty !== "" && TcWeighLine.parse(row.qty) == null)
				items.push(__("Chemical {0}: enter a quantity of 0 or more.", [index + 1]));
		});
		return items;
	}

	startPayload() {
		const form = this.form;
		const args = {
			station: this.station.station,
			batch_type: form.batch_type,
			loads: [{ kg: TcWeighLine.parse(form.kg), contaminated: form.contaminated ? 1 : 0 }],
		};
		if (form.batch_type === "Outsourced") {
			args.vendor = form.vendor.trim();
			args.price_per_kg = TcWeighLine.parse(form.price);
		} else {
			args.equipment = form.equipment;
			args.program = form.program;
			args.chemicals = form.chemicals
				.filter((row) => row.item)
				.map((row) => ({ item: row.item, qty: TcWeighLine.parse(row.qty) || 0 }));
		}
		if (form.redo_of) args.redo_of = form.redo_of;
		if (form.note.trim()) args.note = form.note.trim();
		return args;
	}

	startBatch() {
		const items = this.startProblems();
		if (items.length) {
			this.notice = {
				variant: "error",
				title: __("The batch is not complete"),
				reason: __("Some required values are missing or not allowed."),
				items,
				action: __("Fix the values, then start the batch again."),
			};
			return this.show();
		}
		this.notice = null;
		this.request(LAU_START, this.startPayload(), (res) => {
			this.notice = {
				variant: "ok",
				title: __("Batch {0} started", [res.batch.name]),
				reason: __("{0} kg is washing.", [TcWeighLine.format(res.batch.weight_kg)]),
				action: __("When the wash and the drying are done, choose Complete."),
			};
			this.form = this.blankForm();
			this.ctx = null;
			this.show();
		});
	}

	runningBatch() {
		return ((this.ctx && this.ctx.running) || []).find(
			(row) => row.name === this.finish.batch
		);
	}

	finishProblems() {
		const items = [];
		const finish = this.finish;
		const batch = this.runningBatch();
		if (batch && batch.batch_type === "In-house") {
			if (!finish.dryer) items.push(__("Choose the dryer."));
			const temp = TcWeighLine.parse(finish.dry_temp);
			const minutes = TcWeighLine.parse(finish.dry_minutes);
			if (!temp || temp <= 0) items.push(__("Enter the drying temperature in C."));
			if (!minutes || minutes <= 0) items.push(__("Enter the drying time in minutes."));
		}
		if (finish.clean_ok === "") items.push(__("Record whether the linen is clean."));
		if (finish.dry_ok === "") items.push(__("Record whether the linen is dry."));
		return items;
	}

	completeBatch() {
		const items = this.finishProblems();
		if (items.length) {
			this.notice = {
				variant: "error",
				title: __("The batch cannot be completed yet"),
				reason: __("Some drying or result values are missing."),
				items,
				action: __("Fill in the values, then complete the batch."),
			};
			return this.show();
		}
		this.notice = null;
		const finish = this.finish;
		const args = {
			station: this.station.station,
			batch: finish.batch,
			clean_ok: Number(finish.clean_ok),
			dry_ok: Number(finish.dry_ok),
		};
		if (finish.dryer) {
			args.dryer = finish.dryer;
			args.dry_temp_c = TcWeighLine.parse(finish.dry_temp);
			args.dry_minutes = TcWeighLine.parse(finish.dry_minutes);
		}
		if (finish.note.trim()) args.note = finish.note.trim();
		this.request(LAU_COMPLETE, args, (res) => {
			this.done = res.batch;
			this.mode = "done";
			this.finish = this.blankFinish("");
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
		if (this.offline) return this.station.setState("offline", this.offlineHtml());
		if (!this.ctx && !this.notice && !this.busy) {
			this.loadContext();
			return this.station.renderLoading();
		}
		const failed = this.notice && this.notice.variant === "error";
		const empty = this.ctx && !this.washers().length && !(this.ctx.running || []).length;
		const state = failed ? "error" : empty ? "empty" : "result";
		let body = "";
		if (this.ctx) {
			if (this.mode === "done" && this.done) body = this.doneHtml();
			else if (this.mode === "finish") body = this.finishHtml();
			else body = this.startHtml();
		}
		this.station.setState(
			state,
			`<div class="tc-linen tc-laundry">
				${linenTabs("laundry")}
				<div data-region="notice">${this.noticeHtml()}</div>
				${body}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
	}

	standardOfflineActions() {
		return `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
				__("Retry")
			)}</button>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
				__("Call R02")
			)}</button>
		</div>`;
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
		if (this.ctx && !this.washers().length && this.mode === "start") {
			html += this.alertHtml({
				variant: "info",
				title: __("No washer is ready"),
				reason: __("No laundry washer is ready to use."),
				action: __(
					"Call R02 to check the washers, or send the linen to an outside vendor."
				),
			});
		}
		return html;
	}

	offlineHtml() {
		return this.alertHtml(
			{
				variant: "info",
				title: __("Station offline"),
				reason: __("Recording laundry batches needs a network connection."),
				action: __("Retry when the connection returns."),
			},
			this.standardOfflineActions()
		);
	}

	option(value, label, selected) {
		return `<option value="${esc(value)}"${selected ? " selected" : ""}>${esc(
			label
		)}</option>`;
	}

	startHtml() {
		const form = this.form;
		const outsourced = form.batch_type === "Outsourced";
		const washers = this.washers()
			.map((row) =>
				this.option(
					row.name,
					`${row.equipment_name || row.name}${
						row.capacity_kg ? ` (${TcWeighLine.format(row.capacity_kg)} kg)` : ""
					}`,
					form.equipment === row.name
				)
			)
			.join("");
		const programs = this.programsOf(form.equipment)
			.map((row) =>
				this.option(
					row.name,
					`${row.program_name || row.name} (${row.temperature || 0} C)`,
					form.program === row.name
				)
			)
			.join("");
		const machine = outsourced
			? `<div class="tc-field">
					<label for="tc-lau-vendor">${esc(__("Vendor"))} *</label>
					<input id="tc-lau-vendor" type="text" autocomplete="off" data-lf="vendor" value="${esc(
						form.vendor
					)}">
				</div>
				<div class="tc-field">
					<label for="tc-lau-price">${esc(__("Price per kg"))} *</label>
					<input id="tc-lau-price" type="text" inputmode="decimal" autocomplete="off" data-lf="price" value="${esc(
						form.price
					)}">
				</div>`
			: `<div class="tc-field">
					<label for="tc-lau-washer">${esc(__("Washer"))} *</label>
					<select id="tc-lau-washer" data-lf="equipment">
						<option value="">${esc(__("Choose the washer"))}</option>${washers}
					</select>
				</div>
				<div class="tc-field">
					<label for="tc-lau-program">${esc(__("Program"))} *</label>
					<select id="tc-lau-program" data-lf="program">
						<option value="">${esc(__("Choose the program"))}</option>${programs}
					</select>
				</div>`;
		const redo = form.redo_of
			? `<p class="tc-t6-hint">${esc(__("Washing again batch {0}.", [form.redo_of]))}</p>`
			: "";
		return `<section class="tc-t6-block" aria-label="${esc(__("Laundry batch"))}">
			${redo}
			<div class="tc-linen-head">
				<div class="tc-field">
					<label for="tc-lau-type">${esc(__("Batch Type"))}</label>
					<select id="tc-lau-type" data-lf="batch_type">
						${this.option("In-house", __("In-house"), !outsourced)}
						${this.option("Outsourced", __("Outsourced"), outsourced)}
					</select>
				</div>
				<div class="tc-field">
					<label for="tc-lau-flag">${esc(__("Linen"))}</label>
					<select id="tc-lau-flag" data-lf="contaminated">
						${this.option("1", __("Contaminated"), form.contaminated)}
						${this.option("0", __("Clean"), !form.contaminated)}
					</select>
				</div>
				<div class="tc-field">
					<label for="tc-lau-kg">${esc(__("Weight (kg)"))} *</label>
					<input id="tc-lau-kg" type="text" inputmode="decimal" autocomplete="off" data-lf="kg" value="${esc(
						form.kg
					)}">
				</div>
			</div>
			<div class="tc-linen-head">${machine}</div>
			<div data-hint="batch">${this.hintHtml()}</div>
			${outsourced ? "" : this.chemicalsHtml()}
			<div class="tc-field">
				<label for="tc-lau-note">${esc(__("Note"))}</label>
				<textarea id="tc-lau-note" rows="2" data-lf="note">${esc(form.note)}</textarea>
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="start"${
					this.busy ? " disabled" : ""
				}>${esc(__("Start batch"))}</button>
			</div>
			${this.runningHtml()}
		</section>`;
	}

	// Định mức hóa chất theo chương trình x kg và cảnh báo nhiệt độ
	hintHtml() {
		const form = this.form;
		if (form.batch_type === "Outsourced") return "";
		const program = this.programInfo();
		const kg = TcWeighLine.parse(form.kg);
		let html = "";
		if (program && program.norms && program.norms.length) {
			const text = program.norms
				.map((norm) => {
					const qty = (norm.qty_per_load || 0) + (norm.qty_per_kg || 0) * (kg || 0);
					return `${norm.item} ${TcWeighLine.format(qty)}`;
				})
				.join(", ");
			html += `<p class="tc-t6-hint">${esc(
				__("Chemicals by the program norm: {0}", [text])
			)}</p>`;
		} else if (program) {
			html += `<p class="tc-t6-hint">${esc(
				__("This program has no consumption norm; no chemical is deducted from stock.")
			)}</p>`;
		}
		if (
			program &&
			form.contaminated &&
			(program.temperature || 0) < LAU_MIN_CONTAMINATED_C &&
			!this.hasDisinfectant()
		) {
			html += `<div class="tc-alert tc-alert-warn" role="status">
				<p class="tc-alert-title"><span aria-hidden="true">!</span> ${esc(
					__("Contaminated linen below {0} C needs a disinfectant chemical.", [
						LAU_MIN_CONTAMINATED_C,
					])
				)}</p>
			</div>`;
		}
		return html;
	}

	chemicalsHtml() {
		const options = (this.ctx && this.ctx.chemicals) || [];
		const rows = this.form.chemicals
			.map((row, index) => {
				const list = options
					.map((item) =>
						this.option(
							item.name,
							`${item.item_name || item.name}${
								item.tc_is_disinfectant ? ` (${__("Disinfectant")})` : ""
							}`,
							row.item === item.name
						)
					)
					.join("");
				return `<div class="tc-linen-head">
					<div class="tc-field">
						<label for="tc-lau-chem-${index}">${esc(__("Chemical"))}</label>
						<select id="tc-lau-chem-${index}" data-lf="chem_item" data-row="${index}">
							<option value="">${esc(__("Choose the chemical"))}</option>${list}
						</select>
					</div>
					<div class="tc-field">
						<label for="tc-lau-qty-${index}">${esc(__("Quantity"))}</label>
						<input id="tc-lau-qty-${index}" type="text" inputmode="decimal" autocomplete="off"
							data-lf="chem_qty" data-row="${index}" value="${esc(row.qty)}">
					</div>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="remove-chemical" data-row="${index}">${esc(
					__("Remove line")
				)}</button>
				</div>`;
			})
			.join("");
		return `<div class="tc-linen-lines">${rows}</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-secondary" data-action="add-chemical">${esc(
					__("Add a chemical")
				)}</button>
			</div>`;
	}

	runningHtml() {
		const running = (this.ctx && this.ctx.running) || [];
		if (!running.length) return "";
		const rows = running
			.map((row) => {
				const kind = row.contaminated ? __("Contaminated") : __("Clean");
				const outside =
					row.batch_type === "Outsourced" ? ` &middot; ${esc(__("Outsourced"))}` : "";
				return `<div class="tc-linen-line">
					<p><strong>${esc(row.name)}</strong> &middot; ${esc(
					TcWeighLine.format(row.weight_kg)
				)} kg &middot; ${esc(kind)}${outside}</p>
					<button type="button" class="tc-btn tc-btn-primary" data-action="open-finish" data-batch="${esc(
						row.name
					)}">${esc(__("Complete"))}</button>
				</div>`;
			})
			.join("");
		return `<h3>${esc(__("Running batches"))}</h3>${rows}`;
	}

	finishHtml() {
		const finish = this.finish;
		const batch = this.runningBatch();
		const dryers = ((this.ctx && this.ctx.dryers) || [])
			.map((row) =>
				this.option(row.name, row.equipment_name || row.name, finish.dryer === row.name)
			)
			.join("");
		const result = (field, label, value) => `<div class="tc-field">
				<label for="tc-lau-${field}">${esc(label)} *</label>
				<select id="tc-lau-${field}" data-lf="fin_${field}">
					${this.option("", __("Choose"), value === "")}
					${this.option("1", __("Pass"), value === "1")}
					${this.option("0", __("Fail"), value === "0")}
				</select>
			</div>`;
		const drying =
			batch && batch.batch_type === "Outsourced"
				? ""
				: `<div class="tc-linen-head">
					<div class="tc-field">
						<label for="tc-lau-dryer">${esc(__("Dryer"))} *</label>
						<select id="tc-lau-dryer" data-lf="fin_dryer">
							<option value="">${esc(__("Choose the dryer"))}</option>${dryers}
						</select>
					</div>
					<div class="tc-field">
						<label for="tc-lau-dry-temp">${esc(__("Dry Temperature (C)"))} *</label>
						<input id="tc-lau-dry-temp" type="text" inputmode="numeric" autocomplete="off" data-lf="fin_dry_temp" value="${esc(
							finish.dry_temp
						)}">
					</div>
					<div class="tc-field">
						<label for="tc-lau-dry-min">${esc(__("Dry Time (min)"))} *</label>
						<input id="tc-lau-dry-min" type="text" inputmode="numeric" autocomplete="off" data-lf="fin_dry_minutes" value="${esc(
							finish.dry_minutes
						)}">
					</div>
				</div>`;
		const weight = batch ? ` &middot; ${esc(TcWeighLine.format(batch.weight_kg))} kg` : "";
		return `<section class="tc-t6-block" aria-label="${esc(__("Complete the batch"))}">
			<p><strong>${esc(finish.batch)}</strong>${weight}</p>
			${drying}
			<div class="tc-linen-head">
				${result("clean_ok", __("Clean"), finish.clean_ok)}
				${result("dry_ok", __("Dry"), finish.dry_ok)}
			</div>
			<div class="tc-field">
				<label for="tc-lau-fin-note">${esc(__("Note"))}</label>
				<textarea id="tc-lau-fin-note" rows="2" data-lf="fin_note">${esc(finish.note)}</textarea>
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="complete"${
					this.busy ? " disabled" : ""
				}>${esc(__("Complete batch"))}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="back">${esc(
					__("Back")
				)}</button>
			</div>
		</section>`;
	}

	// VND không lẻ, dấu chấm hàng nghìn theo vi-VN
	money(value) {
		return new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 }).format(value || 0);
	}

	doneHtml() {
		const done = this.done;
		const passed = done.status === "Passed";
		const line = (label, value) =>
			`<tr><th scope="row">${esc(label)}</th><td>${esc(this.money(value))}</td></tr>`;
		const alert = this.alertHtml({
			variant: passed ? "ok" : "warn",
			title: passed
				? __("Batch {0} passed", [done.name])
				: __("Batch {0} did not pass", [done.name]),
			reason: __("{0} kg, cost {1} per kg.", [
				TcWeighLine.format(done.weight_kg),
				this.money(done.cost_per_kg),
			]),
			action: passed
				? __("The chemicals were deducted from stock.")
				: __("The chemicals were deducted from stock. Wash the linen again."),
		});
		const note = done.cost_note
			? this.alertHtml({ variant: "warn", title: done.cost_note, reason: "", action: "" })
			: "";
		const redo = passed
			? ""
			: `<button type="button" class="tc-btn tc-btn-primary" data-action="redo">${esc(
					__("Wash again")
			  )}</button>`;
		return `<section class="tc-t6-block">
			${alert}
			<table class="tc-t6-table">
				<tbody>
					${line(__("Electricity"), done.cost_electricity)}
					${line(__("Water"), done.cost_water)}
					${line(__("Chemicals"), done.cost_chemical)}
					${line(__("Labor"), done.cost_labor)}
					${line(__("Total Cost"), done.cost_total)}
					${line(__("Cost per kg"), done.cost_per_kg)}
				</tbody>
			</table>
			${note}
			<div class="tc-actions">
				${redo}
				<button type="button" class="tc-btn ${
					passed ? "tc-btn-primary" : "tc-btn-secondary"
				}" data-action="new-batch">${esc(__("New batch"))}</button>
			</div>
		</section>`;
	}
}

// Khuôn gọi RPC, thử lại và hộp thông báo dùng chung với màn thu gom (cùng trạm LIN)
for (const name of ["request", "markOnline", "retry", "alertHtml", "standardButtons"]) {
	LaundryBatch.prototype[name] = LinenCollect.prototype[name];
}

// Trạm đồ vải: hai màn, Thu gom (LinenCollect) và Lô giặt (LaundryBatch), chuyển bằng thanh tab ở đầu màn.
// TraceCoreStation chỉ biết một `screen`; lớp này chuyển mọi lời gọi cho màn đang mở.
class LinenStation {
	constructor(station) {
		this.station = station;
		this.collect = new LinenCollect(station);
		this.laundry = new LaundryBatch(station);
		this.issue = new LinenIssue(station); // FEAT-035, SCR-18: cấp phát đồ vải cho khoa
		this.active = this.collect;
	}

	get dialogOpen() {
		return this.active.dialogOpen;
	}

	get busy() {
		return this.active.busy;
	}

	clearSession() {
		this.collect.clearSession();
		this.laundry.clearSession();
		this.issue.clearSession();
		this.active = this.collect;
	}

	scan(raw) {
		return this.active.scan(raw);
	}

	setOffline(offline) {
		this.collect.offline = offline;
		this.laundry.offline = offline;
		this.issue.offline = offline;
		return this.active.show();
	}

	show() {
		return this.active.show();
	}

	onAction(action, button) {
		if (action === "linen-mode") {
			if (this.active.busy) return true;
			this.active = this[button.dataset.mode] || this.collect; // collect | laundry | issue
			this.active.notice = null;
			this.active.show();
			return true;
		}
		return this.active.onAction(action, button);
	}
}
