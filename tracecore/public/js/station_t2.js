/* global uuid4, clientTs, esc */
// Màn T2 lô rửa (SCR-06, FEAT-021) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// Ô quét chính của shell luôn ở đầu và có focus: chế độ "Nạp lô" nhận QR máy, Set ID, mã HOAN-THANH-NAP và mã lô
// (tra cứu); chế độ "Dỡ lô" nhận QR máy rồi QR mã lô. Danh sách bộ đang nạp chỉ nằm trên kiosk (sessionStorage, Q1):
// server sinh mã lô LR- khi Hoàn thành nạp. Lỗi chặn = alert-error inline; RPC do shell gắn bearer trong body.

const T2_COMPLETE_CODE = "HOAN-THANH-NAP";
const T2_AGENT_URL = "http://127.0.0.1:8765/print";
const T2_AGENT_TIMEOUT_MS = 5000;
const T2_COMPLETE = "tracecore.v1.wash.complete";
const T2_RESULT = "tracecore.v1.wash.result";
const T2_SAVE = "tracecore.v1.wash.manual_data";
// từ chối làm lô đang dỡ không còn dùng được → bỏ trạng thái dỡ để quét lô khác
const T2_UNLOAD_RESET_CODES = ["WASH_BATCH_NOT_FOUND", "BATCH_NOT_RUNNING", "STATION_WRONG_STEP"];

