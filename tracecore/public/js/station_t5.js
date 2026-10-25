/* global uuid4, clientTs, esc */
// Màn T5 nạp mẻ tiệt khuẩn (SCR-09 STN, SCR-35 PDA, FEAT-022) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// Ô quét chính của shell luôn ở đầu và có focus: chế độ "Nạp mẻ" nhận QR máy, Cycle ID, mã HOAN-THANH-NAP và mã mẻ
// (tra cứu); chế độ "Nhập dữ liệu" nhận QR máy rồi QR mã mẻ. Danh sách gói đang nạp chỉ nằm trên kiosk
// (sessionStorage, A-16 Q1): server sinh mã mẻ ME- khi Hoàn thành nạp. Lỗi chặn = alert-error inline; RPC do shell
// gắn bearer trong body. Màn hẹp (≤ 480 px) chuyển surface sang PDA: một cột, nút full-width.

const T5_COMPLETE_CODE = "HOAN-THANH-NAP";
const T5_AGENT_URL = "http://127.0.0.1:8765/print";
const T5_AGENT_TIMEOUT_MS = 5000;
const T5_COMPLETE = "tracecore.v1.load.complete";
const T5_SAVE = "tracecore.v1.load.manual_data";
const T5_PDA_QUERY = "(max-width: 480px)";
// từ chối làm mẻ đang nhập dữ liệu không còn dùng được → bỏ trạng thái nhập để quét mẻ khác
const T5_DATA_RESET_CODES = ["LOAD_NOT_FOUND", "LOAD_NOT_OPEN", "STATION_WRONG_STEP"];

