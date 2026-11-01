/* global tcErrorTitle, tcGuideButton, TcStepQueue */
/* global uuid4, clientTs, esc, STATUS_BADGE, tcScanId, tcLocalDay, TcOutbox */
// Màn T4 đóng gói (SCR-08, anchor A2, FEAT-018) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc/STATUS_BADGE.
// Ô chính quét Set/Cycle/cuộn nhãn; lô chỉ thị dùng ô riêng và RPC resolve_ci.
// Lỗi chặn = alert-error inline; mọi RPC người dùng do shell gắn bearer trong body.

const T4_AGENT_URL = "http://127.0.0.1:8765/print";
const T4_AGENT_TIMEOUT_MS = 5000;
const T4_VOID_REASONS = [
	"Used",
	"Expired",
	"Torn",
	"Load Failed",
	"Returned Unused",
	"Label Damaged",
];
// từ chối của lần quét không nói về một bộ mới (lô chỉ thị, cuộn nhãn, gói, mã lạ) → giữ ngữ cảnh bộ đang mở
const T4_KEEP_CONTEXT_CODES = [
	"CI_LOT_INVALID",
	"CI_LOT_EXPIRED",
	"SCAN_INVALID",
	"ROLL_NOT_FOUND",
	"ROLL_NOT_LABEL",
	"ROLL_PRINTER_AMBIGUOUS",
	"PACK_NOT_FOUND",
];
const T4_PACK_BADGE = { Packed: "", Void: "x", Recalled: "r", Quarantine: "o", Released: "g" };
const T4_GENERATE = "tracecore.v1.pack.generate_cycle_id";
const T4_SCAN = "tracecore.v1.pack.scan";
const T4_REQUEST_OVERRIDE = "tracecore.v1.par.override.request";
// lỗi chặn vì hết cơ số: T4 hiện nút "Đề nghị ghi đè" (FEAT-032, FR-M8-04)
const T4_PAR_CODES = ["PAR_EXCEEDED", "SET_END_OF_LIFE"];