function t2Date(iso) {
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
	return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

function t2DateTime(iso) {
	const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(iso || "");
	return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : t2Date(iso);
}

function t2LocalInput(value) {
	// "YYYY-MM-DD HH:MM:SS" (giờ hệ thống) → giá trị ô datetime-local "YYYY-MM-DDTHH:MM"
	const m = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/.exec(value || "");
	return m ? `${m[1]}T${m[2]}` : "";
}

function t2SystemTimeZone() {
	// giờ trên form là giờ hệ thống (Asia/Ho_Chi_Minh), không theo múi giờ của trình duyệt: server coi chuỗi không có
	// offset là giờ hệ thống, và giờ bắt đầu của lô cũng là giờ hệ thống
	return (
		(frappe.boot && frappe.boot.time_zone && frappe.boot.time_zone.system) ||
		"Asia/Ho_Chi_Minh"
	);
}

function t2NowInput(date = new Date()) {
	const parts = {};
	new Intl.DateTimeFormat("en-CA", {
		timeZone: t2SystemTimeZone(),
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		hourCycle: "h23",
	})
		.formatToParts(date)
		.forEach((part) => {
			parts[part.type] = part.value;
		});
	return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function t2Disabled(flag) {
	return flag ? " disabled" : "";
}

function t2Kind(raw) {
	// phân loại sơ bộ trên kiosk; server luôn kiểm lại (gs1.parse_scan)
	const value = String(raw || "").toUpperCase();
	let m = /LR-\d{6}-\d{2}/.exec(value);
	if (m) return { kind: "batch", id: m[0] };
	m = /TB-\d{4}/.exec(value);
	if (m) return { kind: "equipment", id: m[0] };
	return { kind: "set", id: String(raw || "").trim() };
}

function t2GateLabel(step) {
	return (
		{
			T1: __("T1 Reception · count"),
			T2: __("T2 Washing – disinfection"),
			T3: __("T3 Assembly"),
			T4: __("T4 Packing"),
			T5: __("T5 Sterilization · release"),
		}[step] || step
	);
}

class T2Wash {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.busy = null;
		this.offline = false;
		this.overview = null; // {sets: hàng đợi xử lý lại, running: lô đang chạy}
		this.overviewBusy = false;
		this.reset();
		this.load = this.restoreLoad();
		this.result.addEventListener("change", (event) => this.onChange(event));
		this.result.addEventListener("input", (event) => this.onInput(event));
	}

	get dialogOpen() {
		return false;
	}

	reset() {
		this.mode = "load";
		this.load = null; // {machine, programs, lots, program, lot, sets: [{set_id, set_name, gates}]}
		this.done = null; // kết quả wash.complete
		this.printNote = null;
		this.lookup = null;
		this.notice = null;
		this.unload = null; // {batch, equipmentRaw, batchRaw, context, saved, result}
		this.form = null;
		this.verdict = null;
	}

	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.overview = null;
		this.overviewBusy = false;
		this.reset();
		this.saveLoad();
		this.input.placeholder = __("Scan Set ID...");
		this.input.setAttribute("aria-label", __("Scan Set ID"));
	}

	// ---- danh sách nạp trên kiosk (Q1) ----
	storageKey() {
		return `tc-t2-load:${this.station.station}`;
	}

	restoreLoad() {
		try {
			const raw = sessionStorage.getItem(this.storageKey());
			const load = raw ? JSON.parse(raw) : null;
			return load && load.machine && Array.isArray(load.sets) ? load : null;
		} catch (error) {
			return null;
		}
	}

	saveLoad() {
		try {
			if (this.load) sessionStorage.setItem(this.storageKey(), JSON.stringify(this.load));
			else sessionStorage.removeItem(this.storageKey());
		} catch (error) {
			// kiosk tắt storage: danh sách chỉ còn trong bộ nhớ
		}
	}

	// ---- quét ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline()) return this.station.setOffline(true);
		if (this.mode === "unload") return this.unloadScan(raw);
		if (raw.toUpperCase() === T2_COMPLETE_CODE) return this.complete();
		const code = t2Kind(raw);
		if (code.kind === "batch") return this.lookupBatch(raw);
		if (code.kind === "equipment") {
			if (this.load && this.load.sets.length && this.load.machine.name !== code.id) {
				return this.blocked({
					title: __("Loading of washer {0} is not finished", [this.load.machine.name]),
					reason: __("{0} set(s) are on the list for washer {1}.", [
						this.load.sets.length,
						this.load.machine.name,
					]),
					action: __("Complete loading or cancel it before scanning another washer."),
				});
			}
			return this.request(
				"tracecore.v1.wash.start",
				{ raw, station: this.station.station },
				(res) => this.onMachine(res)
			);
		}
		if (!this.load) {
			return this.blocked({
				title: __("Scan the washer first"),
				reason: __("Code {0} was scanned before a washer QR code.", [raw]),
				action: __("Scan the QR code on the washer, then scan each set."),
			});
		}
		return this.request(
			"tracecore.v1.wash.add_set",
			{
				raw,
				equipment: this.load.machine.name,
				queued: this.load.sets.map((row) => row.set_id),
				station: this.station.station,
			},
			(res) => this.onSet(res)
		);
	}

	lookupBatch(raw) {
		return this.request(
			"tracecore.v1.wash.lookup",
			{ raw, station: this.station.station },
			(res) => {
				this.notice = null;
				this.lookup = res.batch;
				this.show();
			}
		);
	}

	blocked(error) {
		this.notice = { variant: "error", ...error };
		this.show();
		this.station.focus(true);
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
		this.show();
		const started = performance.now();
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
		if (!failure) {
			this.pending = null;
			this.result.dataset.ms = String(Math.round(performance.now() - started));
		}
		this.busy = null;
		if (!failure) this.markOnline();
		if (failure) this.failure(failure);
		else if (response && response.ok === false) this.reject(response.error, method);
		else onOk(response);
		this.station.focus(true);
	}

	retry() {
		this.station.manualOffline = false;
		if (!navigator.onLine) return this.station.setOffline(true);
		this.station.setOffline(false);
		const pending = this.pending;
		if (pending) return this.request(pending.method, pending.args, pending.onOk);
		this.notice = null;
		this.loadOverview(true);
		this.show();
	}

	markOnline() {
		if (!this.offline) return;
		this.offline = false;
		this.station.manualOffline = false;
		this.station.banner.hidden = true;
		this.station.root.dataset.offline = "0";
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
				reason: __("This account cannot work with wash batches at this station."),
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

	reject(error, method) {
		if (this.unload && T2_UNLOAD_RESET_CODES.includes(error.code) && method !== T2_COMPLETE)
			this.unload = null;
		this.notice = { variant: "error", ...error };
		this.show();
	}

	// ---- nạp lô ----
	programRow() {
		if (!this.load) return null;
		return this.load.programs.find((row) => row.program_code === this.load.program) || null;
	}

	lotsFor(program) {
		if (!this.load || !program || !program.chemical) return [];
		return this.load.lots.filter((lot) => lot.item === program.chemical);
	}

	onMachine(res) {
		const programs = res.programs || [];
		this.load = {
			machine: res.equipment,
			programs,
			lots: res.chemical_lots || [],
			program: programs.length ? programs[0].program_code : null,
			lot: null,
			sets: [],
		};
		this.pickLot();
		this.done = null;
		this.printNote = null;
		this.lookup = null;
		this.notice = {
			variant: "ok",
			title: __("Washer {0} scanned · {1}", [
				res.equipment.name,
				res.equipment.equipment_name,
			]),
			reason: res.equipment.is_connected
				? __(
						"API connected - automatic data comes with FEAT-024; unload with confirmed manual entry."
				  )
				: __("Not connected - unload with confirmed manual entry."),
		};
		this.saveLoad();
		this.show();
	}

	pickLot() {
		// FEFO: lô gần hạn nhất của hóa chất chương trình (server đã sắp theo hạn tăng dần)
		const lots = this.lotsFor(this.programRow());
		if (!lots.some((lot) => lot.batch_no === this.load.lot))
			this.load.lot = lots.length ? lots[0].batch_no : null;
	}

	onSet(res) {
		if (res.duplicate) {
			this.notice = {
				variant: "info",
				title: __("{0} is already on the list", [res.set_id]),
			};
		} else {
			this.load.sets.push({
				set_id: res.set_id,
				set_name: res.set_name,
				gates: res.gates || [],
			});
			this.notice = {
				variant: "ok",
				title: __("Scanned {0} into washer {1} ({2} set(s))", [
					res.set_id,
					this.load.machine.name,
					this.load.sets.length,
				]),
			};
			this.saveLoad();
		}
		this.done = null;
		this.lookup = null;
		this.show();
	}

	removeSet(setId) {
		if (!this.load || this.busy) return;
		this.load.sets = this.load.sets.filter((row) => row.set_id !== setId);
		this.saveLoad();
		this.notice = { variant: "info", title: __("Removed {0} from the list", [setId]) };
		this.show();
	}

	cancelLoad() {
		if (this.busy) return;
		this.load = null;
		this.saveLoad();
		this.notice = {
			variant: "info",
			title: __("Loading cancelled; scan a washer QR code to start again."),
		};
		this.show();
	}

	missing() {
		const out = [];
		if (this.offline) out.push(__("network connection"));
		if (!this.load) out.push(__("washer"));
		if (!this.load || !this.load.sets.length) out.push(__("at least 1 set"));
		const program = this.programRow();
		if (this.load && !program) out.push(__("wash program"));
		if (program && program.chemical && !this.load.lot) out.push(__("chemical lot"));
		return out;
	}

	complete() {
		if (this.mode !== "load" || this.busy || this.missing().length) {
			if (this.mode === "load" && !this.busy && this.missing().length) {
				this.blocked({
					title: __("Loading cannot be completed yet"),
					reason: __("Missing: {0}", [this.missing().join(", ")]),
					action: __(
						"Scan the washer and the sets, choose the program and the chemical lot."
					),
				});
			}
			return;
		}
		const program = this.programRow();
		const lot = this.lotsFor(program).find((row) => row.batch_no === this.load.lot);
		const load = this.load;
		this.request(
			T2_COMPLETE,
			{
				equipment: load.machine.name,
				program: program.program_code,
				sets: load.sets.map((row) => row.set_id),
				chemicals: lot ? [{ item: lot.item, lot: lot.batch_no }] : [],
				station: this.station.station,
			},
			(res) => {
				this.done = {
					...res,
					machine: load.machine,
					program_name: program.program_name,
					at: t2NowInput().replace("T", " "),
				};
				this.load = null;
				this.saveLoad();
				this.notice = null;
				this.loadOverview(true);
				this.handlePrint(res.print);
			}
		);
	}

	async sendToAgent(job) {
		if (!this.station.session) return false;
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), T2_AGENT_TIMEOUT_MS);
		try {
			const response = await fetch(T2_AGENT_URL, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					zpl: job.zpl,
					print_job: job.print_job,
					printer: job.printer,
				}),
				signal: controller.signal,
			});
			return response.ok;
		} catch (error) {
			return false;
		} finally {
			clearTimeout(timer);
		}
	}

	async handlePrint(print) {
		const version = this.station.sessionVersion;
		if (print && print.status === "Queued" && print.zpl) {
			this.printNote = { kind: "sending" };
			this.show();
			const ok = await this.sendToAgent(print);
			if (version !== this.station.sessionVersion) return;
			this.printNote = { kind: ok ? "sent" : "agent-failed" };
		} else {
			this.printNote = { kind: "waiting" };
		}
		this.show();
	}

	// ---- bảng phụ: lô đang chạy + hàng đợi xử lý lại ----
	async loadOverview(force = false) {
		if (this.overviewBusy || (this.overview && !force) || !this.station.session) return;
		if (this.station.isOffline()) return;
		const version = this.station.sessionVersion;
		this.overviewBusy = true;
		try {
			const res = await this.station.rpc("tracecore.v1.wash.redo_queue", {
				station: this.station.station,
				client_ts: clientTs(),
			});
			if (version !== this.station.sessionVersion) return;
			if (res && res.ok)
				this.overview = { sets: res.sets || [], running: res.running || [] };
		} catch (error) {
			if (error.sessionEnded) return;
		} finally {
			this.overviewBusy = false;
		}
		if (version === this.station.sessionVersion && !this.busy) this.show();
	}

	// ---- dỡ lô ----
	setMode(mode) {
		if (this.busy || (mode !== "load" && mode !== "unload")) return;
		this.mode = mode;
		this.notice = null;
		this.lookup = null;
		if (mode === "load") this.unload = null;
		this.loadOverview(true);
		this.show();
	}

	unloadScan(raw) {
		const code = t2Kind(raw);
		if (code.kind === "set") {
			return this.blocked({
				title: __("Invalid code"),
				reason: __("Code {0} is not the washer QR code or a wash batch code.", [raw]),
				action: __("Scan the washer QR code, then the batch QR code."),
			});
		}
		const current = this.unload && !this.unload.result ? this.unload : null;
		let batch = current && current.batch;
		if (code.kind === "batch" && batch !== code.id) batch = code.id;
		if (code.kind === "equipment" && !batch) {
			const running = ((this.overview && this.overview.running) || []).filter(
				(row) => row.equipment === code.id
			);
			if (running.length !== 1) {
				return this.blocked({
					title: running.length
						? __("Washer {0} has more than one running batch", [code.id])
						: __("Washer {0} has no running batch", [code.id]),
					reason: __(
						"The batch to unload cannot be chosen from the washer QR code alone."
					),
					action: __("Scan the QR code on the wash batch label."),
				});
			}
			batch = running[0].batch;
		}
		if (!current || current.batch !== batch) this.unload = { batch };
		this.request(
			"tracecore.v1.wash.unload",
			{ batch, raw, station: this.station.station },
			(res) => this.onUnloadScan(res, raw)
		);
	}

	onUnloadScan(res, raw) {
		const unload = this.unload;
		if (res.kind === "equipment") unload.equipmentRaw = raw;
		else unload.batchRaw = raw;
		this.lookup = null;
		if (unload.equipmentRaw && unload.batchRaw) return this.fetchContext();
		this.notice = {
			variant: "info",
			title:
				res.kind === "equipment"
					? __("Washer QR code scanned for batch {0}", [unload.batch])
					: __("Batch QR code {0} scanned", [unload.batch]),
			reason:
				res.kind === "equipment"
					? __("Scan the batch QR code next.")
					: __("Scan the washer QR code next."),
		};
		this.show();
	}

	unloadArgs() {
		return {
			batch: this.unload.batch,
			equipment_raw: this.unload.equipmentRaw,
			batch_raw: this.unload.batchRaw,
			station: this.station.station,
		};
	}

	fetchContext(notice = null) {
		return this.request("tracecore.v1.wash.unload_context", this.unloadArgs(), (res) => {
			const context = res.batch;
			this.unload.context = context;
			const data = context.machine_data || {};
			const values = {};
			(data.parameters || []).forEach((row) => {
				values[row.parameter_name] = String(row.value);
			});
			this.form = {
				values,
				alerts: data.alerts ? "yes" : "no",
				alertsText: data.alerts || "",
				reported: data.reported_result || "",
				started: t2LocalInput(context.started_at),
				ended: t2LocalInput(context.ended_at) || t2NowInput(),
				file: context.machine_files || "",
				uploading: false,
				confirmed: false,
			};
			this.verdict = { result: "", clean: "", confirmed: false, pin: "" };
			this.notice = notice || {
				variant: "ok",
				title: __("Scanned washer QR {0} and batch QR {1}", [
					context.equipment.name,
					context.batch,
				]),
				reason: __("The result below applies to all {0} set(s) in the batch.", [
					context.sets.length,
				]),
			};
			this.show();
		});
	}

	oldMachine() {
		const machine = this.unload && this.unload.context && this.unload.context.equipment;
		return Boolean(machine && !machine.is_connected && !machine.has_printout);
	}

	paramState(param, raw) {
		const text = String(raw == null ? "" : raw).trim();
		if (!text) return "";
		const value = Number(text.replace(",", "."));
		if (Number.isNaN(value)) return "invalid";
		const low = Number(param.min_value) || 0;
		const high = Number(param.max_value) || 0;
		return (low && value < low) || (high && value > high) ? "review" : "";
	}

	saveData() {
		if (
			!this.unload ||
			!this.unload.context ||
			this.busy ||
			this.offline ||
			this.form.uploading
		)
			return;
		const form = this.form;
		const schema = this.unload.context.parameter_schema || [];
		const toServer = (value) => (value ? `${value.replace("T", " ")}:00` : null);
		this.request(
			T2_SAVE,
			{
				...this.unloadArgs(),
				values: schema.map((param) => ({
					parameter_name: param.parameter_name,
					value: form.values[param.parameter_name] || null,
				})),
				started_at: toServer(form.started),
				ended_at: toServer(form.ended),
				confirmed: form.confirmed ? 1 : 0,
				reported_result: form.reported || null,
				machine_alerts: form.alerts === "yes" ? form.alertsText || __("Yes") : null,
				machine_file: form.file || null,
			},
			(res) => {
				const notice = res.data_complete
					? {
							variant: res.needs_review ? "warn" : "ok",
							title: __("Manual cycle data saved and confirmed"),
							reason: res.needs_review
								? __(
										"Some values are outside the program range: Needs review by R02."
								  )
								: "",
					  }
					: {
							variant: "error",
							title: __("Cycle data is incomplete"),
							reason: __("The data was saved, but the batch cannot be closed yet."),
							items: res.missing.map((item) => this.missingLabel(item)),
							action: __("Complete the missing items, then save again."),
					  };
				this.loadOverview(true);
				// đủ dữ liệu: đọc lại ngữ cảnh để thẻ dữ liệu và khối kết luận dùng bản server đã lưu
				if (res.data_complete) return this.fetchContext(notice);
				this.notice = notice;
				this.show();
			}
		);
	}

	missingLabel(item) {
		return (
			{
				ended_at: __("end time (not before the start time)"),
				printout: __("photo of the printout or chart"),
				confirmation: __("confirmation tick"),
			}[item] || item
		);
	}

	async uploadFile(input) {
		const file = input.files && input.files[0];
		if (!file || !this.form) return;
		const version = this.station.sessionVersion;
		this.form.uploading = true;
		this.show();
		try {
			const body = new FormData();
			body.append("file", file, file.name);
			body.append("is_private", "1");
			body.append("folder", "Home");
			const response = await fetch("/api/method/upload_file", {
				method: "POST",
				headers: { Accept: "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token },
				body,
				credentials: "same-origin",
			});
			const data = await response.json().catch(() => ({}));
			if (version !== this.station.sessionVersion || !this.form) return;
			if (!response.ok || !data.message || !data.message.file_url) throw new Error("upload");
			this.form.file = data.message.file_url;
			this.notice = { variant: "ok", title: __("Photo attached: {0}", [file.name]) };
		} catch (error) {
			if (version !== this.station.sessionVersion || !this.form) return;
			this.notice = {
				variant: "error",
				title: __("Photo could not be attached"),
				reason: __("The file {0} was not uploaded.", [file.name]),
				action: __("Check the connection and choose the photo again."),
			};
		} finally {
			if (this.form) this.form.uploading = false;
		}
		this.show();
	}

	async recordResult() {
		if (!this.unload || !this.unload.context || this.busy || this.offline) return;
		const verdict = this.verdict;
		if (!verdict.result || !verdict.clean) {
			return this.blocked({
				title: __("Choose the result"),
				reason: __("Choose Pass or Fail for the cycle and for the cleaning test."),
				action: __("Tap the result buttons, then record again."),
			});
		}
		if (!verdict.confirmed) {
			return this.blocked({
				title: __("Confirmation tick is required"),
				reason: __(
					"The result must be confirmed against the washer before it is recorded."
				),
				action: __("Tick the confirmation box, then record the result."),
			});
		}
		let proof = null;
		if (verdict.result === "Pass" && this.oldMachine()) {
			proof = await this.reviewerProof();
			if (!proof) return;
		}
		this.request(
			T2_RESULT,
			{
				...this.unloadArgs(),
				result: verdict.result,
				clean_test: verdict.clean,
				reviewer_proof: proof,
				note: null,
			},
			(res) => {
				this.unload = { batch: res.batch, result: res };
				this.form = null;
				this.verdict = null;
				this.notice = null;
				this.loadOverview(true);
				this.show();
			}
		);
	}

	async reviewerProof() {
		// Q7: máy cũ không kết nối, không bản in → kết luận Đạt cần PIN của R02 đang đăng nhập thẻ tại trạm
		const pin = (this.verdict.pin || "").trim();
		if (!/^\d{6}$/.test(pin)) {
			this.blocked({
				title: __("R02 PIN is required"),
				reason: __(
					"This washer has no connection and no printout, so a Pass needs the confirmation of R02."
				),
				action: __(
					"R02 signs in with the card at this station and enters the 6-digit PIN."
				),
			});
			return null;
		}
		const version = this.station.sessionVersion;
		try {
			const res = await this.station.rpc("tracecore.v1.station.verify_pin", {
				token: this.station.session.token,
				pin,
				client_ts: clientTs(),
			});
			if (version !== this.station.sessionVersion) return null;
			this.verdict.pin = "";
			if (res && res.ok && res.proof) return res.proof;
			this.blocked({ ...(res && res.error) });
		} catch (error) {
			if (!error.sessionEnded) this.failure(error);
		}
		return null;
	}

	// ---- sự kiện trên màn ----
	onAction(action, button) {
		const data = (button && button.dataset) || {};
		const handlers = {
			retry: () => this.retry(),
			"t2-mode": () => this.setMode(data.mode),
			"t2-remove": () => this.removeSet(data.set),
			"t2-complete": () => this.complete(),
			"t2-cancel": () => this.cancelLoad(),
			"t2-save-data": () => this.saveData(),
			"t2-verdict": () => {
				if (!this.verdict) return;
				this.verdict[data.field] = data.value;
				this.show();
			},
			"t2-record": () => this.recordResult(),
			"t2-unload-reset": () => {
				this.unload = null;
				this.notice = null;
				this.show();
			},
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	onChange(event) {
		const target = event.target;
		if (target.id === "tc-t2-program" && this.load) {
			this.load.program = target.value;
			this.pickLot();
			this.saveLoad();
			this.show();
		} else if (target.id === "tc-t2-lot" && this.load) {
			this.load.lot = target.value || null;
			this.saveLoad();
			this.show();
		} else if (target.id === "tc-t2-file") {
			this.uploadFile(target);
		} else if (target.dataset.form && this.form) {
			const field = target.dataset.form;
			this.form[field] = target.type === "checkbox" ? target.checked : target.value;
			if (field === "alerts") this.show();
		} else if (target.dataset.verdict && this.verdict) {
			this.verdict[target.dataset.verdict] =
				target.type === "checkbox" ? target.checked : target.value;
		}
	}

	onInput(event) {
		const target = event.target;
		if (target.dataset.param && this.form) {
			this.form.values[target.dataset.param] = target.value;
			const param = (this.unload.context.parameter_schema || []).find(
				(row) => row.parameter_name === target.dataset.param
			);
			const state = param ? this.paramState(param, target.value) : "";
			const field = target.closest(".tc-field");
			field.classList.toggle("is-review", state === "review");
			field.querySelector(".tc-t2-review").hidden = state !== "review";
		} else if (target.dataset.form && this.form && target.type !== "checkbox") {
			this.form[target.dataset.form] = target.value;
		} else if (target.dataset.verdict && this.verdict && target.type !== "checkbox") {
			this.verdict[target.dataset.verdict] = target.value;
		}
	}

	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	viewState() {
		if (this.offline && !this.load && !this.unload && !this.done) return "offline";
		if (this.notice && this.notice.variant === "error") return "error";
		const idle =
			this.mode === "load" && !this.load && !this.done && !this.lookup && !this.notice;
		return idle ? "empty" : "result";
	}

	show() {
		if (!this.station.session) return;
		this.updatePlaceholder();
		if (!this.overview) this.loadOverview();
		const body = this.mode === "unload" ? this.unloadHtml() : this.loadHtml();
		this.station.setState(
			this.viewState(),
			`<div class="tc-t2" data-mode="${esc(this.mode)}">
				${this.modeHtml()}
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.lookup ? this.lookupHtml(this.lookup) : ""}
				${body}
				${this.redoHtml()}
				${this.mode === "load" ? this.loadBarHtml() : ""}
			</div>`
		);
		const error = Boolean(this.notice && this.notice.variant === "error");
		this.station.form.classList.toggle("is-error", error);
		if (error && this.shownNotice !== this.notice) window.scrollTo({ top: 0 });
		this.shownNotice = this.notice;
	}

	updatePlaceholder() {
		let text = __("Scan the washer QR code...");
		if (this.mode === "unload")
			text = __("Scan the washer QR code, then the batch QR code...");
		else if (this.load)
			text = __("Scan each Set ID into the washer... (scan HOAN-THANH-NAP when done)");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	modeHtml() {
		const running = (this.overview && this.overview.running.length) || 0;
		const chip = (mode, label) =>
			`<button type="button" class="tc-chip" data-action="t2-mode" data-mode="${mode}"
				aria-pressed="${this.mode === mode ? "true" : "false"}">${esc(label)}</button>`;
		return `<div class="tc-chips" role="group" aria-label="${esc(__("Wash batch"))}">
			${chip("load", __("Load batch"))}
			${chip("unload", __("Unload batch ({0} running)", [running]))}
		</div>`;
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		const items = (notice.items || [])
			.map((item) => `<li>${esc(this.itemText(item))}</li>`)
			.join("");
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

	itemText(item) {
		if (typeof item !== "object" || item === null) return this.missingLabel(String(item));
		if (item.set_id) return `${item.set_id}: ${item.reason || item.code || ""}`;
		return JSON.stringify(item);
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
				reason: __(
					"Wash batches need a network connection; offline work comes with FEAT-009."
				),
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
		if (this.offline) html += this.offlineHtml();
		if (this.busy) {
			html += `<p class="tc-loading" role="status" aria-busy="true">${esc(
				__("Loading...")
			)}</p>`;
		}
		if (this.notice) {
			// lỗi kỹ thuật (mạng, máy chủ) có Thử lại; từ chối nghiệp vụ chỉ có kết quả → lý do → hành động
			html += this.alertHtml(
				this.notice,
				this.notice.technical ? this.standardButtons() : ""
			);
		}
		return html;
	}

	gateHtml(step, result, redo = 0, label = null) {
		let cls = "";
		let mark = "&#9675; ";
		let text = __("Pending", null, "Step Gate Result");
		if (result === "Pass") {
			[cls, mark, text] = ["ok", "&#10003; ", __("Pass", null, "Step Gate Result")];
		} else if (result === "Fail") {
			[cls, mark, text] = ["bad", "&#10005; ", __("Fail", null, "Step Gate Result")];
		}
		const redoText = redo ? `<small>${esc(__("Redone {0} time(s)", [redo]))}</small>` : "";
		return `<div class="tc-gate${cls ? " tc-gate-" + cls : ""}">
			<small>${esc(label || t2GateLabel(step))}</small>
			<b><span aria-hidden="true">${mark}</span>${esc(text)}</b>${redoText}
		</div>`;
	}

	gatesHtml(gates) {
		const cells = (gates || []).map((gate) =>
			this.gateHtml(gate.step, gate.result, gate.redo_count)
		);
		const sterile = (gates || []).length && gates.every((gate) => gate.result === "Pass");
		cells.push(this.gateHtml("S", sterile ? "Pass" : "Pending", 0, __("Sterile")));
		return `<div class="tc-gates" aria-label="${esc(__("Step gates"))}">${cells.join(
			""
		)}</div>`;
	}

	// -- chế độ nạp --
	loadHtml() {
		let html = "";
		if (this.done) html += this.doneHtml();
		const load = this.load;
		if (!load) {
			return `${html}<section class="tc-t4-block tc-t2-start">
				<h3>${esc(__("Load washer - scan the washer QR code first, then scan each set"))}</h3>
				<p class="tc-empty">${esc(
					__(
						"Only sets that passed T1 (receiving count) and are not in another batch are accepted."
					)
				)}</p>
			</section>`;
		}
		const program = this.programRow();
		const lots = this.lotsFor(program);
		const programOptions = load.programs
			.map(
				(row) =>
					`<option value="${esc(row.program_code)}"${
						row.program_code === load.program ? " selected" : ""
					}>${esc(row.program_name)} (${esc(row.program_code)})</option>`
			)
			.join("");
		let chemical = `<p>${esc(__("This program uses no chemical."))}</p>`;
		if (program && program.chemical) {
			chemical = lots.length
				? `<select id="tc-t2-lot" aria-label="${esc(
						__("Chemical (FEFO suggestion)")
				  )}">${lots
						.map(
							(lot) =>
								`<option value="${esc(lot.batch_no)}"${
									lot.batch_no === load.lot ? " selected" : ""
								}>${esc(
									__("{0} lot {1} · expires {2} · {3} {4} left", [
										lot.item,
										lot.batch_no,
										t2Date(lot.expiry_date),
										lot.qty,
										lot.uom || "",
									])
								)}</option>`
						)
						.join("")}</select>`
				: this.alertHtml({
						variant: "error",
						title: __("No valid lot of chemical {0}", [program.chemical]),
						reason: __("Every lot of this chemical has expired or is out of stock."),
						action: __("Receive a new lot into stock or call R02."),
				  });
		}
		const rows = load.sets
			.map(
				(row) => `<tr>
					<td class="tc-mono">${esc(row.set_id)}</td>
					<td>${esc(row.set_name || "-")}</td>
					<td>${this.gatesHtml(row.gates)}</td>
					<td><button type="button" class="tc-btn tc-btn-secondary" data-action="t2-remove"
						data-set="${esc(row.set_id)}"${t2Disabled(Boolean(this.busy))}>${esc(
					__("Remove from the list")
				)}</button></td>
				</tr>`
			)
			.join("");
		const table = load.sets.length
			? `<table class="tc-t2-table">
				<thead><tr><th>${esc(__("Set ID"))}</th><th>${esc(__("Set Type"))}</th><th>${esc(
					__("Step gates")
			  )}</th><th><span class="tc-sr-only">${esc(
					__("Remove from the list")
			  )}</span></th></tr></thead>
				<tbody>${rows}</tbody></table>`
			: `<p class="tc-empty">${esc(
					__(
						"Only sets that passed T1 (receiving count) and are not in another batch are accepted."
					)
			  )}</p>`;
		return `${html}<section class="tc-t4-block tc-t2-machine">
				<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(
					__("Washer {0} scanned · {1}", [
						load.machine.name,
						load.machine.equipment_name,
					])
				)} · ${esc(
			load.machine.is_connected
				? __("API connected - automatic data comes with FEAT-024")
				: __("not connected - unload with confirmed manual entry")
		)}</p>
				<div class="tc-t4-row">
					<div class="tc-field">
						<label for="tc-t2-program">${esc(__("Program"))}</label>
						<select id="tc-t2-program">${programOptions}</select>
					</div>
					<div class="tc-field">
						<label for="tc-t2-lot">${esc(__("Chemical (FEFO suggestion)"))}</label>
						${chemical}
					</div>
				</div>
			</section>
			<section class="tc-t4-block tc-t2-sets">
				<h3>${esc(
					__(
						"Sets scanned into washer {0} ({1}) - the batch code is generated at Complete loading",
						[load.machine.name, load.sets.length]
					)
				)}</h3>
				${table}
			</section>`;
	}

	loadBarHtml() {
		if (!this.load) return "";
		const missing = this.missing();
		const label =
			this.busy === T2_COMPLETE
				? __("Recording...")
				: __("Complete loading → generate batch code");
		return `<div class="tc-actionsbar">
			<button type="button" class="tc-btn tc-btn-primary" data-action="t2-complete"${t2Disabled(
				missing.length > 0 || Boolean(this.busy)
			)}>${esc(label)}</button>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="t2-cancel"${t2Disabled(
				Boolean(this.busy)
			)}>${esc(__("Cancel loading"))}</button>
			${
				missing.length
					? `<p class="tc-missing">${esc(__("Missing: {0}", [missing.join(", ")]))}</p>`
					: ""
			}
		</div>`;
	}

	doneHtml() {
		const done = this.done;
		const rejected =
			done.rejected && done.rejected.length
				? this.alertHtml({
						variant: "warn",
						title: __("{0} set(s) were not loaded", [done.rejected.length]),
						items: done.rejected,
						action: __("Take these sets out of the washer and check them."),
				  })
				: "";
		return `<section class="tc-t4-block tc-t4-done tc-t2-done">
			${this.alertHtml({
				variant: "ok",
				title: __("Batch code generated for {0} set(s)", [done.sets.length]),
			})}
			<p class="tc-cycle">${esc(done.batch)}</p>
			${rejected}
			<div class="tc-t4-done-grid">
				${this.labelHtml()}
				<div>
					<dl class="tc-res-grid">
						<dt>${esc(__("Washer"))}</dt><dd>${esc(done.machine.equipment_name)} <span class="tc-mono">${esc(
			done.machine.name
		)}</span></dd>
						<dt>${esc(__("Program"))}</dt><dd>${esc(done.program_name)}</dd>
						<dt>${esc(__("Sets in batch"))}</dt><dd class="tc-mono">${esc(done.sets.join(", "))}</dd>
					</dl>
					${this.printNoteHtml()}
				</div>
			</div>
		</section>`;
	}

	labelHtml() {
		const done = this.done;
		const line = (text, cls = "") => `<div${cls ? ` class="${cls}"` : ""}>${esc(text)}</div>`;
		return `<figure class="tc-label" aria-label="${esc(__("Label preview"))}">
			${
				done.qr_png_b64
					? `<img class="tc-label-dm tc-label-qr" src="data:image/png;base64,${esc(
							done.qr_png_b64
					  )}" alt="${esc(__("QR {0}", [done.batch]))}">`
					: ""
			}
			${line(done.batch, "tc-label-code")}
			${line(__("Wash batch"), "tc-label-strong")}
			${line(`${done.machine.equipment_name} - ${done.program_name}`)}
			${line(t2DateTime(done.at))}
			${line(__("{0} set(s)", [done.sets.length]))}
		</figure>`;
	}

	printNoteHtml() {
		const note = this.printNote;
		const print = this.done && this.done.print;
		if (!note || !print) return "";
		if (note.kind === "sending")
			return this.alertHtml({
				variant: "info",
				title: __("Sending the label to printer {0}...", [print.printer]),
			});
		if (note.kind === "sent") {
			return this.alertHtml({
				variant: "ok",
				title: __("Label sent to printer {0}.", [print.printer]),
				reason: __("Print job {0}", [print.print_job]),
			});
		}
		const warning = print.warning || {};
		return this.alertHtml({
			variant: "warn",
			title: __("Batch code kept - check the Station Agent, then print again"),
			reason: [warning.reason, __("Print job {0}", [print.print_job])]
				.filter(Boolean)
				.join(" "),
			action: warning.action || "",
		});
	}

	lookupHtml(batch) {
		const sets = batch.sets.map((row) => row.set_id).join(", ");
		const chemicals = batch.chemicals
			.map((row) => __("{0} lot {1}", [row.item, row.lot]))
			.join(", ");
		return `<section class="tc-t4-block tc-t2-lookup" aria-label="${esc(
			__("Wash batch lookup")
		)}">
			<h3>${esc(__("Wash batch lookup"))}</h3>
			<div class="tc-res-head">
				<b class="tc-code">${esc(batch.batch)}</b>
				${this.statusBadge(batch.status)}
			</div>
			<dl class="tc-res-grid">
				<dt>${esc(__("Washer"))}</dt><dd>${esc(
			batch.equipment.equipment_name
		)} <span class="tc-mono">${esc(batch.equipment.name)}</span></dd>
				<dt>${esc(__("Program"))}</dt><dd>${esc(batch.program.program_name)}</dd>
				<dt>${esc(__("Loaded at"))}</dt><dd>${esc(t2DateTime(batch.load_completed_at))} · ${esc(
			(batch.operator && (batch.operator.employee_name || batch.operator.name)) || "-"
		)}</dd>
				<dt>${esc(__("Sets in batch ({0})", [batch.sets.length]))}</dt><dd class="tc-mono">${esc(
			sets
		)}</dd>
				<dt>${esc(__("Chemicals"))}</dt><dd>${esc(chemicals || "-")}</dd>
				<dt>${esc(__("Cycle data"))}</dt><dd>${esc(this.dataText(batch))}</dd>
				${
					batch.cycle_result
						? `<dt>${esc(__("Result"))}</dt><dd>${esc(
								__(batch.cycle_result, null, "Wash Batch")
						  )}</dd>`
						: ""
				}
			</dl>
		</section>`;
	}

	statusBadge(status) {
		const variant = { Running: "", Passed: "g", Failed: "r" }[status] || "";
		return `<span class="tc-badge${variant ? " tc-badge-" + variant : ""}">${esc(
			__(status, null, "Wash Batch")
		)}</span>`;
	}

	dataText(batch) {
		if (!batch.data_source) return __("No cycle data yet");
		const text = batch.data_complete
			? __("Manual entry, confirmed")
			: __("Manual entry, incomplete");
		return batch.needs_review ? `${text} · ${__("Needs review")}` : text;
	}

	redoHtml() {
		const rows = (this.overview && this.overview.sets) || [];
		const body = rows.length
			? rows
					.map((row) =>
						this.alertHtml({
							variant: "warn",
							title: __("{0} - wash again, attempt {1}: scan it into a new batch.", [
								row.set_id,
								row.redo_count,
							]),
							reason: row.set_name || "",
						})
					)
					.join("")
			: `<p class="tc-empty">${esc(__("None."))}</p>`;
		return `<section class="tc-t4-block tc-t2-redo" aria-label="${esc(
			__("Reprocessing queue at T2")
		)}">
			<h3>${esc(__("Reprocessing queue at T2"))}</h3>
			${this.overview ? body : `<p class="tc-loading">${esc(__("Loading..."))}</p>`}
		</section>`;
	}

	// -- chế độ dỡ --
	runningHtml() {
		const rows = (this.overview && this.overview.running) || [];
		if (!this.overview) return `<p class="tc-loading">${esc(__("Loading..."))}</p>`;
		if (!rows.length) return `<p class="tc-empty">${esc(__("No running wash batch."))}</p>`;
		return rows
			.map(
				(row) => `<section class="tc-t4-block tc-t2-batch" data-batch="${esc(row.batch)}">
				<div class="tc-res-head">
					<b class="tc-code">${esc(row.batch)}</b>
					${this.statusBadge("Running")}
				</div>
				<p>${esc(
					__("Wash batch · {0} · {1}", [
						row.equipment_name || row.equipment,
						row.program_name || row.program,
					])
				)}
					<span class="tc-mono">${esc(row.equipment)}</span></p>
				<p>${esc(__("Sets in batch ({0}): {1}", [row.sets.length, row.sets.join(", ")]))}</p>
				${
					row.data_complete
						? `<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(
								__("Cycle data: confirmed manual entry")
						  )}</p>`
						: this.alertHtml({
								variant: "warn",
								title: __(
									"No cycle data yet - automatic data or a confirmed manual entry is needed before a Pass (BRU-REP-015)"
								),
						  })
				}
			</section>`
			)
			.join("");
	}

	unloadHtml() {
		const unload = this.unload;
		let html = `<section class="tc-t4-block">
			<h3>${esc(__("Running batches - unload: scan the washer QR code, then the batch QR code"))}</h3>
		</section>${this.runningHtml()}`;
		if (!unload) return html;
		if (unload.result) return html + this.resultSummaryHtml(unload.result);
		const scanned = `<section class="tc-t4-block tc-t2-unload">
			<h3>${esc(__("Unloading batch {0}", [unload.batch]))}</h3>
			<p>${esc(__("Washer QR code"))}: <b>${esc(
			unload.equipmentRaw ? __("Scanned") : __("Not scanned")
		)}</b> · ${esc(__("Batch QR code"))}: <b>${esc(
			unload.batchRaw ? __("Scanned") : __("Not scanned")
		)}</b></p>
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="t2-unload-reset">${esc(
				__("Choose another batch")
			)}</button></div>
		</section>`;
		html += scanned;
		const context = unload.context;
		if (!context) return html;
		html += context.data_complete
			? this.dataSummaryHtml(context)
			: this.manualFormHtml(context);
		if (context.data_complete) html += this.verdictHtml(context);
		return html;
	}

	manualFormHtml(context) {
		const form = this.form;
		const machine = context.equipment;
		const session = this.station.session || {};
		const params = (context.parameter_schema || [])
			.map((param, index) => {
				const value = form.values[param.parameter_name] || "";
				const review = this.paramState(param, value) === "review";
				const range = [
					Number(param.min_value) ? `≥ ${param.min_value}` : "",
					Number(param.max_value) ? `≤ ${param.max_value}` : "",
				]
					.filter(Boolean)
					.join(" · ");
				return `<div class="tc-field${review ? " is-review" : ""}">
					<label for="tc-t2-param-${index}">${esc(param.parameter_name)}${
					param.unit ? ` (${esc(param.unit)})` : ""
				}${param.required ? " *" : ""}${range ? ` · ${esc(range)}` : ""}</label>
					<input id="tc-t2-param-${index}" type="text" inputmode="decimal" autocomplete="off"
						data-param="${esc(param.parameter_name)}" value="${esc(value)}">
					<p class="tc-t2-review" ${review ? "" : "hidden"}><span aria-hidden="true">!</span> ${esc(
					__("Needs review")
				)}</p>
				</div>`;
			})
			.join("");
		const option = (value, label, current) =>
			`<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(
				label
			)}</option>`;
		const fileRequired = Boolean(machine.has_printout);
		return `<section class="tc-t4-block tc-t2-form">
			<h3>${esc(__("Manual cycle data for batch {0}", [context.batch]))}</h3>
			<div class="tc-t4-row">${params}</div>
			<div class="tc-t4-row">
				<div class="tc-field">
					<label for="tc-t2-alerts">${esc(__("Washer alerts observed"))}</label>
					<select id="tc-t2-alerts" data-form="alerts">
						${option("no", __("No"), form.alerts)}${option("yes", __("Yes - describe"), form.alerts)}
					</select>
					${
						form.alerts === "yes"
							? `<input type="text" data-form="alertsText" aria-label="${esc(
									__("Washer alerts observed")
							  )}" value="${esc(form.alertsText)}">`
							: ""
					}
				</div>
				<div class="tc-field">
					<label for="tc-t2-reported">${esc(__("Cycle result shown by the washer"))}</label>
					<select id="tc-t2-reported" data-form="reported">
						${option("", "-", form.reported)}${option(
			"Pass",
			__("Pass", null, "Step Gate Result"),
			form.reported
		)}${option("Fail", __("Fail", null, "Step Gate Result"), form.reported)}
					</select>
				</div>
				<div class="tc-field">
					<label for="tc-t2-started">${esc(__("Start time"))}</label>
					<input id="tc-t2-started" type="datetime-local" data-form="started" value="${esc(form.started)}">
				</div>
				<div class="tc-field">
					<label for="tc-t2-ended">${esc(__("End time"))}</label>
					<input id="tc-t2-ended" type="datetime-local" data-form="ended" value="${esc(form.ended)}">
				</div>
			</div>
			<div class="tc-field">
				<label for="tc-t2-file">${esc(__("Printout / chart photo"))}${
			fileRequired
				? ` * (${esc(__("required: this washer has a printout"))})`
				: ` (${esc(__("optional"))})`
		}</label>
				<input id="tc-t2-file" type="file" accept="image/*" capture="environment"${t2Disabled(
					form.uploading || this.offline
				)}>
				${
					form.file
						? `<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(
								__("Photo attached")
						  )}</p>`
						: ""
				}
			</div>
			<label class="tc-t2-confirm">
				<input type="checkbox" class="tc-check" data-form="confirmed"${form.confirmed ? " checked" : ""}>
				<span>${esc(
					__(
						"I, {0} {1}, confirm that the values above match the screen/printout of washer {2}.",
						[session.employee || "", session.employee_name || "", machine.name]
					)
				)}</span>
			</label>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="t2-save-data"${t2Disabled(
					Boolean(this.busy) || this.offline || form.uploading
				)}>${esc(__("Save manual data and confirm"))}</button>
			</div>
		</section>`;
	}

	dataSummaryHtml(context) {
		const data = context.machine_data || {};
		const rows = (data.parameters || [])
			.map(
				(row) =>
					`<dt>${esc(row.parameter_name)}</dt><dd>${esc(row.value)} ${esc(
						row.unit || ""
					)}${
						row.outside_range
							? ` <b class="tc-warn-text">! ${esc(__("Needs review"))}</b>`
							: ""
					}</dd>`
			)
			.join("");
		return `<section class="tc-t4-block tc-t2-data">
			<h3>${esc(__("Cycle data of batch {0}: confirmed manual entry", [context.batch]))}</h3>
			<dl class="tc-res-grid">${rows}</dl>
		</section>`;
	}

	verdictHtml(context) {
		const verdict = this.verdict || { result: "", clean: "", confirmed: false, pin: "" };
		const chip = (field, value, label) =>
			`<button type="button" class="tc-chip" data-action="t2-verdict" data-field="${field}" data-value="${value}"
				aria-pressed="${verdict[field] === value ? "true" : "false"}">${esc(label)}</button>`;
		const pass = __("Pass", null, "Step Gate Result");
		const fail = __("Fail", null, "Step Gate Result");
		const pin =
			this.oldMachine() && verdict.result === "Pass"
				? `<div class="tc-field">
					<label for="tc-t2-pin">${esc(__("R02 PIN (washer without connection or printout)"))}</label>
					<input id="tc-t2-pin" type="password" inputmode="numeric" maxlength="6" autocomplete="off"
						data-verdict="pin" value="">
					<p class="tc-hint">${esc(
						__(
							"R02 signs in with the card at this station and enters the 6-digit PIN."
						)
					)}</p>
				</div>`
				: "";
		const label =
			this.busy === T2_RESULT
				? __("Recording...")
				: __("Record the result for {0} set(s)", [context.sets.length]);
		return `<section class="tc-t4-block tc-t2-verdict">
			<h3>${esc(__("Cycle result (applies to every set)"))}</h3>
			<div class="tc-chips" role="group" aria-label="${esc(__("Cycle result (applies to every set)"))}">
				${chip("result", "Pass", pass)}${chip("result", "Fail", fail)}
			</div>
			<h3>${esc(__("Cleaning test"))}</h3>
			<div class="tc-chips" role="group" aria-label="${esc(__("Cleaning test"))}">
				${chip("clean", "Pass", pass)}${chip("clean", "Fail", fail)}
			</div>
			${pin}
			<label class="tc-t2-confirm">
				<input type="checkbox" class="tc-check" data-verdict="confirmed"${
					verdict.confirmed ? " checked" : ""
				}>
				<span>${esc(
					__("I confirm that the result above matches washer {0} for batch {1}.", [
						context.equipment.name,
						context.batch,
					])
				)}</span>
			</label>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="t2-record"${t2Disabled(
					Boolean(this.busy) || this.offline
				)}>${esc(label)}</button>
			</div>
		</section>`;
	}

	resultSummaryHtml(res) {
		const pass = res.result === "Pass";
		const rows = res.sets
			.map(
				(row) =>
					`<tr><td class="tc-mono">${esc(row.set_id)}</td><td>${esc(
						pass
							? __("Waiting for assembly")
							: __("Reprocess (wash again, attempt {0})", [row.redo_count])
					)}</td></tr>`
			)
			.join("");
		return `<section class="tc-t4-block tc-t2-result" data-result="${esc(res.result)}">
			${this.alertHtml(
				pass
					? {
							variant: "ok",
							title: __("Recorded Pass for {0} set(s) of batch {1}", [
								res.sets.length,
								res.batch,
							]),
					  }
					: {
							variant: "warn",
							title: __("Recorded Fail for {0} set(s) of batch {1}", [
								res.sets.length,
								res.batch,
							]),
							reason: __("Every set goes back to reprocessing."),
							action: __(
								"Marked as needing a nonconformity (automatic NC comes with FEAT-030)."
							),
					  }
			)}
			<table class="tc-t2-table">
				<thead><tr><th>${esc(__("Set ID"))}</th><th>${esc(__("Next step"))}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</section>`;
	}
}