function t5Date(iso) {
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
	return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

function t5DateTime(iso) {
	const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(iso || "");
	return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : t5Date(iso);
}

function t5LocalInput(value) {
	// "YYYY-MM-DD HH:MM:SS" (giờ hệ thống) → giá trị ô datetime-local "YYYY-MM-DDTHH:MM"
	const m = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/.exec(value || "");
	return m ? `${m[1]}T${m[2]}` : "";
}

function t5SystemTimeZone() {
	// giờ trên form là giờ hệ thống (Asia/Ho_Chi_Minh), không theo múi giờ của trình duyệt: server coi chuỗi không có
	// offset là giờ hệ thống, và giờ bắt đầu của lô cũng là giờ hệ thống
	return (
		(frappe.boot && frappe.boot.time_zone && frappe.boot.time_zone.system) ||
		"Asia/Ho_Chi_Minh"
	);
}

function t5NowInput(date = new Date()) {
	const parts = {};
	new Intl.DateTimeFormat("en-CA", {
		timeZone: t5SystemTimeZone(),
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

function t5Disabled(flag) {
	return flag ? " disabled" : "";
}

function t5Kind(raw) {
	// phân loại sơ bộ trên kiosk; server luôn kiểm lại (gs1.parse_scan)
	const value = String(raw || "").toUpperCase();
	let m = /ME-\d{6}-\d{2}/.exec(value);
	if (m) return { kind: "load", id: m[0] };
	m = /TB-\d{4}/.exec(value);
	if (m) return { kind: "equipment", id: m[0] };
	return { kind: "pack", id: String(raw || "").trim() };
}

function t5GateLabel(step) {
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

function t5IndicatorLabel(code) {
	return (
		{
			chemical_class_5: __("Chemical indicator class 5"),
			bowie_dick: __("Bowie-Dick test of the day"),
			chemical_plasma: __("Plasma chemical indicator for each load"),
			biological: __("Biological indicator (quarantine until read)"),
		}[code] || code
	);
}

class T5Load {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.busy = null;
		this.offline = false;
		this.overview = null; // {running: mẻ đang chạy}
		this.overviewBusy = false;
		this.reset();
		this.load = this.restoreLoad();
		this.result.addEventListener("change", (event) => this.onChange(event));
		this.result.addEventListener("input", (event) => this.onInput(event));
		this.watchSurface();
	}

	get dialogOpen() {
		return false;
	}

	watchSurface() {
		// SCR-35: cùng màn trên PDA; bề rộng ≤ 480 px đặt surface PDA (một cột, nút full-width, chữ lớn)
		if (!window.matchMedia) return;
		const query = window.matchMedia(T5_PDA_QUERY);
		const apply = () => {
			this.station.root.dataset.surface = query.matches ? "PDA" : "STN";
		};
		apply();
		if (query.addEventListener) query.addEventListener("change", apply);
	}

	reset() {
		this.mode = "load";
		this.load = null; // {machine, programs, program, priority, packs: [{cycle_id, set_id, ...}]}
		this.done = null; // kết quả load.complete
		this.printNote = null;
		this.lookup = null;
		this.notice = null;
		this.data = null; // {load, equipmentRaw, loadRaw, context, saved}
		this.form = null;
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

	// ---- danh sách nạp trên kiosk (A-16 Q1) ----
	storageKey() {
		return `tc-t5-load:${this.station.station}`;
	}

	restoreLoad() {
		try {
			const raw = sessionStorage.getItem(this.storageKey());
			const load = raw ? JSON.parse(raw) : null;
			return load && load.machine && Array.isArray(load.packs) ? load : null;
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
		if (this.mode === "data") return this.dataScan(raw);
		if (raw.toUpperCase() === T5_COMPLETE_CODE) return this.complete();
		const code = t5Kind(raw);
		if (code.kind === "load") return this.lookupLoad(raw);
		if (code.kind === "equipment") {
			if (this.load && this.load.packs.length && this.load.machine.name !== code.id) {
				return this.blocked({
					title: __("Loading of sterilizer {0} is not finished", [
						this.load.machine.name,
					]),
					reason: __("{0} pack(s) are on the list for sterilizer {1}.", [
						this.load.packs.length,
						this.load.machine.name,
					]),
					action: __(
						"Complete loading or cancel it before scanning another sterilizer."
					),
				});
			}
			return this.request(
				"tracecore.v1.load.create",
				{ raw, station: this.station.station },
				(res) => this.onMachine(res)
			);
		}
		if (!this.load) {
			return this.blocked({
				title: __("Scan the sterilizer first"),
				reason: __("Code {0} was scanned before a sterilizer QR code.", [raw]),
				action: __("Scan the QR code on the sterilizer, then scan each pack."),
			});
		}
		const program = this.programRow();
		if (!program) {
			return this.blocked({
				title: __("Choose the program first"),
				reason: __("Sterilizer {0} has no active program.", [this.load.machine.name]),
				action: __("Ask R10 to add a program to the sterilizer."),
			});
		}
		return this.request(
			"tracecore.v1.load.add_pack",
			{
				raw,
				equipment: this.load.machine.name,
				program: program.program_code,
				queued: this.load.packs.map((row) => row.cycle_id),
				station: this.station.station,
			},
			(res) => this.onPack(res)
		);
	}

	lookupLoad(raw) {
		return this.request(
			"tracecore.v1.load.lookup",
			{ raw, station: this.station.station },
			(res) => {
				this.notice = null;
				this.lookup = res.load;
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
				reason: __("This account cannot work with sterilization loads at this station."),
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
		if (this.data && T5_DATA_RESET_CODES.includes(error.code) && method !== T5_COMPLETE)
			this.data = null;
		this.notice = { variant: "error", ...error };
		this.show();
	}

	// ---- nạp mẻ ----
	programRow() {
		if (!this.load) return null;
		return this.load.programs.find((row) => row.program_code === this.load.program) || null;
	}

	onMachine(res) {
		const programs = res.programs || [];
		this.load = {
			machine: res.equipment,
			programs,
			program: programs.length ? programs[0].program_code : null,
			priority: false,
			packs: [],
		};
		this.done = null;
		this.printNote = null;
		this.lookup = null;
		const max = res.equipment.max_packs;
		this.notice = {
			variant: "ok",
			title: __("Sterilizer {0} scanned · {1}", [
				res.equipment.name,
				res.equipment.equipment_name,
			]),
			reason: [
				max
					? __("Up to {0} pack(s) per load.", [max])
					: __("Capacity not set for this sterilizer."),
				res.equipment.is_connected
					? __(
							"API connected - automatic data comes with FEAT-024; enter data by hand with confirmation."
					  )
					: __("Not connected - enter the cycle data by hand with confirmation."),
			].join(" "),
		};
		this.saveLoad();
		this.show();
	}

	onPack(res) {
		if (res.duplicate) {
			this.notice = {
				variant: "info",
				title: __("{0} is already on the list", [res.cycle_id]),
			};
		} else {
			this.load.packs.push({
				cycle_id: res.cycle_id,
				set_id: res.set_id,
				set_name: res.set_name,
				method: res.method,
				pack_type_name: res.pack_type_name || res.pack_type,
				expiry: res.expiry,
				gates: res.gates || [],
			});
			this.notice = {
				variant: "ok",
				title: __("Scanned {0} into sterilizer {1} ({2} pack(s))", [
					res.cycle_id,
					this.load.machine.name,
					this.load.packs.length,
				]),
			};
			this.saveLoad();
		}
		this.done = null;
		this.lookup = null;
		this.show();
	}

	removePack(cycleId) {
		if (!this.load || this.busy) return;
		this.load.packs = this.load.packs.filter((row) => row.cycle_id !== cycleId);
		this.saveLoad();
		this.notice = { variant: "info", title: __("Removed {0} from the list", [cycleId]) };
		this.show();
	}

	cancelLoad() {
		if (this.busy) return;
		this.load = null;
		this.saveLoad();
		this.notice = {
			variant: "info",
			title: __("Loading cancelled; scan a sterilizer QR code to start again."),
		};
		this.show();
	}

	missing() {
		const out = [];
		if (this.offline) out.push(__("network connection"));
		if (!this.load) out.push(__("sterilizer"));
		if (!this.load || !this.load.packs.length) out.push(__("at least 1 pack"));
		if (this.load && !this.programRow()) out.push(__("program"));
		return out;
	}

	complete() {
		if (this.mode !== "load" || this.busy || this.missing().length) {
			if (this.mode === "load" && !this.busy && this.missing().length) {
				this.blocked({
					title: __("Loading cannot be completed yet"),
					reason: __("Missing: {0}", [this.missing().join(", ")]),
					action: __("Scan the sterilizer and the packs, then choose the program."),
				});
			}
			return;
		}
		const program = this.programRow();
		const load = this.load;
		this.request(
			T5_COMPLETE,
			{
				equipment: load.machine.name,
				program: program.program_code,
				packs: load.packs.map((row) => row.cycle_id),
				is_priority: load.priority ? 1 : 0,
				station: this.station.station,
			},
			(res) => {
				this.done = {
					...res,
					machine: load.machine,
					program_name: program.program_name,
					at: t5NowInput().replace("T", " "),
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
		const timer = setTimeout(() => controller.abort(), T5_AGENT_TIMEOUT_MS);
		try {
			const response = await fetch(T5_AGENT_URL, {
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

	// ---- bảng phụ: mẻ đang chạy ----
	async loadOverview(force = false) {
		if (this.overviewBusy || (this.overview && !force) || !this.station.session) return;
		if (this.station.isOffline()) return;
		const version = this.station.sessionVersion;
		this.overviewBusy = true;
		try {
			const res = await this.station.rpc("tracecore.v1.load.overview", {
				station: this.station.station,
				client_ts: clientTs(),
			});
			if (version !== this.station.sessionVersion) return;
			if (res && res.ok) this.overview = { running: res.running || [] };
		} catch (error) {
			if (error.sessionEnded) return;
		} finally {
			this.overviewBusy = false;
		}
		if (version === this.station.sessionVersion && !this.busy) this.show();
	}

	// ---- nhập dữ liệu chu trình ----
	setMode(mode) {
		if (this.busy || (mode !== "load" && mode !== "data")) return;
		this.mode = mode;
		this.notice = null;
		this.lookup = null;
		if (mode === "load") this.data = null;
		this.loadOverview(true);
		this.show();
		// nút đổi chế độ vừa bị render lại: trả focus về ô quét để mã quét ngay sau đó không bị mất
		this.station.focus(true);
	}

	openData(load) {
		if (this.busy) return;
		this.mode = "data";
		this.data = { load };
		this.form = null;
		this.notice = {
			variant: "info",
			title: __("Enter data for load {0}", [load]),
			reason: __("Scan the sterilizer QR code, then the load QR code."),
		};
		this.show();
		this.station.focus(true);
	}

	dataScan(raw) {
		const code = t5Kind(raw);
		if (code.kind === "pack") {
			return this.blocked({
				title: __("Invalid code"),
				reason: __(
					"Code {0} is not the sterilizer QR code or a sterilization load code.",
					[raw]
				),
				action: __("Scan the sterilizer QR code, then the load QR code."),
			});
		}
		const current = this.data && !this.data.saved ? this.data : null;
		let load = current && current.load;
		if (code.kind === "load" && load !== code.id) load = code.id;
		if (code.kind === "equipment" && !load) {
			const running = ((this.overview && this.overview.running) || []).filter(
				(row) => row.equipment === code.id
			);
			if (running.length !== 1) {
				return this.blocked({
					title: running.length
						? __("Sterilizer {0} has more than one open load", [code.id])
						: __("Sterilizer {0} has no open load", [code.id]),
					reason: __("The load cannot be chosen from the sterilizer QR code alone."),
					action: __("Scan the QR code on the sterilization load label."),
				});
			}
			load = running[0].load;
		}
		if (!current || current.load !== load) this.data = { load };
		this.request(
			"tracecore.v1.load.data_scan",
			{ load, raw, station: this.station.station },
			(res) => this.onDataScan(res, raw)
		);
	}

	onDataScan(res, raw) {
		const data = this.data;
		if (res.kind === "equipment") data.equipmentRaw = raw;
		else data.loadRaw = raw;
		this.lookup = null;
		if (data.equipmentRaw && data.loadRaw) return this.fetchContext();
		this.notice = {
			variant: "info",
			title:
				res.kind === "equipment"
					? __("Sterilizer QR code scanned for load {0}", [data.load])
					: __("Load QR code {0} scanned", [data.load]),
			reason:
				res.kind === "equipment"
					? __("Scan the load QR code next.")
					: __("Scan the sterilizer QR code next."),
		};
		this.show();
	}

	dataArgs() {
		return {
			load: this.data.load,
			equipment_raw: this.data.equipmentRaw,
			load_raw: this.data.loadRaw,
			station: this.station.station,
		};
	}

	fetchContext() {
		return this.request("tracecore.v1.load.data_context", this.dataArgs(), (res) => {
			const context = res.load;
			this.data.context = context;
			const values = {};
			(context.params || []).forEach((row) => {
				values[row.parameter_name] = String(row.value);
			});
			const alerts = context.machine_alerts && context.machine_alerts.text;
			this.form = {
				values,
				alerts: alerts ? "yes" : "no",
				alertsText: alerts || "",
				started: t5LocalInput(context.started_at),
				ended: t5LocalInput(context.ended_at) || t5NowInput(),
				file: context.machine_report || "",
				reason: context.manual_reason || "",
				uploading: false,
				confirmed: false,
				card: "",
			};
			this.notice = {
				variant: "ok",
				title: __("Scanned sterilizer QR {0} and load QR {1}", [
					context.equipment.name,
					context.load,
				]),
				reason: __("The data below is attached to all {0} pack(s) of the load.", [
					context.packs.length,
				]),
			};
			this.show();
		});
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
		if (!this.data || !this.data.context || this.busy || this.offline || this.form.uploading)
			return;
		const form = this.form;
		const schema = this.data.context.parameter_schema || [];
		const toServer = (value) => (value ? `${value.replace("T", " ")}:00` : null);
		this.request(
			T5_SAVE,
			{
				...this.dataArgs(),
				values: schema.map((param) => ({
					parameter_name: param.parameter_name,
					value: form.values[param.parameter_name] || null,
				})),
				started_at: toServer(form.started),
				ended_at: toServer(form.ended),
				confirmed: form.confirmed ? 1 : 0,
				card: form.card || "",
				machine_alerts: form.alerts === "yes" ? form.alertsText || __("Yes") : null,
				machine_report: form.file || null,
				reason: form.reason || null,
			},
			(res) => {
				this.data = { load: this.data.load, context: this.data.context, saved: res };
				this.form = null;
				this.notice = {
					variant: res.needs_review ? "warn" : "ok",
					title: __("Manual cycle data saved and confirmed"),
					reason: res.needs_review
						? __("Some values are outside the program range: Needs review by R02.")
						: "",
				};
				this.loadOverview(true);
				this.show();
			}
		);
	}

	missingLabel(item) {
		return (
			{
				ended_at: __("end time (not before the start time)"),
				printout: __("photo of the printout"),
				reason: __("reason for entering the data by hand"),
				confirmation: __("confirmation tick"),
				card: __("operator card scan"),
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

	// ---- sự kiện trên màn ----
	onAction(action, button) {
		const data = (button && button.dataset) || {};
		const handlers = {
			retry: () => this.retry(),
			"t5-mode": () => this.setMode(data.mode),
			"t5-release": () => this.openRelease(),
			"t5-remove": () => this.removePack(data.pack),
			"t5-complete": () => this.complete(),
			"t5-cancel": () => this.cancelLoad(),
			"t5-open-data": () => this.openData(data.load),
			"t5-save-data": () => this.saveData(),
			"t5-data-reset": () => {
				this.data = null;
				this.form = null;
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
		if (target.id === "tc-t5-program" && this.load) {
			// đổi chương trình xóa danh sách đã quét: tương thích phải kiểm lại theo chương trình mới (mockup t5)
			this.load.program = target.value;
			this.load.packs = [];
			this.saveLoad();
			this.show();
		} else if (target.id === "tc-t5-priority" && this.load) {
			this.load.priority = target.checked;
			this.saveLoad();
		} else if (target.id === "tc-t5-file") {
			this.uploadFile(target);
		} else if (target.dataset.form && this.form) {
			const field = target.dataset.form;
			this.form[field] = target.type === "checkbox" ? target.checked : target.value;
			if (field === "alerts") this.show();
		}
	}

	onInput(event) {
		const target = event.target;
		if (target.dataset.param && this.form) {
			this.form.values[target.dataset.param] = target.value;
			const param = (this.data.context.parameter_schema || []).find(
				(row) => row.parameter_name === target.dataset.param
			);
			const state = param ? this.paramState(param, target.value) : "";
			const field = target.closest(".tc-field");
			field.classList.toggle("is-review", state === "review");
			field.querySelector(".tc-t5-review").hidden = state !== "review";
		} else if (target.dataset.form && this.form && target.type !== "checkbox") {
			this.form[target.dataset.form] = target.value;
		}
	}

	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	viewState() {
		if (this.offline && !this.load && !this.data && !this.done) return "offline";
		if (this.notice && this.notice.variant === "error") return "error";
		const idle =
			this.mode === "load" && !this.load && !this.done && !this.lookup && !this.notice;
		return idle ? "empty" : "result";
	}

	show() {
		if (!this.station.session) return;
		this.updatePlaceholder();
		if (!this.overview) this.loadOverview();
		const body = this.mode === "data" ? this.dataHtml() : this.loadHtml();
		this.station.setState(
			this.viewState(),
			`<div class="tc-t2 tc-t5" data-mode="${esc(this.mode)}">
				${this.modeHtml()}
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.lookup ? this.lookupHtml(this.lookup) : ""}
				${body}
				${this.mode === "load" ? this.runningHtml() : ""}
				${this.mode === "load" ? this.loadBarHtml() : ""}
			</div>`
		);
		const error = Boolean(this.notice && this.notice.variant === "error");
		this.station.form.classList.toggle("is-error", error);
		if (error && this.shownNotice !== this.notice) window.scrollTo({ top: 0 });
		this.shownNotice = this.notice;
	}

	updatePlaceholder() {
		let text = __("Scan the sterilizer QR code...");
		if (this.mode === "data")
			text = __("Scan the sterilizer QR code, then the load QR code...");
		else if (this.load)
			text = __("Scan each Cycle ID into the sterilizer... (scan HOAN-THANH-NAP when done)");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	modeHtml() {
		const open = (this.overview && this.overview.running.length) || 0;
		const chip = (mode, label) =>
			`<button type="button" class="tc-chip" data-action="t5-mode" data-mode="${mode}"
				aria-pressed="${this.mode === mode ? "true" : "false"}">${esc(label)}</button>`;
		return `<div class="tc-chips" role="group" aria-label="${esc(__("Sterilization load"))}">
			${chip("load", __("Load sterilizer"))}
			${chip("data", __("Cycle data ({0} open)", [open]))}
			<button type="button" class="tc-chip" data-action="t5-release" aria-pressed="false">${esc(
				__("Unload and release")
			)}</button>
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
		if (item.cycle_id) return `${item.cycle_id}: ${item.reason || item.code || ""}`;
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
					"Sterilization loads need a network connection; offline work comes with FEAT-009."
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
			<small>${esc(label || t5GateLabel(step))}</small>
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

	indicatorsText(program) {
		return ((program && program.indicators) || [])
			.map((code) => t5IndicatorLabel(code))
			.join(" · ");
	}

	// -- chế độ nạp --
	loadHtml() {
		let html = "";
		if (this.done) html += this.doneHtml();
		const load = this.load;
		if (!load) {
			return `${html}<section class="tc-t4-block tc-t2-start">
				<h3>${esc(__("Load sterilizer - scan the sterilizer QR code first, then scan each pack"))}</h3>
				<p class="tc-empty">${esc(
					__(
						"Only packs that passed T4 and fit the program are accepted (BRU-FLOW-004, BRU-REP-004)."
					)
				)}</p>
			</section>`;
		}
		const program = this.programRow();
		const programOptions = load.programs
			.map(
				(row) =>
					`<option value="${esc(row.program_code)}"${
						row.program_code === load.program ? " selected" : ""
					}>${esc(row.program_name)} (${esc(row.program_code)})</option>`
			)
			.join("");
		const max = load.machine.max_packs;
		const rows = load.packs
			.map(
				(row) => `<li class="tc-t5-pack">
					<div class="tc-t5-pack-id"><span class="tc-mono">${esc(row.cycle_id)}</span>
						<span>${esc(row.set_id)} · ${esc(row.set_name || "-")}</span></div>
					<div>${esc(__(row.method, null, "Pack"))} · ${esc(row.pack_type_name || "-")} · ${esc(
					__("Expires {0}", [t5Date(row.expiry)])
				)}</div>
					${this.gatesHtml(row.gates)}
					<button type="button" class="tc-btn tc-btn-secondary" data-action="t5-remove"
						data-pack="${esc(row.cycle_id)}"${t5Disabled(Boolean(this.busy))}>${esc(
					__("Remove from the list")
				)}</button>
				</li>`
			)
			.join("");
		const list = load.packs.length
			? `<ul class="tc-t5-packs">${rows}</ul>`
			: `<p class="tc-empty">${esc(
					__(
						"Only packs that passed T4 and fit the program are accepted (BRU-FLOW-004, BRU-REP-004)."
					)
			  )}</p>`;
		return `${html}<section class="tc-t4-block tc-t2-machine">
				<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(
					__("Sterilizer {0} scanned · {1}", [
						load.machine.name,
						load.machine.equipment_name,
					])
				)} · ${esc(
			load.machine.is_connected
				? __("API connected - automatic data comes with FEAT-024")
				: __("not connected - enter the cycle data by hand with confirmation")
		)}</p>
				<div class="tc-t4-row">
					<div class="tc-field">
						<label for="tc-t5-program">${esc(__("Program"))}</label>
						<select id="tc-t5-program">${programOptions}</select>
					</div>
					<div class="tc-field">
						<span class="tc-t5-label">${esc(__("Indicators for this program"))}</span>
						<p>${esc(this.indicatorsText(program) || "-")}</p>
					</div>
				</div>
				<label class="tc-t2-confirm"><input type="checkbox" id="tc-t5-priority"${
					load.priority ? " checked" : ""
				}> ${esc(__("Priority load"))}</label>
			</section>
			<section class="tc-t4-block tc-t2-sets">
				<h3>${esc(
					__(
						"Packs scanned into sterilizer {0} ({1}{2}) - the load code is generated at Complete loading",
						[load.machine.name, load.packs.length, max ? `/${max}` : ""]
					)
				)}</h3>
				${list}
			</section>`;
	}

	loadBarHtml() {
		if (!this.load) return "";
		const missing = this.missing();
		const label =
			this.busy === T5_COMPLETE
				? __("Recording...")
				: __("Complete loading → generate load code");
		return `<div class="tc-actionsbar">
			<button type="button" class="tc-btn tc-btn-primary" data-action="t5-complete"${t5Disabled(
				missing.length > 0 || Boolean(this.busy)
			)}>${esc(label)}</button>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="t5-cancel"${t5Disabled(
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
						title: __("{0} pack(s) were not loaded", [done.rejected.length]),
						items: done.rejected,
						action: __("Take these packs out of the sterilizer load and check them."),
				  })
				: "";
		return `<section class="tc-t4-block tc-t4-done tc-t2-done">
			${this.alertHtml({
				variant: "ok",
				title: __("Load code generated for {0} pack(s)", [done.packs.length]),
			})}
			<p class="tc-cycle">${esc(done.load)}</p>
			${rejected}
			<div class="tc-t4-done-grid">
				${this.labelHtml()}
				<div>
					<dl class="tc-res-grid">
						<dt>${esc(__("Sterilizer"))}</dt><dd>${esc(
			done.machine.equipment_name
		)} <span class="tc-mono">${esc(done.machine.name)}</span></dd>
						<dt>${esc(__("Program"))}</dt><dd>${esc(done.program_name)}</dd>
						<dt>${esc(__("Packs in load"))}</dt><dd class="tc-mono">${esc(done.packs.join(", "))}</dd>
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
					  )}" alt="${esc(__("QR {0}", [done.load]))}">`
					: ""
			}
			${line(done.load, "tc-label-code")}
			${line(__("Sterilization load"), "tc-label-strong")}
			${line(`${done.machine.equipment_name} - ${done.program_name}`)}
			${line(t5DateTime(done.at))}
			${line(__("{0} pack(s)", [done.packs.length]))}
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
			title: __("Load code kept - check the Station Agent, then print again"),
			reason: [warning.reason, __("Print job {0}", [print.print_job])]
				.filter(Boolean)
				.join(" "),
			action: warning.action || "",
		});
	}

	statusBadge(status) {
		const variant = {
			Running: "",
			"Cycle Complete": "g",
			Quarantine: "o",
			Released: "g",
			Failed: "r",
		}[status];
		return `<span class="tc-badge${variant ? " tc-badge-" + variant : ""}">${esc(
			__(status, null, "Sterilization Load")
		)}</span>`;
	}

	dataText(load) {
		if (!load.data_source) return __("No cycle data yet");
		const text = load.data_complete
			? __("Manual entry, confirmed")
			: __("Manual entry, incomplete");
		return load.needs_review ? `${text} · ${__("Needs review")}` : text;
	}

	lookupHtml(load) {
		const packs = load.packs.map((row) => `${row.cycle_id} (${row.set_id})`).join(", ");
		return `<section class="tc-t4-block tc-t2-lookup" aria-label="${esc(
			__("Sterilization load lookup")
		)}">
			<h3>${esc(__("Sterilization load lookup"))}</h3>
			<div class="tc-res-head">
				<b class="tc-code">${esc(load.load)}</b>
				${this.statusBadge(load.status)}
			</div>
			<dl class="tc-res-grid">
				<dt>${esc(__("Sterilizer"))}</dt><dd>${esc(
			load.equipment.equipment_name
		)} <span class="tc-mono">${esc(load.equipment.name)}</span></dd>
				<dt>${esc(__("Program"))}</dt><dd>${esc(load.program.program_name)}</dd>
				<dt>${esc(__("Indicators for this program"))}</dt><dd>${esc(this.indicatorsText(load) || "-")}</dd>
				<dt>${esc(__("Loaded at"))}</dt><dd>${esc(t5DateTime(load.load_completed_at))} · ${esc(
			(load.operator && (load.operator.employee_name || load.operator.name)) || "-"
		)}</dd>
				<dt>${esc(__("Packs in load ({0})", [load.packs.length]))}</dt><dd class="tc-mono">${esc(
			packs
		)}</dd>
				<dt>${esc(__("Cycle data"))}</dt><dd>${esc(this.dataText(load))}</dd>
			</dl>
		</section>`;
	}

	// -- mẻ đang chạy (thẻ + nút nhập dữ liệu) --
	runningHtml() {
		const rows = (this.overview && this.overview.running) || [];
		const body = !this.overview
			? `<p class="tc-loading">${esc(__("Loading..."))}</p>`
			: rows.length
			? rows
					.map(
						(row) => `<section class="tc-t4-block tc-t2-batch" data-load="${esc(
							row.load
						)}">
				<div class="tc-res-head">
					<b class="tc-code">${esc(row.load)}</b>
					${this.statusBadge(row.status)}
				</div>
				<p>${esc(
					__("Sterilization load · {0} · {1}", [
						row.equipment_name || row.equipment,
						row.program_name || row.program,
					])
				)} <span class="tc-mono">${esc(row.equipment)}</span></p>
				<p>${esc(__("Packs in load ({0})", [row.packs.length]))}: <span class="tc-mono">${esc(
							row.packs.join(", ")
						)}</span></p>
				${
					row.data_complete
						? `<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(
								__("Cycle data: confirmed manual entry")
						  )}${row.needs_review ? " · " + esc(__("Needs review")) : ""}</p>`
						: this.alertHtml({
								variant: "warn",
								title: __(
									"No cycle data yet - enter it by hand with confirmation when the cycle ends"
								),
						  })
				}
				<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="t5-open-data"
					data-load="${esc(row.load)}"${t5Disabled(Boolean(this.busy))}>${esc(
							__("Enter cycle data")
						)}</button></div>
			</section>`
					)
					.join("")
			: `<p class="tc-empty">${esc(__("No open sterilization load."))}</p>`;
		return `<section class="tc-t4-block tc-t2-redo" aria-label="${esc(
			__("Open sterilization loads")
		)}">
			<h3>${esc(__("Open sterilization loads"))}</h3>
			${body}
		</section>`;
	}

	// -- chế độ nhập dữ liệu --
	dataHtml() {
		const data = this.data;
		let html = this.runningHtml();
		if (!data) {
			return `<section class="tc-t4-block">
				<h3>${esc(__("Cycle data - scan the sterilizer QR code, then the load QR code"))}</h3>
			</section>${html}`;
		}
		if (data.saved) return html + this.savedHtml(data.saved);
		html = `<section class="tc-t4-block tc-t2-unload">
			<h3>${esc(__("Entering data for load {0}", [data.load]))}</h3>
			<p>${esc(__("Sterilizer QR code"))}: <b>${esc(
			data.equipmentRaw ? __("Scanned") : __("Not scanned")
		)}</b> · ${esc(__("Load QR code"))}: <b>${esc(
			data.loadRaw ? __("Scanned") : __("Not scanned")
		)}</b></p>
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="t5-data-reset">${esc(
				__("Choose another load")
			)}</button></div>
		</section>`;
		if (!data.context || !this.form) return html;
		return html + this.formHtml();
	}

	savedHtml(saved) {
		return `<section class="tc-t4-block">
			${this.alertHtml({
				variant: saved.needs_review ? "warn" : "ok",
				title: __("Cycle data attached to the load"),
				reason: __("The load is now {0}.", [__(saved.status, null, "Sterilization Load")]),
			})}
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="t5-data-reset">${esc(
				__("Done")
			)}</button></div>
		</section>`;
	}

	formHtml() {
		const context = this.data.context;
		const form = this.form;
		const machine = context.equipment;
		const fields = (context.parameter_schema || [])
			.map((param) => {
				const state = this.paramState(param, form.values[param.parameter_name]);
				const low = Number(param.min_value) || 0;
				const high = Number(param.max_value) || 0;
				let range = "";
				if (low && high) range = `${low} – ${high}`;
				else if (low) range = `≥ ${low}`;
				else if (high) range = `≤ ${high}`;
				return `<div class="tc-field${state === "review" ? " is-review" : ""}">
					<label for="tc-t5-param-${esc(param.parameter_name)}">${esc(param.parameter_name)}${
					param.unit ? ` (${esc(param.unit)})` : ""
				}${Number(param.required) ? " *" : ""}${range ? ` · ${esc(range)}` : ""}</label>
					<input id="tc-t5-param-${esc(
						param.parameter_name
					)}" type="text" inputmode="decimal" autocomplete="off"
						data-param="${esc(param.parameter_name)}" value="${esc(form.values[param.parameter_name] || "")}">
					<p class="tc-t5-review tc-t2-review"${state === "review" ? "" : " hidden"}>${esc(
					__("Outside the program range - Needs review")
				)}</p>
				</div>`;
			})
			.join("");
		const photo = machine.has_printout
			? __("Photo of the printout (required for this sterilizer)")
			: __("Photo of the printout (optional)");
		const reason = machine.is_connected
			? `<div class="tc-field">
					<label for="tc-t5-reason">${esc(__("Why is the data entered by hand?"))} *</label>
					<textarea id="tc-t5-reason" data-form="reason" rows="2">${esc(form.reason)}</textarea>
				</div>`
			: "";
		const session = this.station.session || {};
		const who =
			[session.employee, session.employee_name].filter(Boolean).join(" ") || __("operator");
		return `<section class="tc-t4-block tc-t2-form">
			<h3>${esc(__("Manual cycle data - confirmed by the operator"))}</h3>
			<div class="tc-t4-row">${fields}</div>
			<div class="tc-t4-row">
				<div class="tc-field">
					<label for="tc-t5-started">${esc(__("Started at"))}</label>
					<input id="tc-t5-started" type="datetime-local" data-form="started" value="${esc(form.started)}">
				</div>
				<div class="tc-field">
					<label for="tc-t5-ended">${esc(__("Ended at"))} *</label>
					<input id="tc-t5-ended" type="datetime-local" data-form="ended" value="${esc(form.ended)}">
				</div>
			</div>
			<div class="tc-field">
				<label for="tc-t5-alerts">${esc(__("Machine alerts observed"))}</label>
				<select id="tc-t5-alerts" data-form="alerts">
					<option value="no"${form.alerts === "no" ? " selected" : ""}>${esc(__("None"))}</option>
					<option value="yes"${form.alerts === "yes" ? " selected" : ""}>${esc(
			__("Yes - describe")
		)}</option>
				</select>
				${
					form.alerts === "yes"
						? `<input type="text" data-form="alertsText" aria-label="${esc(
								__("Machine alerts observed")
						  )}" value="${esc(form.alertsText)}">`
						: ""
				}
			</div>
			<div class="tc-field">
				<label for="tc-t5-file">${esc(photo)}</label>
				<input id="tc-t5-file" type="file" accept="image/*" capture="environment">
				${
					form.uploading
						? `<p class="tc-loading">${esc(__("Loading..."))}</p>`
						: form.file
						? `<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(
								form.file
						  )}</p>`
						: ""
				}
			</div>
			${reason}
			<label class="tc-t2-confirm"><input type="checkbox" data-form="confirmed"${
				form.confirmed ? " checked" : ""
			}> ${esc(
			__(
				"I, {0}, confirm the values above match the screen or printout of sterilizer {1}.",
				[who, machine.name]
			)
		)}</label>
			<div class="tc-field">
				<label for="tc-t5-card">${esc(__("Scan your employee card to confirm"))} *</label>
				<input id="tc-t5-card" type="password" autocomplete="off" data-form="card" value="${esc(
					form.card
				)}">
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="t5-save-data"${t5Disabled(
					Boolean(this.busy) || this.offline || form.uploading
				)}>${esc(
			this.busy === T5_SAVE ? __("Recording...") : __("Save manual data and confirm")
		)}</button>
			</div>
		</section>`;
	}
}
