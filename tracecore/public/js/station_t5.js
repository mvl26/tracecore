/* global tcPdfRetryButton, tcPrintLabelPdf, tcErrorTitle, tcGuideButton, tcIsSetOrPackCode, tcPackLabel, tcPackLabelHtml */
/* global uuid4, clientTs, esc */
// Màn T5 nạp mẻ tiệt khuẩn (SCR-09 STN, SCR-35 PDA, FEAT-022) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// Ô quét chính của shell luôn ở đầu và có focus: chế độ "Nạp mẻ" nhận QR máy, Cycle ID, mã HOAN-THANH-NAP và mã mẻ
// (tra cứu); chế độ "Nhập dữ liệu" nhận QR máy rồi QR mã mẻ. Danh sách gói đang nạp chỉ nằm trên kiosk
// (sessionStorage, A-16 Q1): server sinh mã mẻ ME- khi Hoàn thành nạp. Lỗi chặn = alert-error inline; RPC do shell
// gắn bearer trong body. Màn hẹp (≤ 480 px) chuyển surface sang PDA: một cột, nút full-width.

const T5_COMPLETE_CODE = "HOAN-THANH-NAP";
const T5_COMPLETE = "tracecore.v1.load.complete";
const T5_SAVE = "tracecore.v1.load.manual_data";
const T5_PDA_QUERY = "(max-width: 480px)";
const T5_LOOKUP = "tracecore.v1.lookup.batches";
// từ chối làm mẻ đang nhập dữ liệu không còn dùng được → bỏ trạng thái nhập để quét mẻ khác
const T5_DATA_RESET_CODES = [
	"LOAD_NOT_FOUND",
	"LOAD_NOT_OPEN",
	"LOAD_ALREADY_RELEASED",
	"STATION_WRONG_STEP",
];

// Mẻ đã giải phóng là thông báo, không phải lỗi: không tô đỏ, không nút gọi giám sát
function t5RejectNotice(error) {
	return { variant: error.code === "LOAD_ALREADY_RELEASED" ? "info" : "error", ...error };
}

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

// Mã bộ/gói quét ở bước cần mã mẻ (ticket 1819), dùng chung tab dữ liệu chu trình, dỡ mẻ, đọc BI
function t5SetCodeNotice(raw) {
	return {
		title: __("This is an instrument set code - please scan the load code (ME-...)"),
		reason: __("Code {0} is a set or pack code; unloading works on the whole load.", [raw]),
		action: __("Scan the QR code on the sterilization load label."),
	};
}