function t4Date(iso) {
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
	return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

function t4DateTime(iso) {
	const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(iso || "");
	return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : t4Date(iso);
}

function t4GateLabel(step) {
	return (window.tcGateLabels || {})[step] || step;
}

function t4Disabled(flag) {
	return flag ? " disabled" : "";
}

class T4Packing {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.offline = false;
		this.busy = null; // tên RPC đang chạy
		this.dialog = null;
		this.viewKey = null;
		this.reset();
		this.result.addEventListener("change", (event) => {
			if (event.target.matches(".tc-check")) this.toggleLine(event.target);
		});
		this.result.addEventListener("submit", (event) => {
			if (!event.target.matches(".tc-ci-form")) return;
			event.preventDefault();
			const input = event.target.querySelector("#tc-ci-input");
			const raw = input.value;
			input.value = "";
			this.scanIndicator(raw);
		});
	}

	get dialogOpen() {
		return Boolean(this.dialog);
	}

	reset() {
		this.ctx = null; // ngữ cảnh của pack.scan kind=context
		this.checked = new Set(); // chỉ số dòng BOM đã tick
		this.imagesReady = false;
		this.ci = null;
		this.packType = null;
		this.maint = {}; // {mã dụng cụ: {instrument, action, oil_batch?, reason?}}
		this.done = null; // kết quả generate_cycle_id
		this.printNote = null; // {kind: sending | sent | agent-failed | waiting}
		this.notice = null; // {variant, title, reason, action, items, code, technical}
		this.lookup = null;
		if (this.queue) this.queue.reset(); // màn trống kế tiếp tải lại hàng đợi, không dùng danh sách cũ
	}

	clearSession() {
		if (this.dialog) this.dialog.remove();
		this.dialog = null;
		this.pending = null;
		this.busy = null;
		this.viewKey = null;
		this.offline = false;
		this.reset();
		this.input.placeholder = __("Scan Set ID...");
		this.input.setAttribute("aria-label", __("Scan Set ID"));
	}

	openSet() {
		return this.ctx && !this.done ? this.ctx.set.set_id : null;
	}

	// ---- quét và gọi RPC ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline()) {
			return this.offlineReady() ? this.offlineScan(raw) : this.station.setOffline(true);
		}
		this.scanned = raw; // lỗi hết cơ số của lần quét này đề nghị ghi đè cho đúng mã đã quét
		await this.request(
			T4_SCAN,
			{ raw, station: this.station.station, open_set: this.openSet() },
			(res) => this.onScan(res, raw)
		);
	}

	async scanIndicator(raw) {
		raw = (raw || "").trim();
		if (!raw || !this.openSet() || !this.station.session) return;
		if (this.station.isOffline()) {
			return this.offlineReady()
				? this.offlineIndicator(raw)
				: this.station.setOffline(true);
		}
		await this.request(
			"tracecore.v1.pack.resolve_ci",
			{
				raw,
				station: this.station.station,
				open_set: this.openSet(),
			},
			(res) => this.onScan(res, raw)
		);
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
		if (this.viewKey) this.refresh();
		else this.station.renderLoading();
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
		if (!this.viewKey) return this.station.handshake();
		this.notice = null;
		this.show();
	}

	markOnline() {
		// server đã trả lời: chắc chắn có mạng, bỏ trạng thái offline cũ (không có sự kiện "online" nào báo)
		if (!this.offline) return;
		this.offline = false;
		this.station.manualOffline = false;
		this.station.banner.hidden = true;
		this.station.root.dataset.offline = "0";
	}

	failure(error) {
		// chỉ coi là offline khi trình duyệt báo mất mạng; hết thời gian chờ khi vẫn có mạng là lỗi kỹ thuật
		// có nút Thử lại (gửi lại y nguyên key: server có thể đã ghi, ví dụ đã sinh Cycle ID)
		if (error.offline && navigator.onLine === false) return this.station.setOffline(true);
		// 4xx là câu trả lời dứt khoát của server: lần sau phải dùng key mới
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
				reason: __("This account cannot pack sets at this station."),
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
		const setLevel = method === T4_SCAN && !T4_KEEP_CONTEXT_CODES.includes(error.code);
		// bộ bị từ chối vì hết cơ số: nhớ mã để nút "Đề nghị ghi đè" gửi đúng bộ (trước khi reset bỏ ngữ cảnh)
		const parSet = this.ctx && method === T4_GENERATE ? this.ctx.set.set_id : this.scanned;
		if (setLevel) this.reset();
		this.notice = { variant: "error", ...error };
		if (T4_PAR_CODES.includes(error.code)) this.notice.setId = parSet;
		this.show();
	}

	onScan(res, raw) {
		this.notice = null;
		this.lookup = null;
		if (res.kind === "context") {
			// ngữ cảnh mới (kể cả quét lại đúng bộ đang mở): vẽ lại toàn bộ để DOM, D1 và khối bộ khớp state
			this.reset();
			this.viewKey = null;
			this.ctx = res.context;
			this.packType = (this.ctx.pack_types[0] || {}).item || null;
		} else if (res.kind === "ci") {
			this.ci = res.ci;
		} else if (res.kind === "pack") {
			this.lookup = res.pack;
		} else if (res.kind === "roll") {
			return this.onRoll(res.roll, raw);
		}
		this.show();
	}

	async onRoll(roll, raw) {
		const version = this.station.sessionVersion;
		if (this.ctx && this.ctx.set.method === roll.method) {
			this.ctx.printer = { name: roll.printer, label_type: roll.label_type };
			this.ctx.label_type = roll.label_type;
		}
		const jobs = roll.released_jobs || [];
		const broken = roll.failed_jobs || []; // nhãn chờ không dựng được: vẫn Waiting, cuộn đã ghi nhận
		const title = __("Loaded roll {0} into printer {1}.", [raw, roll.printer]);
		this.notice = jobs.length
			? {
					variant: "info",
					title,
					reason: __("Sending {0} waiting label(s) to the printer...", [jobs.length]),
			  }
			: this.rollNotice(title, 0, 0, broken);
		this.show();
		if (!jobs.length) return;
		const results = await Promise.all(jobs.map((job) => this.sendToAgent(job)));
		if (version !== this.station.sessionVersion) return;
		const failed = results.filter((ok) => !ok).length;
		this.notice = this.rollNotice(title, jobs.length, failed, broken);
		const mine = this.done && jobs.find((job) => job.print_job === this.done.print.print_job);
		if (mine) {
			this.done.print = { ...this.done.print, ...mine, status: "Queued", warning: null };
			this.printNote = { kind: results[jobs.indexOf(mine)] ? "sent" : "agent-failed" };
		}
		this.show();
	}

	rollNotice(title, sent, failed, broken) {
		const reasons = [];
		const actions = [];
		if (failed) {
			reasons.push(__("{0} waiting label(s) could not be sent to the printer.", [failed]));
			actions.push(__("Check the Station Agent, then reprint."));
		} else if (sent) {
			reasons.push(__("Sent {0} waiting label(s) to the printer.", [sent]));
		}
		if (broken.length) {
			reasons.push(
				__("{0} waiting label(s) could not be prepared and are still waiting.", [
					broken.length,
				])
			);
			actions.push(
				__(
					"Ask R10 to fix the label template, then scan the roll code on the printer to print the waiting label."
				)
			);
		}
		return {
			variant: failed || broken.length ? "warn" : "info",
			title,
			reason: reasons.join(" "),
			items: broken.map((job) => __("Print job {0}: {1}", [job.print_job, job.error])),
			action: actions.join(" "),
		};
	}

	// ---- in qua Station Agent (D11) ----
	async sendToAgent(job) {
		if (!this.station.session) return false;
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), T4_AGENT_TIMEOUT_MS);
		try {
			const response = await fetch(T4_AGENT_URL, {
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
		this.done.print = print;
		if (print.status === "Queued" && print.zpl) {
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

	onGenerated(res) {
		this.notice = null;
		this.done = res;
		if (this.queue) this.queue.reset(); // bộ vừa đóng gói rời hàng đợi
		this.handlePrint(res.print);
	}

	// ---- thao tác trên màn ----
	onAction(action, button) {
		const data = (button && button.dataset) || {};
		const handlers = {
			retry: () => this.retry(),
			"confirm-all": () => this.confirmAll(),
			"confirm-pack": () => this.confirmPack(),
			"pack-type": () => this.choosePackType(data.item),
			"maint-done": () => this.maintDone(data.instrument),
			"maint-defer": () => this.maintDefer(data.instrument),
			"maint-reset": () => {
				delete this.maint[data.instrument];
				this.refresh();
			},
			reprint: () => this.reprint(),
			void: () => this.voidPack(),
			"request-override": () => this.requestOverride(),
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	markLine(box, checked) {
		box.checked = checked;
		const card = box.closest(".tc-ins");
		card.classList.toggle("is-done", checked);
		card.querySelector(".tc-ins-state").textContent = this.lineState(checked);
	}

	toggleLine(box) {
		const index = Number(box.dataset.line);
		if (box.checked) this.checked.add(index);
		else this.checked.delete(index);
		this.markLine(box, box.checked);
		this.refresh();
	}

	// dòng BOM đã được R02 xác nhận thiếu ở T3 (FR-M2-06.1): không phải tick
	isShort(line) {
		return ((this.ctx && this.ctx.shortage) || []).some(
			(row) => row.instrument === line.instrument
		);
	}

	tickable() {
		return this.ctx.bom.filter((line) => !this.isShort(line)).length;
	}

	confirmAll() {
		if (!this.ctx || !this.imagesReady) return;
		this.ctx.bom.forEach((line, index) => {
			if (!this.isShort(line)) this.checked.add(index);
		});
		this.result.querySelectorAll(".tc-check").forEach((box) => this.markLine(box, true));
		this.refresh();
	}

	choosePackType(item) {
		if (this.ctx && this.ctx.pack_types.some((row) => row.item === item)) this.packType = item;
		this.refresh();
	}

	confirmedLines() {
		// mã dụng cụ gửi lên khi MỌI dòng BOM của mã đó đã tick
		const lines = this.ctx.bom;
		const codes = [...new Set(lines.map((line) => line.instrument))];
		return codes.filter((code) =>
			lines.every((line, index) => line.instrument !== code || this.checked.has(index))
		);
	}

	missing() {
		if (!this.ctx) return [];
		const out = [];
		if (this.offline && !this.offlineReady()) out.push(__("network connection"));
		const left = this.tickable() - this.checked.size;
		if (left > 0) out.push(__("{0} instrument(s)", [left]));
		if (!this.ci) out.push(__("indicator lot"));
		const maint = (this.ctx.maintenance || [])
			.filter((row) => !this.maint[row.instrument])
			.map((row) => row.instrument);
		if (maint.length) out.push(__("maintenance action {0}", [maint.join(", ")]));
		if (!this.packType) out.push(__("pack type"));
		return out;
	}

	confirmPack() {
		if (!this.ctx || this.done || this.missing().length || this.busy) return;
		const args = {
			set_id: this.ctx.set.set_id,
			station: this.station.station,
			confirmed_lines: this.confirmedLines(),
			ci_batch: this.ci.batch,
			pack_type: this.packType,
			maint_actions: Object.values(this.maint),
		};
		if (this.station.isOffline() && this.offlineReady()) return this.offlineGenerate(args);
		this.request(T4_GENERATE, args, (res) => this.onGenerated(res));
	}

	// ---- offline (FEAT-009, FR-M2-07.11, A-40) ----
	offlineReady() {
		const data = this.station.offlineData;
		return Boolean(this.station.offlineCapable() && data && data.function === "PACK");
	}

	offlineScan(raw) {
		const id = tcScanId(raw);
		this.scanned = id;
		this.queuedSets = this.queuedSets || new Set();
		const row = (this.station.offlineData.sets || []).find((item) => item.set_id === id);
		if (!row) {
			return this.reject(
				{
					code: "OFFLINE_SET_UNKNOWN",
					title: __("Set not in offline data"),
					reason: __(
						"{0} is not among the sets ready for packing when the station went offline.",
						[id]
					),
					action: __("Keep the set aside and pack it when the connection returns."),
				},
				T4_SCAN
			);
		}
		if (row.blocked) return this.reject(row.blocked, T4_SCAN);
		if (this.queuedSets.has(id)) {
			return this.reject(
				{
					code: "OFFLINE_ALREADY_PACKED",
					title: __("Set already packed offline"),
					reason: __("A Cycle ID for {0} is waiting to be synced.", [id]),
					action: __("Do not pack the set again."),
				},
				T4_SCAN
			);
		}
		if (row.maint_pending) {
			return this.reject(
				{
					code: "OFFLINE_MAINT",
					title: __("Maintenance needs the network"),
					reason: __("Set {0} has maintenance reminders that are handled online only.", [
						id,
					]),
					action: __("Pack this set when the connection returns."),
				},
				T4_SCAN
			);
		}
		this.onScan({ kind: "context", context: { ...row.context, offline: true } }, raw);
	}

	offlineIndicator(raw) {
		const code = tcScanId(raw).toUpperCase();
		const today = tcLocalDay();
		const lot = (this.station.offlineData.ci_batches || []).find(
			(row) => row.batch.toUpperCase() === code && row.method === this.ctx.set.method
		);
		if (!lot || lot.expiry < today) {
			this.notice = {
				variant: "error",
				code: "CI_LOT_INVALID",
				title: __("Indicator lot not valid"),
				reason: lot
					? __("Lot {0} expired on {1}.", [lot.batch, t4Date(lot.expiry)])
					: __(
							"Lot {0} is not a valid class 5/6 indicator lot for {1} in the offline data.",
							[code, __(this.ctx.set.method)]
					  ),
				action: __("Scan another indicator lot that is still valid."),
			};
			return this.show();
		}
		this.notice = null;
		this.ci = { batch: lot.batch, ci_class: lot.ci_class, expiry_date: lot.expiry };
		this.show();
	}

	// bấm hai lần liền không xếp hai gói cho cùng bộ (review I10): khóa `busy` suốt lúc lấy mã và ghi hàng đợi
	async offlineGenerate(args) {
		if (this.busy) return;
		this.busy = T4_GENERATE;
		try {
			await this.offlineGenerateLocked(args);
		} finally {
			this.busy = null;
		}
		this.show();
		this.station.focus(true);
	}

	async offlineGenerateLocked(args) {
		const code = await TcOutbox.nextCode(this.station.station);
		if (!code) {
			this.notice = {
				variant: "error",
				code: "CODE_RANGE_EXHAUSTED",
				title: __("No offline codes left"),
				reason: __("This station has used every offline Cycle ID it received."),
				action: __("Pack the remaining sets when the connection returns."),
			};
			return this.show();
		}
		const key = uuid4();
		const ts = clientTs();
		try {
			await this.station.queueCall(
				T4_GENERATE,
				{ ...args, offline_cycle_id: code },
				key,
				ts
			);
		} catch (error) {
			if (error.sessionEnded) return;
			this.notice = {
				variant: "error",
				code: "OFFLINE_STORE_FAILED",
				title: __("Could not keep the transaction on this device"),
				reason: __("The station storage is not available."),
				action: __("Do not label the set; call R10."),
			};
			return this.show();
		}
		this.queuedSets.add(args.set_id);
		const type = this.ctx.pack_types.find((row) => row.item === this.packType) || {};
		const days = Number(type.days || type.shelf_life_days || 0);
		const expiry = new Date();
		expiry.setDate(expiry.getDate() + days);
		const set = this.ctx.set;
		this.notice = null;
		this.done = {
			offline: true,
			pack: {
				cycle_id: code,
				set_id: set.set_id,
				set_name: set.set_name,
				method: set.method,
				pack_type: this.packType,
				pack_type_name: type.item_name,
				expiry: tcLocalDay(expiry),
				shelf_life_days_applied: days,
				packed_at: ts,
			},
			hri: code,
			print: null,
		};
		this.show();
	}

	offlineDoneHtml() {
		const pack = this.done.pack;
		return `<section class="tc-t4-block tc-t4-done">
			${this.alertHtml({
				variant: "info",
				title: __("Cycle ID kept on this device"),
				reason: __(
					"The pack is recorded offline and is sent to the server when the connection returns."
				),
				action: __(
					"The label prints when the connection returns; keep the pack with its set tag until then."
				),
			})}
			<p class="tc-cycle">${esc(pack.cycle_id)}</p>
			<dl class="tc-res-grid">
				<dt>${esc(__("Set ID"))}</dt><dd class="tc-mono">${esc(pack.set_id)}</dd>
				<dt>${esc(__("Set Name"))}</dt><dd>${esc(pack.set_name)}</dd>
				<dt>${esc(__("Use-by date"))}</dt><dd><b>${esc(t4Date(pack.expiry))}</b> (${esc(
			__("{0} days", [pack.shelf_life_days_applied])
		)})</dd>
				<dt>${esc(__("Pack Type"))}</dt><dd>${esc(pack.pack_type_name || pack.pack_type)}</dd>
				<dt>${esc(__("Packed At"))}</dt><dd>${esc(t4DateTime(pack.packed_at))}</dd>
			</dl>
		</section>`;
	}

	maintIntro(row) {
		return `${row.instrument_name} (${row.instrument}) · ${__(
			row.maint_type || "Maintenance",
			null,
			"Instrument"
		)}`;
	}

	maintDone(code) {
		const row = this.ctx && this.ctx.maintenance.find((item) => item.instrument === code);
		if (!row) return;
		const lube = row.maint_type === "Lubrication";
		this.openDialog({
			title: __("Confirm maintenance done"),
			intro: this.maintIntro(row),
			fields: lube
				? [{ name: "oil_batch", label: __("Lubricant lot"), required: true, mono: true }]
				: [],
			submitLabel: __("Maintenance done"),
			onSubmit: (values) => {
				this.maint[code] = { instrument: code, action: "Done" };
				if (lube) this.maint[code].oil_batch = values.oil_batch;
				this.refresh();
			},
		});
	}

	maintDefer(code) {
		const row = this.ctx && this.ctx.maintenance.find((item) => item.instrument === code);
		if (!row || !row.can_defer) return;
		this.openDialog({
			title: __("Defer maintenance"),
			variant: "warn",
			intro: this.maintIntro(row),
			fields: [{ name: "reason", label: __("Reason"), type: "textarea", required: true }],
			submitLabel: __("Defer"),
			onSubmit: (values) => {
				this.maint[code] = { instrument: code, action: "Deferred", reason: values.reason };
				this.refresh();
			},
		});
	}

	labelWaiting() {
		// F3: nhãn còn chờ máy in (Waiting) thì chưa in lại được, nếu không đổi cuộn sẽ in hai nhãn cùng Cycle ID
		return Boolean(this.done && this.done.print && this.done.print.status === "Waiting");
	}

	reprint() {
		if (!this.done || this.busy || this.offline || this.labelWaiting()) return;
		const cycleId = this.done.pack.cycle_id;
		this.openDialog({
			title: __("Reprint label"),
			intro: cycleId,
			fields: [{ name: "reason", label: __("Reason"), type: "textarea", required: true }],
			submitLabel: __("Reprint"),
			onSubmit: (values) =>
				this.request(
					"tracecore.v1.pack.reprint_label",
					{ cycle_id: cycleId, reason: values.reason, station: this.station.station },
					(res) => {
						this.notice = null;
						this.handlePrint(res.print);
					}
				),
		});
	}

	requestOverride() {
		const setId = this.notice && this.notice.setId;
		if (!setId || this.busy || this.offline) return;
		this.openDialog({
			title: __("Request override"),
			variant: "warn",
			intro: __("Set {0} reached its cycle limit. R01 decides after you give the reason.", [
				setId,
			]),
			fields: [{ name: "reason", label: __("Reason"), type: "textarea", required: true }],
			submitLabel: __("Send request"),
			onSubmit: (values) =>
				this.request(
					T4_REQUEST_OVERRIDE,
					{ set_id: setId, reason: values.reason, station: this.station.station },
					(res) => {
						this.reset();
						this.notice = {
							variant: "ok",
							title: __("Override request {0} sent", [res.override.name]),
							reason: __(
								"R01 was notified. Do not pack set {0} until the override is approved.",
								[res.override.set_unit]
							),
							action: __("Scan the set again after R01 approved the override."),
						};
						this.show();
					}
				),
		});
	}

	voidPack() {
		if (!this.done || this.busy || this.offline) return;
		const cycleId = this.done.pack.cycle_id;
		this.openDialog({
			title: __("Void Cycle ID"),
			variant: "danger",
			intro: __("Void {0}? The set goes back to reprocessing and must be packed again.", [
				cycleId,
			]),
			fields: [
				{
					name: "reason",
					label: __("Void reason"),
					type: "select",
					required: true,
					options: T4_VOID_REASONS.map((value) => [value, __(value, null, "Pack")]),
				},
				{ name: "note", label: __("Note", null, "Station"), type: "textarea" },
			],
			submitLabel: __("Void Cycle ID"),
			onSubmit: (values) =>
				this.request(
					"tracecore.v1.pack.void",
					{
						cycle_id: cycleId,
						reason: values.reason,
						station: this.station.station,
						note: values.note || null,
					},
					(res) => {
						this.reset();
						this.notice = {
							variant: "info",
							title: __("Voided Cycle ID {0}.", [res.cycle_id]),
							reason: __("Set {0} goes back to reprocessing ({1}).", [
								res.set_id,
								__(res.void_reason, null, "Pack"),
							]),
						};
						this.show();
					}
				),
		});
	}

	// ---- dialog §4.13: chỉ để nhập lý do / xác nhận; lỗi chặn không bao giờ vào dialog ----
	dialogField(field) {
		const id = `tc-dlg-${field.name}`;
		const common = `id="${id}" name="${field.name}" aria-describedby="${id}-err"${
			field.required ? " required" : ""
		}`;
		let control;
		if (field.type === "textarea") {
			control = `<textarea ${common} rows="3"></textarea>`;
		} else if (field.type === "select") {
			const options = field.options
				.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`)
				.join("");
			control = `<select ${common}><option value=""></option>${options}</select>`;
		} else {
			control = `<input ${common} type="text" autocomplete="off" spellcheck="false"${
				field.mono ? ' class="tc-mono"' : ""
			}>`;
		}
		return `<div class="tc-field">
			<label for="${id}">${esc(field.label)}${field.required ? " *" : ""}</label>
			${control}
			<p class="tc-field-error" id="${id}-err" hidden>${esc(__("Required"))}</p>
		</div>`;
	}

	openDialog({ title, intro, fields = [], submitLabel, variant = "", onSubmit }) {
		if (this.dialog) return;
		const overlay = document.createElement("div");
		overlay.className = "tc-modal";
		overlay.innerHTML = `<div class="tc-modal-box${variant ? " tc-modal-" + variant : ""}"
			role="dialog" aria-modal="true" aria-labelledby="tc-dlg-title">
			<h3 id="tc-dlg-title">${esc(title)}</h3>
			${intro ? `<p class="tc-modal-intro">${esc(intro)}</p>` : ""}
			<form class="tc-modal-form" novalidate>
				${fields.map((field) => this.dialogField(field)).join("")}
				<div class="tc-modal-actions">
					<button type="submit" class="tc-btn ${
						variant === "danger" ? "tc-btn-danger" : "tc-btn-primary"
					}">${esc(submitLabel)}</button>
					<button type="button" class="tc-btn tc-btn-secondary" data-dialog="cancel">${esc(
						__("Cancel")
					)}</button>
				</div>
			</form>
		</div>`;
		const form = overlay.querySelector("form");
		const close = () => {
			overlay.remove();
			this.dialog = null;
			this.station.focus();
		};
		form.addEventListener("submit", (event) => {
			event.preventDefault();
			const values = {};
			let firstInvalid = null;
			fields.forEach((field) => {
				const control = form.elements[field.name];
				values[field.name] = control.value.trim();
				const empty = Boolean(field.required && !values[field.name]);
				control.classList.toggle("is-error", empty);
				form.querySelector(`#tc-dlg-${field.name}-err`).hidden = !empty;
				if (empty && !firstInvalid) firstInvalid = control;
			});
			if (firstInvalid) return firstInvalid.focus();
			close();
			onSubmit(values);
		});
		overlay.querySelector("[data-dialog='cancel']").addEventListener("click", close);
		overlay.addEventListener("keydown", (event) => {
			if (event.key === "Escape") {
				event.preventDefault();
				close();
			} else if (event.key === "Tab") {
				// focus trap trong dialog
				const items = [...overlay.querySelectorAll("input, textarea, select, button")];
				const first = items[0];
				const last = items[items.length - 1];
				if (event.shiftKey && document.activeElement === first) {
					event.preventDefault();
					last.focus();
				} else if (!event.shiftKey && document.activeElement === last) {
					event.preventDefault();
					first.focus();
				}
			}
		});
		this.dialog = overlay;
		this.station.root.appendChild(overlay);
		(overlay.querySelector("input, textarea, select") || form.querySelector("button")).focus();
	}

	// ---- trạng thái mạng ----
	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	viewState() {
		return this.viewKey === "info" && this.notice && this.notice.variant === "error"
			? "error"
			: "result";
	}

	// #1835 T4-01: bộ đã lắp xong chờ đóng gói hiện sẵn khi chưa mở bộ nào; đóng gói xong tải lại
	queueHtml() {
		if (!this.queue) this.queue = new TcStepQueue(this.station, "pack");
		if (!this.queue.items && !this.queue.failed && !this.offline)
			this.queue.load(() => {
				if (!this.done && !this.ctx) this.show();
			});
		return this.queue.html(
			(count) => __("Sets waiting for packing ({0})", [count]),
			__("No set is waiting for packing.")
		);
	}

	show() {
		if (!this.station.session) return;
		let key = null;
		if (this.done) key = `done:${this.done.pack.cycle_id}`;
		else if (this.ctx) key = `ctx:${this.ctx.set.set_id}`;
		else if (this.notice || this.lookup) key = "info";
		this.updatePlaceholder();
		if (!key) {
			this.viewKey = null;
			if (this.offline) return this.station.setState("offline", this.offlineHtml());
			return this.station.setState(
				"empty",
				`<p class="tc-empty">${esc(
					__("Scan the Set ID of the set to pack")
				)}</p>${this.queueHtml()}`
			);
		}
		if (key === this.viewKey && this.result.querySelector(".tc-t4")) return this.refresh();
		this.viewKey = key;
		let body = "";
		if (this.done) body = this.done.offline ? this.offlineDoneHtml() : this.doneHtml();
		else if (this.ctx) body = this.ctxHtml();
		// chưa mở bộ nào: hàng chờ vẫn hiện cạnh thông báo lỗi (#1835 T4-01)
		else body = `<div data-region="queue">${this.queueHtml()}</div>`;
		this.station.setState(
			this.viewState(),
			`<div class="tc-t4" data-view="${esc(key.split(":")[0])}">
				<div data-region="notice">${this.noticeHtml()}</div>
				${body}
				<div data-region="danger">${this.dangerHtml()}</div>
				<div data-region="bar">${this.barHtml()}</div>
			</div>`
		);
		this.markScanBox();
		if (this.ctx && !this.done) this.watchImages();
	}

	refresh() {
		if (!this.result.querySelector(".tc-t4")) return this.show();
		const regions = {
			queue: () => this.queueHtml(),
			notice: () => this.noticeHtml(),
			danger: () => this.dangerHtml(),
			bar: () => this.barHtml(),
			maint: () => this.maintHtml(),
			bomfoot: () => this.bomFootHtml(),
			ci: () => this.ciHtml(),
			pack: () => this.packHtml(),
			printer: () => this.printerHtml(),
			print: () => this.printNoteHtml(),
		};
		// vẽ lại vùng lô chỉ thị (vd ảnh BOM vừa tải xong) không được làm mất mã máy quét đang nhập
		const typing = this.result.querySelector("#tc-ci-input");
		const typed = typing ? typing.value : "";
		const focused = typing && document.activeElement === typing;
		this.result.querySelectorAll("[data-region]").forEach((node) => {
			const build = regions[node.dataset.region];
			if (build) node.innerHTML = build();
		});
		const field = this.result.querySelector("#tc-ci-input");
		if (field) {
			field.value = typed;
			if (focused) field.focus();
		}
		this.result.dataset.state = this.viewState();
		this.markScanBox();
	}

	markScanBox() {
		const error = Boolean(this.notice && this.notice.variant === "error");
		this.station.form.classList.toggle("is-error", error);
		// lỗi mới (vd bấm Xác nhận ở cuối trang): đưa alert-error vào khung nhìn
		this.station.revealNotice(this.notice);
	}

	updatePlaceholder() {
		const text = this.openSet()
			? __("Scan next Set ID, Cycle ID or roll code...")
			: __("Scan Set ID...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	watchImages() {
		// D1: "Xác nhận tất cả" chỉ bật khi mọi ảnh của lưới BOM đã tải xong hoặc báo lỗi
		const images = [...this.result.querySelectorAll(".tc-inst img")];
		const context = this.ctx;
		const check = () => {
			if (this.imagesReady || this.ctx !== context || !this.ctx || !this.ctx.bom.length)
				return;
			if (images.every((img) => img.complete)) {
				this.imagesReady = true;
				this.refresh();
			}
		};
		images.forEach((img) => {
			img.addEventListener("load", check);
			img.addEventListener("error", () => {
				img.classList.add("is-broken");
				img.alt = __("Photo not available");
				check();
			});
		});
		check();
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		const items = (notice.items || [])
			.map((item) => `<li>${esc(this.itemText(item))}</li>`)
			.join("");
		const override =
			T4_PAR_CODES.includes(notice.code) && notice.setId
				? `<div class="tc-actions">
					<button type="button" class="tc-btn tc-btn-secondary" data-action="request-override"${t4Disabled(
						this.busy || this.offline
					)}>${esc(__("Request override"))}</button>
				</div>`
				: "";
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(tcErrorTitle(notice))}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${items ? `<ul class="tc-alert-items">${items}</ul>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
			${tcGuideButton(notice)}
			${override}
			${buttons}
		</div>`;
	}

	itemText(item) {
		if (typeof item !== "object" || item === null) return String(item);
		const parts = [
			item.instrument_name
				? `${item.instrument_name} (${item.instrument})`
				: item.instrument,
		];
		if (item.qty) parts.push(__("× {0}", [item.qty]));
		if (item.position) parts.push(__("position {0}", [item.position]));
		if (item.maint_type) parts.push(__(item.maint_type, null, "Instrument"));
		if (item.state) parts.push(this.maintStateLabel(item.state));
		return parts.filter(Boolean).join(" · ");
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

	offlineAlert() {
		if (this.offlineReady()) {
			return {
				variant: "info",
				title: __("Station offline"),
				reason: __(
					"Packing continues from the data loaded before the connection was lost. Cycle IDs come from this station's offline range; labels print when the connection returns."
				),
			};
		}
		return {
			variant: "info",
			title: __("Station offline"),
			reason: __(
				"Packing needs a network connection; no offline data was loaded on this station."
			),
		};
	}

	offlineHtml() {
		return this.alertHtml(
			this.offlineAlert(),
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
		// trong mọi view (ngữ cảnh, kết quả, thông báo) alert offline luôn có Thử lại: gửi lại `pending` cùng key
		if (this.offline) html += this.offlineHtml();
		if (this.busy) {
			html += `<p class="tc-loading" role="status" aria-busy="true">${esc(
				__("Loading...")
			)}</p>`;
		}
		if (this.notice) {
			html += this.alertHtml(
				this.notice,
				this.notice.technical
					? this.standardButtons()
					: this.station.businessButtons(this.notice)
			);
		}
		if (this.lookup) html += this.lookupHtml();
		return html;
	}

	lookupHtml() {
		const pack = this.lookup;
		const variant = T4_PACK_BADGE[pack.status] || "";
		return `<section class="tc-t4-block tc-t4-lookup" aria-label="${esc(__("Pack lookup"))}">
			<h3>${esc(__("Pack lookup"))}</h3>
			<div class="tc-res-head">
				<b class="tc-code">${esc(pack.cycle_id)}</b>
				<span class="tc-badge${variant ? " tc-badge-" + variant : ""}">${esc(
			__(pack.status, null, "Pack")
		)}</span>
			</div>
			<dl class="tc-res-grid">
				<dt>${esc(__("Set ID"))}</dt><dd class="tc-mono">${esc(pack.set_id)}</dd>
				<dt>${esc(__("Set Name"))}</dt><dd>${esc(pack.set_name)}</dd>
				<dt>${esc(__("Sterilization Method"))}</dt><dd>${esc(__(pack.method))}</dd>
				<dt>${esc(__("Pack Type"))}</dt><dd class="tc-mono">${esc(pack.pack_type)}</dd>
				<dt>${esc(__("Packed At"))}</dt><dd>${esc(t4DateTime(pack.packed_at))} · ${esc(pack.packer)}</dd>
				<dt>${esc(__("Use-by date"))}</dt><dd><b>${esc(t4Date(pack.expiry))}</b></dd>
				<dt>${esc(__("Indicator Lot"))}</dt><dd class="tc-mono">${esc(pack.ci_batch)}</dd>
				<dt>${esc(__("Labels Printed"))}</dt><dd>${esc(pack.label_print_count)}</dd>
			</dl>
		</section>`;
	}

	// -- ngữ cảnh bộ đang đóng gói --
	ctxHtml() {
		return `${this.setHtml()}
			<div data-region="maint">${this.maintHtml()}</div>
			${this.bomHtml()}
			<div class="tc-t4-row">
				<section class="tc-t4-block" data-region="ci">${this.ciHtml()}</section>
				<section class="tc-t4-block" data-region="pack">${this.packHtml()}</section>
				<section class="tc-t4-block" data-region="printer">${this.printerHtml()}</section>
			</div>`;
	}

	gateHtml(gate) {
		let cls = "";
		let mark = "&#9675; ";
		let text = __("Pending", null, "Step Gate Result");
		if (gate.result === "Pass") {
			[cls, mark, text] = ["ok", "&#10003; ", __("Pass", null, "Step Gate Result")];
		} else if (gate.result === "Fail") {
			[cls, mark, text] = ["bad", "&#10005; ", __("Fail", null, "Step Gate Result")];
		}
		const redo = gate.redo_count
			? `<small>${esc(__("Redone {0} time(s)", [gate.redo_count]))}</small>`
			: "";
		return `<div class="tc-gate${cls ? " tc-gate-" + cls : ""}">
			<small>${esc(t4GateLabel(gate.step))}</small>
			<b><span aria-hidden="true">${mark}</span>${esc(text)}</b>${redo}
		</div>`;
	}

	setHtml() {
		const set = this.ctx.set;
		const par = this.ctx.par || {
			cycles_used: set.cycles_used,
			max_cycles: set.max_cycles,
			percent: set.max_cycles ? Math.floor((100 * set.cycles_used) / set.max_cycles) : 0,
			state: "ok",
		};
		const width = Math.min(par.percent, 100);
		// override / undefined chỉ khác chữ; thanh dùng màu cảnh báo khi đang ghi đè, màu thường khi chưa xác định
		const barState = { override: "warn", undefined: "ok" }[par.state] || par.state;
		const status = STATUS_BADGE[set.status] || "";
		const department = set.department
			? ` · ${esc(__("Department: {0}", [set.department]))}`
			: "";
		return `<section class="tc-t4-block" aria-label="${esc(__("Set"))}">
			<div class="tc-res-head">
				<b class="tc-code">${esc(set.set_id)}</b>
				<span class="tc-badge">${esc(__(set.method))}</span>
				${set.is_loaner ? `<span class="tc-badge tc-badge-o">${esc(__("LOANER"))}</span>` : ""}
				<span class="tc-badge${status ? " tc-badge-" + status : ""}">${esc(
			__(set.status, null, "Set Unit")
		)}</span>
				${set.is_test ? `<span class="tc-tag">${esc(__("TEST"))}</span>` : ""}
			</div>
			<p class="tc-t4-setname"><b>${esc(set.set_name)}</b>${department}</p>
			<div class="tc-gates" aria-label="${esc(__("Step gates"))}">${(this.ctx.gates || [])
			.map((gate) => this.gateHtml(gate))
			.join("")}</div>
			<div class="tc-par-row">
				<div class="tc-par tc-par-${esc(barState)}" role="progressbar" aria-valuemin="0"
					aria-valuemax="100" aria-valuenow="${width}"><span style="width: ${width}%"></span></div>
				<span>${esc(
					par.max_cycles
						? __("{0}/{1} cycles ({2}%)", [
								par.cycles_used,
								par.max_cycles,
								par.percent,
						  ])
						: __("{0} cycles used · limit not defined", [par.cycles_used])
				)}</span>
				${
					par.state === "warn"
						? `<b class="tc-warn-text">! ${esc(__("Close to the cycle limit"))}</b>`
						: ""
				}
			</div>
			${this.parNoteHtml(par)}
		</section>`;
	}

	// FEAT-032: ghi đè đang hiệu lực và dụng cụ sắp hết / hết cơ số (chữ cam, luôn có chữ và ký hiệu)
	parNoteHtml(par) {
		const lines = [];
		if (par.state === "override" && par.override) {
			const left = Math.max(par.override.extra_cycles - par.override.cycles_consumed, 0);
			lines.push(
				__("Override {0}: {1} more cycle(s) allowed until {2}", [
					par.override.name,
					left,
					t4Date(par.override.valid_until),
				])
			);
		}
		(par.instruments || []).forEach((row) =>
			lines.push(
				row.state === "blocked"
					? __("{0} ({1}) reached its cycle limit", [
							row.instrument_name,
							row.instrument,
					  ])
					: __("{0} ({1}): {2} cycle(s) left", [
							row.instrument_name,
							row.instrument,
							row.remaining,
					  ])
			)
		);
		if (!lines.length) return "";
		return `<ul class="tc-warn-text tc-par-notes">${lines
			.map((line) => `<li><b aria-hidden="true">!</b> ${esc(line)}</li>`)
			.join("")}</ul>`;
	}

	maintStateLabel(state) {
		return state === "overdue" ? __("Overdue") : __("Due");
	}

	photoHtml(url, alt) {
		return url
			? `<img class="tc-photo" src="${esc(url)}" alt="${esc(alt)}">`
			: `<span class="tc-photo tc-photo-empty">${esc(__("No photo"))}</span>`;
	}

	maintControls(row) {
		const code = esc(row.instrument);
		const action = this.maint[row.instrument];
		if (action) {
			let text = __("Deferred · reason: {0}", [action.reason]);
			if (action.action === "Done") {
				text = action.oil_batch
					? __("Maintenance done · lubricant lot {0}", [action.oil_batch])
					: __("Maintenance done");
			}
			return `<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(text)}</p>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="maint-reset"
					data-instrument="${code}">${esc(__("Change"))}</button>`;
		}
		const locked = row.can_defer
			? ""
			: `<span class="tc-hint">${esc(
					__("Overdue: cannot be deferred any more, do the maintenance now.")
			  )}</span>`;
		return `<button type="button" class="tc-btn tc-btn-ok" data-action="maint-done"
				data-instrument="${code}">${esc(__("Maintenance done"))}</button>
			<button type="button" class="tc-btn tc-btn-warn" data-action="maint-defer"
				data-instrument="${code}"${t4Disabled(!row.can_defer)}>${esc(__("Defer (reason)"))}</button>
			${locked}`;
	}

	maintHtml() {
		const rows = this.ctx ? this.ctx.maintenance || [] : [];
		if (!rows.length) return "";
		const cards = rows
			.map(
				(row) => `<div class="tc-maint${this.maint[row.instrument] ? " is-done" : ""}">
				${this.photoHtml(row.thumbnail || row.image, row.instrument_name)}
				<div class="tc-maint-text">
					<b>${esc(row.instrument_name)}</b> <span class="tc-tag">${esc(row.instrument)}</span>
					<p>${esc(__(row.maint_type || "Maintenance", null, "Instrument"))} · ${esc(
					__("{0}/{1} cycles since maintenance", [row.cycles_since, row.interval])
				)} · ${esc(__("deferred {0}/3", [row.deferred_count]))}</p>
				</div>
				<span class="tc-badge ${row.state === "overdue" ? "tc-badge-r" : "tc-badge-o"}">${esc(
					this.maintStateLabel(row.state)
				)}</span>
				<div class="tc-actions">${this.maintControls(row)}</div>
			</div>`
			)
			.join("");
		return `<section class="tc-t4-block tc-t4-maint">
			<h3>${esc(__("Maintenance reminders ({0})", [rows.length]))}</h3>
			${cards}
		</section>`;
	}

	lineState(checked) {
		return checked ? __("Placed correctly") : __("Not confirmed");
	}

	bomHtml() {
		const ctx = this.ctx;
		const lines = ctx.bom
			.map((line, index) => {
				const short = this.isShort(line);
				const checked = this.checked.has(index);
				const label = __("Placed correctly at position {0} as in the photo", [
					line.position,
				]);
				return `<label class="tc-ins${checked ? " is-done" : ""}${
					short ? " is-short" : ""
				}">
					${this.photoHtml(line.thumbnail || line.image, line.instrument_name)}
					<span class="tc-ins-text">
						<span class="tc-ins-name">${esc(line.instrument_name)}</span>
						<span class="tc-ins-pos">${esc(
							__("Position {0} · × {1} · {2}", [
								line.position,
								line.qty,
								line.instrument,
							])
						)}</span>
						<span class="tc-ins-state">${esc(
							short ? __("Missing – confirmed by R02") : this.lineState(checked)
						)}</span>
					</span>
					<input type="checkbox" class="tc-check" data-line="${index}"${checked ? " checked" : ""}${
					short ? " disabled" : ""
				} aria-label="${esc(`${line.instrument_name}: ${label}`)}">
				</label>`;
			})
			.join("");
		const tray = ctx.tray_image
			? `<figure class="tc-tray">
				<img src="${esc(ctx.tray_image)}" alt="${esc(__("Arranged set photo"))}">
				<figcaption>${esc(__("Arranged set photo"))}</figcaption>
			</figure>`
			: "";
		const grid = lines || `<p class="tc-empty">${esc(__("This set type has no BOM."))}</p>`;
		return `<section class="tc-t4-block">
			<h3>${esc(__("Set components (BOM v{0})", [ctx.bom_version]))}</h3>
			<div class="tc-bom${tray ? " has-tray" : ""}">${tray}<div class="tc-inst">${grid}</div></div>
			<div data-region="bomfoot">${this.bomFootHtml()}</div>
		</section>`;
	}

	bomFootHtml() {
		if (!this.ctx) return "";
		const total = this.tickable();
		const ready = this.imagesReady && total > 0;
		const all = total > 0 && this.checked.size === total;
		return `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-ok" data-action="confirm-all"${t4Disabled(
				!ready || all
			)}>${esc(__("Confirm all components"))}</button>
			<span class="tc-hint">${all ? `<span aria-hidden="true">&#10003;</span> ` : ""}${esc(
			__("Confirmed {0}/{1} lines", [this.checked.size, total])
		)}</span>
			${ready ? "" : `<span class="tc-hint">${esc(__("Loading instrument photos..."))}</span>`}
		</div>`;
	}

	ciHtml() {
		if (!this.ctx) return "";
		const heading = `<h3>${esc(__("Indicator Lot"))}</h3>`;
		const field = `<form class="tc-ci-form" autocomplete="off">
			<label for="tc-ci-input">${esc(__("Scan indicator lot"))}</label>
			<input id="tc-ci-input" class="tc-scan-input" type="text" inputmode="none"
				autocomplete="off" autocapitalize="off" spellcheck="false"${t4Disabled(Boolean(this.busy))} />
			<button type="submit" class="tc-btn tc-btn-secondary"${t4Disabled(Boolean(this.busy))}>${esc(
			__("Scan")
		)}</button>
		</form>`;
		if (!this.ci) {
			const prompt = __("Scan indicator lot class {0} – {1}", [
				this.ctx.ci.classes.join("/"),
				__(this.ctx.ci.method),
			]);
			return `${heading}${field}<p class="tc-t4-todo"><span aria-hidden="true">&#9675;</span> ${esc(
				prompt
			)}</p>`;
		}
		return `${heading}${field}
			<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span>
				<b class="tc-mono">${esc(this.ci.batch)}</b> · ${esc(__("class {0}", [this.ci.ci_class]))}</p>
			<p>${esc(__("Expiry: {0}", [t4Date(this.ci.expiry_date)]))}</p>`;
	}

	packHtml() {
		if (!this.ctx) return "";
		const heading = `<h3>${esc(__("Pack Type"))}</h3>`;
		const types = this.ctx.pack_types || [];
		if (!types.length) {
			return `${heading}<p class="tc-t4-todo">${esc(
				__("No usable pack type. Call R10.")
			)}</p>`;
		}
		const chosen = types.find((row) => row.item === this.packType);
		const chips = types
			.map((row) => {
				const on = row.item === this.packType;
				return `<button type="button" class="tc-chip" data-action="pack-type"
					data-item="${esc(row.item)}" aria-pressed="${on}">${
					on ? '<span aria-hidden="true">&#10003; </span>' : ""
				}${esc(row.item_name)} · ${esc(__("{0} days", [row.shelf_life_days]))}</button>`;
			})
			.join("");
		const expiry = chosen
			? `<p>${esc(__("Expected expiry date"))}: <b>${esc(
					t4Date(chosen.expected_expiry)
			  )}</b></p>`
			: "";
		return `${heading}
			<div class="tc-chips" role="group" aria-label="${esc(__("Pack Type"))}">${chips}</div>
			${expiry}`;
	}

	printerHtml() {
		const ctx = this.ctx;
		if (!ctx) return "";
		const printer = ctx.printer;
		const warning = printer
			? ""
			: this.alertHtml({
					variant: "warn",
					title: __("No printer has this label loaded"),
					reason: __(
						"The Cycle ID can still be generated; the label waits until the roll code CN- is scanned."
					),
			  });
		return `<h3>${esc(__("Label and printer"))}</h3>
			<p>${esc(__("Label type"))}: <span class="tc-mono">${esc(ctx.label_type || "-")}</span></p>
			<p>${esc(__("Printer"))}: <span class="tc-mono">${esc(printer ? printer.name : "-")}</span></p>
			${warning}`;
	}

	dangerHtml() {
		// #1843 T4-07: nút hủy tách khỏi thanh thao tác và xa nút In lại; hủy vẫn qua hộp thoại xác nhận + lý do
		if (!this.done) return "";
		const blocked = Boolean(this.busy) || this.offline || Boolean(this.done.offline);
		return `<section class="tc-t4-block tc-danger-zone" aria-label="${esc(
			__("Void Cycle ID")
		)}">
			<p class="tc-hint">${esc(
				__(
					"Void only if this pack cannot be used. You will be asked to confirm and give a reason."
				)
			)}</p>
			<button type="button" class="tc-btn tc-btn-danger" data-action="void"${t4Disabled(blocked)}>${esc(
			__("Void Cycle ID")
		)}</button>
		</section>`;
	}

	barHtml() {
		if (this.done) {
			// gói offline chưa lên server: chưa in lại / hủy được (A-40 D1)
			const blocked = Boolean(this.busy) || this.offline || Boolean(this.done.offline);
			const waiting = this.labelWaiting();
			const waitingHint = waiting
				? `<span class="tc-hint">${esc(
						__("Reprint opens once the waiting label has been printed.")
				  )}</span>`
				: "";
			return `<div class="tc-actionsbar">
				<button type="button" class="tc-btn tc-btn-secondary" data-action="reprint"${t4Disabled(
					blocked || waiting
				)}>${esc(__("Reprint (reason)"))}</button>
				${waitingHint}
				<span class="tc-hint">${esc(__("Scan the Set ID of the next set to pack"))}</span>
			</div>`;
		}
		if (!this.ctx) return "";
		const missing = this.missing();
		const label =
			this.busy === T4_GENERATE ? __("Recording...") : __("Confirm packing complete");
		const reason = missing.length
			? `<p class="tc-missing">${esc(__("Missing: {0}", [missing.join(", ")]))}</p>`
			: "";
		return `<div class="tc-actionsbar">
			<button type="button" class="tc-btn tc-btn-primary" data-action="confirm-pack"${t4Disabled(
				missing.length > 0 || Boolean(this.busy)
			)}>${esc(label)}</button>
			${reason}
		</div>`;
	}

	// -- kết quả sau khi sinh Cycle ID --
	doneHtml() {
		const pack = this.done.pack;
		return `<section class="tc-t4-block tc-t4-done">
			${this.alertHtml({ variant: "ok", title: __("Cycle ID generated") })}
			<p class="tc-cycle">${esc(pack.cycle_id)}</p>
			<div class="tc-t4-done-grid">
				${this.labelHtml()}
				<div>
					<dl class="tc-res-grid">
						<dt>${esc(__("Set ID"))}</dt><dd class="tc-mono">${esc(pack.set_id)}</dd>
						<dt>${esc(__("Use-by date"))}</dt><dd><b>${esc(t4Date(pack.expiry))}</b> (${esc(
			__("{0} days", [pack.shelf_life_days_applied])
		)})</dd>
						<dt>${esc(__("Pack Type"))}</dt><dd>${esc(pack.pack_type_name || pack.pack_type)}</dd>
						<dt>${esc(__("Packed At"))}</dt><dd>${esc(t4DateTime(pack.packed_at))}</dd>
						<dt>${esc(__("Label type"))}</dt><dd class="tc-mono">${esc(this.labelType())}</dd>
					</dl>
					<div data-region="print">${this.printNoteHtml()}</div>
				</div>
			</div>
		</section>`;
	}

	labelHtml() {
		// label preview §4.12: dựng HTML từ dữ liệu gói, giữ tiếng Việt có dấu (D7); DataMatrix là PNG thật
		const pack = this.done.pack;
		const plasma = pack.method === "Plasma";
		const department = this.ctx && this.ctx.set.department;
		const line = (text, cls = "") => `<div${cls ? ` class="${cls}"` : ""}>${esc(text)}</div>`;
		const lines = [
			line(pack.cycle_id, "tc-label-code"),
			line(this.done.hri, "tc-label-hri"),
			line(pack.set_id, "tc-mono"),
			line(pack.set_name, "tc-label-strong"),
			department ? line(__("Department: {0}", [department])) : "",
			line(__("Method: {0}", [__(pack.method)])),
			line(__("Pack type: {0}", [pack.pack_type_name || pack.pack_type])),
			line(__("Packed: {0} · {1}", [pack.packer, t4DateTime(pack.packed_at)])),
			line(__("Indicator: lot {0} · BOM v{1}", [pack.ci_batch, pack.bom_version])),
			pack.is_loaner ? line(__("LOANER"), "tc-label-strong") : "",
			pack.is_test ? line(__("TEST"), "tc-label-strong") : "",
			line(__("EXPIRY DATE / EXP: {0}", [t4Date(pack.expiry)]), "tc-label-strong"),
			line(
				plasma
					? __("Plasma H2O2 label / Plasma label")
					: __("Steam 134°C label / Steam label"),
				"tc-label-type"
			),
		];
		return `<figure class="tc-label${plasma ? " tc-label-plasma" : ""}" aria-label="${esc(
			__("Label preview")
		)}">
			<img class="tc-label-dm" src="data:image/png;base64,${esc(
				this.done.datamatrix_png_b64
			)}" alt="${esc(__("DataMatrix {0}", [pack.cycle_id]))}">
			${lines.join("")}
		</figure>`;
	}

	labelType() {
		// nhãn chờ in (Waiting) chưa có loại nhãn trên gói: lấy loại nhãn cần nạp từ ngữ cảnh bộ
		return (
			(this.done && this.done.pack.label_type) || (this.ctx && this.ctx.label_type) || "-"
		);
	}

	printNoteHtml() {
		if (!this.done || !this.printNote) return "";
		const print = this.done.print;
		const kind = this.printNote.kind;
		if (kind === "sending") {
			return this.alertHtml({
				variant: "info",
				title: __("Sending the label to printer {0}...", [print.printer]),
			});
		}
		if (kind === "sent") {
			return this.alertHtml({
				variant: "ok",
				title: __("Label sent to printer {0}.", [print.printer]),
				reason: __("Print job {0}", [print.print_job]),
			});
		}
		if (kind === "agent-failed") {
			return this.alertHtml({
				variant: "warn",
				title: __(
					"Not sent to the printer; the Cycle ID is kept. Check the Station Agent, then reprint."
				),
				reason: __("Print job {0}", [print.print_job]),
			});
		}
		// Waiting (NO_PRINTER_FOR_METHOD, LABEL_TEMPLATE_MISSING, LABEL_RENDER_FAILED): hiển thị chung
		const warning = print.warning || {};
		const items =
			warning.code === "NO_PRINTER_FOR_METHOD" || !print.printer
				? [__("Label roll to load: {0}", [this.labelType()])]
				: [];
		return this.alertHtml({
			variant: "error",
			title: warning.title || __("Label is waiting for a printer"),
			reason: warning.reason || "",
			items,
			action: [warning.action, __("Scan the roll code CN- after changing the roll.")]
				.filter(Boolean)
				.join(" "),
		});
	}
}
