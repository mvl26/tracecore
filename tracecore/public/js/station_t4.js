/* global uuid4, clientTs, esc, STATUS_BADGE */
// Màn T4 đóng gói (SCR-08, anchor A2, FEAT-018) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc/STATUS_BADGE.
// TraceCoreStation giao cho T4Packing khi trạm là bước T4: một ô quét duy nhất (D10), mọi lần quét đi qua
// tracecore.v1.pack.scan kèm open_set; "kind" của kết quả quyết định việc tiếp theo. Lỗi chặn = alert-error inline.

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

function t4Date(iso) {
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
	return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

function t4DateTime(iso) {
	const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(iso || "");
	return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : t4Date(iso);
}

function t4GateLabel(step) {
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
	}

	openSet() {
		return this.ctx && !this.done ? this.ctx.set.set_id : null;
	}

	// ---- quét và gọi RPC ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline()) return this.station.setOffline(true);
		await this.request(
			"tracecore.v1.pack.scan",
			{ raw, station: this.station.station, open_set: this.openSet() },
			(res) => this.onScan(res, raw)
		);
	}

	async request(method, args, onOk) {
		if (this.busy) return;
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
			this.pending = null;
			this.result.dataset.ms = String(Math.round(performance.now() - started));
		} catch (error) {
			failure = error;
		}
		this.busy = null;
		if (!failure) this.markOnline();
		if (failure) this.failure(failure);
		else if (response && response.ok === false) this.reject(response.error, method);
		else onOk(response);
		this.station.focus();
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
		const setLevel =
			method === "tracecore.v1.pack.scan" && !T4_KEEP_CONTEXT_CODES.includes(error.code);
		if (setLevel) this.reset();
		this.notice = { variant: "error", ...error };
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
		this.done.print = print;
		if (print.status === "Queued" && print.zpl) {
			this.printNote = { kind: "sending" };
			this.show();
			const ok = await this.sendToAgent(print);
			this.printNote = { kind: ok ? "sent" : "agent-failed" };
		} else {
			this.printNote = { kind: "waiting" };
		}
		this.show();
	}

	onGenerated(res) {
		this.notice = null;
		this.done = res;
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

	confirmAll() {
		if (!this.ctx || !this.imagesReady) return;
		this.ctx.bom.forEach((_line, index) => this.checked.add(index));
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
		if (this.offline) out.push(__("network connection"));
		const left = this.ctx.bom.length - this.checked.size;
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
		this.request(T4_GENERATE, args, (res) => this.onGenerated(res));
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
				{ name: "note", label: __("Note"), type: "textarea" },
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

	show() {
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
				`<p class="tc-empty">${esc(__("Scan the Set ID of the set to pack"))}</p>`
			);
		}
		if (key === this.viewKey && this.result.querySelector(".tc-t4")) return this.refresh();
		this.viewKey = key;
		let body = "";
		if (this.done) body = this.doneHtml();
		else if (this.ctx) body = this.ctxHtml();
		this.station.setState(
			this.viewState(),
			`<div class="tc-t4" data-view="${esc(key.split(":")[0])}">
				<div data-region="notice">${this.noticeHtml()}</div>
				${body}
				<div data-region="bar">${this.barHtml()}</div>
			</div>`
		);
		this.markScanBox();
		if (this.ctx && !this.done) this.watchImages();
	}

	refresh() {
		if (!this.result.querySelector(".tc-t4")) return this.show();
		const regions = {
			notice: () => this.noticeHtml(),
			bar: () => this.barHtml(),
			maint: () => this.maintHtml(),
			bomfoot: () => this.bomFootHtml(),
			ci: () => this.ciHtml(),
			pack: () => this.packHtml(),
			printer: () => this.printerHtml(),
			print: () => this.printNoteHtml(),
		};
		this.result.querySelectorAll("[data-region]").forEach((node) => {
			const build = regions[node.dataset.region];
			if (build) node.innerHTML = build();
		});
		this.result.dataset.state = this.viewState();
		this.markScanBox();
	}

	markScanBox() {
		const error = Boolean(this.notice && this.notice.variant === "error");
		this.station.form.classList.toggle("is-error", error);
		// lỗi mới (vd bấm Xác nhận ở cuối trang): cuộn về đầu để thấy ô quét và alert-error ngay dưới
		if (error && this.shownNotice !== this.notice) window.scrollTo({ top: 0 });
		this.shownNotice = this.notice;
	}

	updatePlaceholder() {
		const text = this.openSet()
			? __("Scan indicator lot, next Set ID, Cycle ID or roll code...")
			: __("Scan Set ID...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	watchImages() {
		// D1: "Xác nhận tất cả" chỉ bật khi mọi ảnh của lưới BOM đã tải xong hoặc báo lỗi
		const images = [...this.result.querySelectorAll(".tc-inst img")];
		const check = () => {
			if (this.imagesReady || !this.ctx || !this.ctx.bom.length) return;
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
			notice.code === "PAR_EXCEEDED"
				? `<div class="tc-actions">
					<button type="button" class="tc-btn tc-btn-secondary" disabled>${esc(
						__("Request override")
					)}</button>
					<span class="tc-hint">${esc(__("Available from FEAT-032"))}</span>
				</div>`
				: "";
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(notice.title)}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${items ? `<ul class="tc-alert-items">${items}</ul>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
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
		return {
			variant: "info",
			title: __("Station offline"),
			reason: __(
				"Packing needs a network connection; offline Cycle ID generation comes with FEAT-009."
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
			const standalone = !this.ctx && !this.done && this.notice.variant === "error";
			html += this.alertHtml(
				this.notice,
				this.notice.technical || standalone ? this.standardButtons() : ""
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
				<div class="tc-par tc-par-${esc(par.state)}" role="progressbar" aria-valuemin="0"
					aria-valuemax="100" aria-valuenow="${width}"><span style="width: ${width}%"></span></div>
				<span>${esc(__("{0}/{1} cycles ({2}%)", [par.cycles_used, par.max_cycles, par.percent]))}</span>
				${
					par.state === "warn"
						? `<b class="tc-warn-text">! ${esc(__("Close to the cycle limit"))}</b>`
						: ""
				}
			</div>
		</section>`;
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
				${this.photoHtml(row.image, row.instrument_name)}
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
				const checked = this.checked.has(index);
				const label = __("Placed correctly at position {0} as in the photo", [
					line.position,
				]);
				return `<label class="tc-ins${checked ? " is-done" : ""}">
					${this.photoHtml(line.image, line.instrument_name)}
					<span class="tc-ins-text">
						<span class="tc-ins-name">${esc(line.instrument_name)}</span>
						<span class="tc-ins-pos">${esc(
							__("Position {0} · × {1} · {2}", [
								line.position,
								line.qty,
								line.instrument,
							])
						)}</span>
						<span class="tc-ins-state">${esc(this.lineState(checked))}</span>
					</span>
					<input type="checkbox" class="tc-check" data-line="${index}"${
					checked ? " checked" : ""
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
		const total = this.ctx.bom.length;
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
		if (!this.ci) {
			const prompt = __("Scan indicator lot class {0} – {1}", [
				this.ctx.ci.classes.join("/"),
				__(this.ctx.ci.method),
			]);
			return `${heading}<p class="tc-t4-todo"><span aria-hidden="true">&#9675;</span> ${esc(
				prompt
			)}</p>`;
		}
		return `${heading}
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

	barHtml() {
		if (this.done) {
			const blocked = Boolean(this.busy) || this.offline;
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
				<button type="button" class="tc-btn tc-btn-danger" data-action="void"${t4Disabled(blocked)}>${esc(
				__("Void Cycle ID")
			)}</button>
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