function t5GateLabel(step) {
	return (window.tcGateLabels || {})[step] || step;
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

// A-84: trạng thái máy theo mẻ chưa dỡ, dùng chung ở mọi tab của T5
function t5MachineState(status, load, unloaded) {
	if (unloaded) return __("Waiting for release - {0}", [load]);
	return status === "Running"
		? __("Running - {0}", [load])
		: status === "Cycle Complete"
		? __("Waiting to unload - {0}", [load])
		: load;
}

// A-103: bước mặc định suy từ dữ liệu mẻ, không lưu theo tab. Máy đã xong cần dỡ trước, rồi đến mẻ chờ BI, rồi mẻ còn chạy.
function t5DefaultStep({ draft, unload = [], bi = [], canLoad = true, canUnload = true }) {
	if (draft) return 1;
	if (canUnload) {
		if (unload.some((row) => row.status !== "Running" || row.unloaded)) return 2;
		if (bi.length) return 3;
		if (unload.length) return 2;
	}
	return canLoad ? 1 : 2;
}

// Thanh bước 1-2-3 (A-103): luôn có chữ và ký hiệu, bấm được để quay lại bước trước hoặc sang bước có mẻ đang chờ
function t5StepsHtml(current, hub = {}) {
	const can = (name) => !hub[name] || hub[name]();
	const queues = hub.queues;
	const steps = [
		{ label: __("Load sterilizer"), enabled: can("canLoad") },
		{ label: __("Unload and release"), enabled: true, count: queues && queues.unload.length },
		{ label: __("Read BI"), enabled: can("canUnload"), count: queues && queues.bi.length },
	];
	const buttons = steps
		.map((step, index) => {
			const number = index + 1;
			const state =
				number === current ? "is-current" : number < current ? "is-done" : "is-pending";
			return `<button type="button" class="tc-t5-step ${state}" data-action="t5-step" data-step="${number}"${
				number === current ? ' aria-current="step"' : ""
			}${step.enabled ? "" : " disabled"}>${
				number < current ? '<span aria-hidden="true">&#10003; </span>' : ""
			}${number}. ${esc(step.label)}${step.count ? ` (${esc(step.count)})` : ""}</button>`;
		})
		.join("");
	return `<div class="tc-t5-steps" data-region="t5-steps" role="group" aria-label="${esc(
		__("Sterilization load")
	)}">${buttons}<button type="button" class="tc-btn tc-btn-secondary tc-t5-daily" data-action="t5-daily-test">${esc(
		__("Daily test")
	)}</button></div>`;
}

function t5InstructionHtml(text) {
	return `<p class="tc-t5-instruction">${esc(text)}</p>`;
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
		this.queues = null; // {unload, bi}: mẻ theo trạng thái, nguồn của bước mặc định và danh sách chọn nhanh
		this.queuesBusy = false;
		this.queuesError = false;
		this.stepSettled = false; // đã vào bước mặc định hoặc người dùng đã thao tác
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
		this.mode = this.canLoad() ? "load" : "data";
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
		this.queues = null;
		this.queuesBusy = false;
		this.queuesAgain = false;
		this.queuesError = false;
		this.stepSettled = false;
		this.reset();
		if (this.releaseScreen) {
			this.releaseScreen.pending = null;
			this.releaseScreen.busy = null;
			this.releaseScreen.offline = false;
			this.releaseScreen.reset();
		}
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
		this.stepSettled = true;
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
				queued: this.load.packs
					.filter((row) => !row.incompatible)
					.map((row) => row.cycle_id),
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
		this.queuesError = false;
		this.loadQueues(true);
		if (this.mode === "data") this.loadOverview(true);
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
		this.notice = t5RejectNotice(error);
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
			// A-83: chương trình mặc định của máy, không có thì chương trình đầu (danh sách không có chương trình test)
			program:
				res.equipment.default_program ||
				(programs.length ? programs[0].program_code : null),
			priority: false,
			packs: [],
		};
		this.done = null;
		this.printNote = null;
		this.lookup = null;
		this.notice = null; // xác nhận máy chỉ một dòng, ở khối máy bên dưới (ticket 1844)
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
				department_name: res.department_name,
				method: res.method,
				pack_type_name: res.pack_type_name || res.pack_type,
				expiry: res.expiry,
				gates: res.gates || [],
			});
			this.notice = {
				variant: "ok",
				title: __("Scanned {0} into sterilizer {1} ({2} pack(s))", [
					tcPackLabel(res),
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
		// bỏ một gói có thể trả lại dung tích cho gói đang bị đánh dấu
		if (this.load.packs.some((row) => row.incompatible)) this.recheckPacks();
	}

	// Đổi chương trình (ticket 1844): giữ gói đã quét, kiểm lại từng gói; gói không hợp đánh dấu đỏ kèm lý do
	recheckPacks() {
		const program = this.programRow();
		if (!this.load || !this.load.packs.length || !program) return;
		this.load.rechecking = true;
		this.saveLoad();
		this.request(
			"tracecore.v1.load.recheck",
			{
				equipment: this.load.machine.name,
				program: program.program_code,
				packs: this.load.packs.map((row) => row.cycle_id),
				station: this.station.station,
			},
			(res) => this.onRecheck(res)
		);
		this.show();
	}

	onRecheck(res) {
		if (!this.load) return;
		const rows = {};
		(res.packs || []).forEach((row) => {
			rows[row.cycle_id] = row;
		});
		this.load.packs.forEach((pack) => {
			const row = rows[pack.cycle_id];
			pack.incompatible = row && !row.ok ? { code: row.code, reason: row.reason } : null;
		});
		this.load.rechecking = false;
		const bad = this.load.packs.filter((row) => row.incompatible).length;
		this.notice = bad
			? {
					variant: "warn",
					title: __("{0} pack(s) do not fit the new program", [bad]),
					action: __("Remove the packs marked in red, or choose another program."),
			  }
			: {
					variant: "ok",
					title: __("All {0} pack(s) still fit the new program", [
						this.load.packs.length,
					]),
			  };
		this.saveLoad();
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
		if (this.load && this.load.rechecking)
			out.push(__("check of the packs against the program"));
		if (this.load && this.load.packs.some((row) => row.incompatible))
			out.push(__("removing the packs marked in red"));
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
				this.stepSettled = true;
				// A-103: nạp xong thì sang bước dỡ với đúng mẻ này; trạm chỉ có chức năng nạp ở lại, thẻ mã mẻ vẫn hiện
				if (this.canUnload())
					this.openRelease({
						load: res.load,
						equipment: load.machine.name,
						reason: __("Load known from the previous step, no scan"),
					});
				else this.loadQueues(true);
				this.handlePrint(res.print);
			}
		);
	}

	// A-101: có máy in thì nhãn ra file PDF, không qua Station Agent; chưa có máy in thì giữ Waiting và cảnh báo
	async handlePrint(print) {
		if (print && print.status === "Queued") return this.printLabelPdf();
		this.printNote = { kind: "waiting" };
		this.show();
	}

	async printLabelPdf() {
		if (!this.done || (this.printNote && this.printNote.kind === "sending")) return;
		const version = this.station.sessionVersion;
		this.printNote = { kind: "sending" };
		this.show();
		const result = await tcPrintLabelPdf(this.station, "tracecore.v1.load.label_pdf", {
			load: this.done.load,
			station: this.station.station,
		});
		if (result.ended || version !== this.station.sessionVersion) return;
		this.printNote = result.ok
			? { kind: "pdf", filename: result.filename }
			: { kind: "pdf-failed", reason: result.reason };
		this.show();
	}

	// ---- các bước (A-103) ----
	async loadQueues(force = false) {
		if (!this.station.session || this.station.isOffline()) return;
		if (this.queuesBusy) {
			if (force) this.queuesAgain = true;
			return;
		}
		if (this.queues && !force) return;
		const version = this.station.sessionVersion;
		this.queuesBusy = true;
		const read = (purpose) =>
			this.station.rpc(T5_LOOKUP, {
				station: this.station.station,
				screen: "sterilize",
				purpose,
				page_length: 50,
				client_ts: clientTs(),
			});
		let failed = false;
		try {
			const [unload, bi] = await Promise.all([read("unload"), read("bi")]);
			if (version !== this.station.sessionVersion) return;
			if (unload && unload.ok && bi && bi.ok) {
				this.queues = { unload: unload.items || [], bi: bi.items || [] };
				this.queuesError = false;
			} else failed = true;
		} catch (error) {
			if (error.sessionEnded || version !== this.station.sessionVersion) return;
			failed = true;
		} finally {
			this.queuesBusy = false;
		}
		if (failed) this.queuesError = true;
		if (this.queuesAgain) {
			this.queuesAgain = false;
			return this.loadQueues(true);
		}
		this.onQueues();
	}

	onQueues() {
		if (!this.stepSettled && this.queues) {
			this.stepSettled = true;
			const idle = !this.load && !this.done && !this.notice && !this.busy && !this.data;
			const step = t5DefaultStep({
				draft: Boolean(this.load),
				unload: this.queues.unload,
				bi: this.queues.bi,
				canLoad: this.canLoad(),
				canUnload: this.canUnload(),
			});
			if (idle && step !== 1 && this.station.screen === this) return this.goStep(step);
		}
		this.repaintSteps();
	}

	// Không vẽ lại cả màn khi người dùng đang nhập: PIN, thẻ, chương trình giữ nguyên, chỉ cập nhật số mẻ trên thanh bước
	repaintSteps() {
		const screen = this.station.screen || this;
		const release = this.releaseScreen;
		if (screen !== this && screen !== release) return;
		const typing =
			screen === this ? this.load || this.form || this.busy : release.ctx || release.busy;
		if (!typing) return screen.show();
		const node = this.result.querySelector('[data-region="t5-steps"]');
		if (node) node.outerHTML = t5StepsHtml(screen.currentStep(), this);
	}

	currentStep() {
		return this.mode === "data" ? 2 : 1;
	}

	goStep(step, options = {}) {
		if (this.busy || (this.releaseScreen && this.releaseScreen.busy)) return;
		this.stepSettled = true;
		if (step === 1) return this.openLoadStep(options.notice);
		if (!this.canUnload()) {
			if (step === 2) this.setMode("data");
			return;
		}
		this.openRelease({ ...options, mode: step === 3 ? "bi" : "unload" });
	}

	openLoadStep(notice = null) {
		if (!this.canLoad()) return;
		this.station.screen = this;
		this.offline = this.station.isOffline();
		this.mode = "load";
		this.data = null;
		this.form = null;
		this.lookup = null;
		if (this.canUnload()) this.done = null; // thẻ mã mẻ đã hiện ở bước dỡ
		this.notice = notice;
		if (this.station.picker && this.station.picker.isOpen) this.station.picker.close();
		this.loadQueues(true);
		this.show();
		this.station.focus(true);
	}

	// Dữ liệu chu trình trong bước 2: mẻ đã biết từ màn dỡ, máy chủ vẫn kiểm cặp mã (Q10)
	openDataKnown(load, equipmentRaw, loadRaw) {
		this.station.screen = this;
		this.offline = this.station.isOffline();
		this.mode = "data";
		this.data = { load, equipmentRaw, loadRaw, known: true };
		this.form = null;
		this.notice = null;
		this.lookup = null;
		if (this.station.picker && this.station.picker.isOpen) this.station.picker.close();
		return this.fetchContext();
	}

	// ---- bảng phụ: mẻ đang chạy ----
	async loadOverview(force = false) {
		if (this.overviewBusy || (this.overview && !force) || !this.station.session) return;
		if (this.station.isOffline()) return;
		const version = this.station.sessionVersion;
		this.overviewBusy = true;
		try {
			const res = await this.station.rpcRead("tracecore.v1.load.overview", {
				station: this.station.station,
				client_ts: clientTs(),
			});
			if (version !== this.station.sessionVersion) return;
			this.overview = { running: (res && res.ok && res.running) || [] };
		} catch (error) {
			if (error.sessionEnded) return;
			this.overview = { running: [] }; // không tải lại liên tục khi vai trò không xem được; Thử lại tải lại
		} finally {
			this.overviewBusy = false;
		}
		if (version === this.station.sessionVersion && !this.busy && !this.form) this.show();
	}

	// ---- nhập dữ liệu chu trình ----
	setMode(mode) {
		if (this.busy || (mode !== "load" && mode !== "data")) return;
		if (mode === "load" && !this.canLoad()) return;
		this.mode = mode;
		this.notice = null;
		this.lookup = null;
		if (mode === "load") this.data = null;
		if (this.station.picker && this.station.picker.isOpen) this.station.picker.close();
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

	// Chọn tay ở tab Dữ liệu chu trình (A-87): danh sách là mẻ còn mở; tab Nạp máy vẫn chọn gói
	pickContext() {
		if (this.mode !== "data") return null;
		const raw = this.data && !this.data.saved && this.data.equipmentRaw;
		return {
			label: __("Loads"),
			purpose: "unload",
			equipment: raw ? t5Kind(raw).id : null,
		};
	}

	pickCodes(item) {
		const current = this.data;
		if (current && current.load === item.id && current.equipmentRaw) return [item.id];
		return [item.id, item.equipment];
	}

	dataScan(raw) {
		const code = t5Kind(raw);
		if (code.kind === "pack" && tcIsSetOrPackCode(raw))
			return this.blocked(t5SetCodeNotice(raw));
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
			// máy không đẩy dữ liệu: điền sẵn theo chương trình, KTV kiểm tra và sửa được (A-89)
			const prefill = context.prefill || {};
			const values = {};
			Object.entries(prefill.values || {}).forEach(([name, value]) => {
				values[name] = window.tcDecimal(value);
			});
			(context.params || []).forEach((row) => {
				values[row.parameter_name] = window.tcDecimal(row.value);
			});
			const alerts = context.machine_alerts && context.machine_alerts.text;
			this.form = {
				values,
				alerts: alerts ? "yes" : "no",
				alertsText: alerts || "",
				started: t5LocalInput(context.started_at),
				ended:
					t5LocalInput(context.ended_at) ||
					t5LocalInput(prefill.ended_at) ||
					t5NowInput(),
				chemicalName: prefill.chemical_name || prefill.chemical || "",
				file: context.machine_report || "",
				reason: context.manual_reason || "",
				uploading: false,
				confirmed: false,
				card: "",
			};
			this.notice = this.data.known
				? null
				: {
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
				const known = this.data;
				this.data = { load: known.load, context: known.context, saved: res };
				this.form = null;
				const notice = {
					variant:
						res.needs_review || (res.duration && res.duration.abnormal)
							? "warn"
							: "ok",
					title: __("Manual cycle data saved and confirmed"),
					reason: [
						res.needs_review
							? __(
									"Some values are outside the program range: a Pass needs head of KSNK approval."
							  )
							: "",
						this.durationText(res.duration),
					]
						.filter(Boolean)
						.join(" · "),
				};
				// A-103: lưu xong về đúng mẻ ở bước dỡ, không phải bấm thêm hay quét lại
				if (known.known && this.canUnload()) {
					this.data = null;
					return this.openRelease({
						load: known.load,
						equipment: known.equipmentRaw,
						loadRaw: known.loadRaw,
						notice,
					});
				}
				this.notice = notice;
				this.loadOverview(true);
				this.show();
			}
		);
	}

	durationText(duration) {
		if (!duration) return "";
		const text = __("Actual {0} min, standard {1} min ({2} %)", [
			duration.actual_min,
			duration.standard_min,
			duration.deviation_pct,
		]);
		return duration.abnormal ? `${__("Abnormal duration")}: ${text}` : text;
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
			"t5-step": () => this.goStep(Number(data.step)),
			"t5-daily-test": () => {
				this.openDailyTest();
				if (this.dailyTestScreen) this.dailyTestScreen.back = this;
			},
			"t5-remove": () => this.removePack(data.pack),
			"t5-recheck": () => this.recheckPacks(),
			"t5-complete": () => this.complete(),
			"t5-label-pdf-retry": () => this.printLabelPdf(),
			"t5-cancel": () => this.cancelLoad(),
			"t5-open-data": () => this.openData(data.load),
			"t5-save-data": () => this.saveData(),
			"t5-data-reset": () => {
				this.data = null;
				this.form = null;
				this.notice = null;
				if (this.canUnload()) return this.goStep(2);
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
			this.load.program = target.value;
			this.saveLoad();
			this.show();
			this.recheckPacks();
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
		// câu trả lời muộn (nhãn PDF, danh sách mẻ) khi màn đang ở bước khác của T5, hoặc ở Kiểm tra hằng ngày
		if (this.station.screen && this.station.screen !== this) {
			if (this.station.screen === this.releaseScreen) this.releaseScreen.show();
			return;
		}
		this.updatePlaceholder();
		if (!this.queues && !this.queuesError) this.loadQueues();
		if (!this.overview && this.mode === "data") this.loadOverview();
		const body = this.mode === "data" ? this.dataHtml() : this.loadHtml();
		this.station.setState(
			this.viewState(),
			`<div class="tc-t2 tc-t5" data-mode="${esc(this.mode)}">
				${t5StepsHtml(this.currentStep(), this)}
				${t5InstructionHtml(this.instructionText())}
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.lookup ? this.lookupHtml(this.lookup) : ""}
				${body}
				${this.mode === "load" ? this.loadBarHtml() : ""}
			</div>`
		);
		const error = Boolean(this.notice && this.notice.variant === "error");
		this.station.form.classList.toggle("is-error", error);
		this.station.revealNotice(this.notice);
	}

	instructionText() {
		if (this.mode === "data") {
			return this.data && this.data.load
				? __("Load {0}: enter the cycle data, then confirm.", [this.data.load])
				: __("Scan the sterilizer QR code, then the load QR code.");
		}
		return this.load
			? __("Scan each pack into sterilizer {0}, then press Complete loading.", [
					this.load.machine.name,
			  ])
			: __("Scan the sterilizer QR code, then scan each pack.");
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

	// chế độ theo chức năng của trạm (A-64)
	stationHas(code) {
		const info = this.station.stationInfo;
		return Boolean(info && (info.functions || []).includes(code));
	}

	canLoad() {
		return this.stationHas("STERI_LOAD");
	}

	canUnload() {
		return this.stationHas("STERI_UNLOAD");
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
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(tcErrorTitle(notice))}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${items ? `<ul class="tc-alert-items">${items}</ul>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
			${tcGuideButton(notice)}
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
				reason: __("Sterilization loads need a network connection."),
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
				this.notice.technical
					? this.standardButtons()
					: this.station.businessButtons(this.notice)
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
				<p class="tc-empty">${esc(
					__(
						"Only packs that finished packing and fit the program of this sterilizer are accepted."
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
				(row) => `<li class="tc-t5-pack${row.incompatible ? " is-bad" : ""}">
					<div class="tc-t5-pack-id"><span>${tcPackLabelHtml(row)}</span>
						<span class="tc-mono">${esc(row.set_id)}</span></div>
					<div>${esc(__(row.method, null, "Pack"))} · ${esc(row.pack_type_name || "-")} · ${esc(
					__("Expires {0}", [t5Date(row.expiry)])
				)}</div>
					${this.gatesHtml(row.gates)}
					<button type="button" class="tc-btn tc-btn-secondary" data-action="t5-remove"
						data-pack="${esc(row.cycle_id)}"${t5Disabled(Boolean(this.busy))}>${esc(
					__("Remove from the list")
				)}</button>
					${
						row.incompatible
							? `<p class="tc-t5-pack-reason"><span aria-hidden="true">&#10005;</span> ${esc(
									row.incompatible.reason || row.incompatible.code
							  )}</p>`
							: ""
					}
				</li>`
			)
			.join("");
		const list = load.packs.length
			? `<ul class="tc-t5-packs">${rows}</ul>`
			: `<p class="tc-empty">${esc(
					__(
						"Only packs that finished packing and fit the program of this sterilizer are accepted."
					)
			  )}</p>`;
		const recheck =
			load.rechecking && !this.busy
				? `<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="t5-recheck">${esc(
						__("Check the packs again")
				  )}</button></div>`
				: "";
		return `${html}<section class="tc-t4-block tc-t2-machine">
				<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(
					__("Sterilizer {0} scanned · {1}", [
						load.machine.name,
						load.machine.equipment_name,
					])
				)} · ${esc(
			load.machine.is_connected
				? __("API connected - data comes automatically from the station agent")
				: __("not connected - enter the cycle data by hand with confirmation")
		)} · ${esc(
			max
				? __("Up to {0} pack(s) per load.", [max])
				: __("Capacity not set for this sterilizer.")
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
				${recheck}
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
						<dt>${esc(__("Packs in load"))}</dt><dd>${(done.pack_rows || [])
			.map((row) => tcPackLabelHtml(row))
			.join(", ")}</dd>
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
			return this.alertHtml({ variant: "info", title: __("Creating the label PDF...") });
		if (note.kind === "pdf") {
			return this.alertHtml({
				variant: "ok",
				title: __("Label printed to PDF file: {0}", [note.filename]),
				reason: __("Print job {0}", [print.print_job]),
			});
		}
		if (note.kind === "pdf-failed") {
			return this.alertHtml(
				{
					variant: "warn",
					title: __("Label PDF was not created; code {0} is kept.", [this.done.load]),
					reason: [note.reason, __("Print job {0}", [print.print_job])]
						.filter(Boolean)
						.join(" "),
				},
				tcPdfRetryButton("t5-label-pdf-retry", this.busy || this.offline)
			);
		}
		const warning = print.warning || {};
		return this.alertHtml({
			variant: "warn",
			title:
				warning.code === "NO_PRINTER_AT_STATION"
					? __("No printer at this station, the label is waiting")
					: __("Load code kept, the label was not printed"),
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
		// FEAT-024: dữ liệu do station agent gửi (A-39)
		const auto = load.data_source === "Auto";
		const text = load.data_complete
			? auto
				? __("Automatic (station agent)")
				: load.data_source === "Manual Default"
				? __("Manual entry from program defaults, confirmed")
				: __("Manual entry, confirmed")
			: auto
			? __("Automatic (station agent), incomplete")
			: __("Manual entry, incomplete");
		return load.needs_review ? `${text} · ${__("Needs review")}` : text;
	}

	lookupHtml(load) {
		const packs = load.packs.map((row) => tcPackLabelHtml(row)).join(", ");
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
				<dt>${esc(__("Packs in load ({0})", [load.packs.length]))}</dt><dd>${packs}</dd>
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
					<span class="tc-badge${row.unloaded ? "" : " tc-badge-o"}">${esc(
							t5MachineState(row.status, row.load, row.unloaded)
						)}</span>
				</div>
				<p>${esc(
					__("Sterilization load · {0} · {1}", [
						row.equipment_name || row.equipment,
						row.program_name || row.program,
					])
				)} <span class="tc-mono">${esc(row.equipment)}</span></p>
				<p>${esc(__("Packs in load ({0})", [row.packs.length]))}: ${(row.pack_rows || [])
							.map((pack) => tcPackLabelHtml(pack))
							.join(", ")}</p>
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

	// Dòng thông tin mẻ sau khi quét/chọn (ticket 1819): số bộ trong mẻ, có cần BI
	loadFactsText(load) {
		return [
			__("{0} pack(s)", [(load.packs || []).length]),
			load.requires_bi
				? __("Biological indicator required")
				: __("No biological indicator required"),
		].join(" · ");
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
			${
				data.known
					? ""
					: `<p>${esc(__("Sterilizer QR code"))}: <b>${esc(
							data.equipmentRaw ? __("Scanned") : __("Not scanned")
					  )}</b> · ${esc(__("Load QR code"))}: <b>${esc(
							data.loadRaw ? __("Scanned") : __("Not scanned")
					  )}</b></p>`
			}
			${data.context ? `<p>${esc(this.loadFactsText(data.context))}</p>` : ""}
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="t5-data-reset">${esc(
				data.known ? __("Back to unloading") : __("Choose another load")
			)}</button></div>
		</section>`;
		if (!data.context || !this.form) return html;
		return html + this.formHtml();
	}

	savedHtml(saved) {
		return `<section class="tc-t4-block">
			${this.alertHtml({
				variant:
					saved.needs_review || (saved.duration && saved.duration.abnormal)
						? "warn"
						: "ok",
				title: __("Cycle data attached to the load"),
				reason: [
					__("The load is now {0}.", [__(saved.status, null, "Sterilization Load")]),
					this.durationText(saved.duration),
				]
					.filter(Boolean)
					.join(" · "),
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
				const [lowText, highText] = [low, high].map(window.tcDecimal);
				if (low && high) range = `${lowText} – ${highText}`;
				else if (low) range = `≥ ${lowText}`;
				else if (high) range = `≤ ${highText}`;
				return `<div class="tc-field${state === "review" ? " is-review" : ""}">
					<label for="tc-t5-param-${esc(param.parameter_name)}">${esc(param.parameter_name)}${
					param.unit ? ` (${esc(param.unit)})` : ""
				}${Number(param.required) ? " *" : ""}${range ? ` · ${esc(range)}` : ""}</label>
					<input id="tc-t5-param-${esc(
						param.parameter_name
					)}" type="text" inputmode="decimal" autocomplete="off"
						data-param="${esc(param.parameter_name)}" value="${esc(form.values[param.parameter_name] || "")}">
					<p class="tc-t5-review tc-t2-review"${state === "review" ? "" : " hidden"}>${esc(
					__("Outside the program range - a Pass needs head of KSNK approval")
				)}</p>
				${
					param.default_value != null
						? `<p class="tc-hint">${esc(
								__("Program default: {0}", [window.tcDecimal(param.default_value)])
						  )}</p>`
						: ""
				}
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
		const who = session.employee_name || __("operator");
		return `<section class="tc-t4-block tc-t2-form">
			<h3>${esc(__("Manual cycle data - confirmed by the operator"))}</h3>
			${
				context.prefill
					? `<p class="tc-hint">${esc(
							__(
								"Filled in from the program: check against the sterilizer, change what differs, then confirm."
							)
					  )}</p>`
					: ""
			}
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
					<option value="no"${form.alerts === "no" ? " selected" : ""}>${esc(__("No"))}</option>
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
			this.busy === T5_SAVE ? __("Recording...") : __("Confirm cycle data")
		)}</button>
			</div>
		</section>`;
	}
}
