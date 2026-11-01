/* global t5MachineState, t5DateTime, t5RejectNotice, t5SetCodeNotice, tcIsSetOrPackCode, tcPackLabelHtml */
/* global t5StepsHtml, t5InstructionHtml */
/* global tcErrorTitle, tcGuideButton */
/* global uuid4, clientTs, esc, t5Kind, t5Date, t5IndicatorLabel, T5Load */
// Màn T5b dỡ mẻ và giải phóng (SCR-10, FEAT-023, UC-10) trên Page station: chế độ "Dỡ mẻ" của màn T5.
// Frappe nối file này sau station_t5.js (hook page_js) nên dùng chung uuid4/clientTs/esc/t5Kind/t5IndicatorLabel.
// Bước 2 (dỡ mẻ, giải phóng) và bước 3 (đọc BI) của thanh bước T5 (A-103); T5Load đổi `station.screen` sang T5Release.
// Quét QR máy và QR mã mẻ (hai mã, thứ tự bất kỳ, server kiểm lại) mở mẻ: kết quả chu trình, chỉ thị, giải phóng bằng PIN
// R02 (hoặc R01 kèm lý do khẩn), mẻ Không đạt, đọc BI. Lỗi chặn = alert-error inline (kết quả → lý do → hành động).

const T5B_CONTEXT = "tracecore.v1.release.context";
const T5B_RESULT = "tracecore.v1.release.cycle_result";
const T5B_INDICATOR = "tracecore.v1.release.indicator";
const T5B_RELEASE = "tracecore.v1.release.release";
const T5B_REJECT = "tracecore.v1.release.reject";
const T5B_BI = "tracecore.v1.release.bi_result";
const T5B_VERIFY_PIN = "tracecore.v1.station.verify_pin";
// từ chối làm mẻ đang mở không còn dùng được → bỏ mẻ để quét mẻ khác
const T5B_RESET_CODES = [
	"LOAD_NOT_FOUND",
	"LOAD_NOT_OPEN",
	"LOAD_ALREADY_RELEASED",
	"STATION_WRONG_STEP",
	"EQUIPMENT_MISMATCH",
];

class T5Release {
	constructor(station, back) {
		this.station = station;
		this.back = back; // màn T5Load để quay lại
		this.result = station.result;
		this.input = station.input;
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.reset();
		this.result.addEventListener("change", (event) => this.onChange(event));
		this.result.addEventListener("input", (event) => this.onInput(event));
	}

	get dialogOpen() {
		return false;
	}

	reset() {
		this.mode = "unload"; // unload | bi
		this.scans = { equipment_raw: "", load_raw: "" };
		this.ctx = null; // kết quả release.context
		this.notice = null;
		this.resetDraft();
		this.biLoad = "";
		this.biResult = "";
		this.biManual = null;
	}

	resetDraft() {
		this.form = {
			result: "",
			confirmed: false,
			pin: "",
			review: false,
			reason: "",
			accept: false, // Vẫn chấp nhận Đạt khi ngoài dải (A-106)
			outOfRangeReason: "",
			redo: "T4",
			reject: "",
		};
		this.indicator = {}; // nháp từng chỉ thị: {kind: {result, test_date, lot, incubator}}
	}

	closeLoad() {
		this.ctx = null;
		this.scans = { equipment_raw: "", load_raw: "" };
		this.resetDraft();
	}

	// Mẻ theo trạng thái do T5Load giữ (A-103), nguồn của thanh bước và danh sách chọn nhanh
	get queues() {
		return this.back && this.back.queues;
	}

	// A-103: vào bước; `load` đã biết thì mở luôn, `reason` là vết Manual Entry vì không có lần quét nào
	open({
		mode = "unload",
		load = null,
		equipment = null,
		loadRaw = null,
		notice = null,
		reason = null,
	} = {}) {
		this.station.screen = this;
		this.offline = this.station.isOffline();
		this.mode = mode;
		this.notice = notice;
		if (this.station.picker && this.station.picker.isOpen) this.station.picker.close();
		this.back.loadQueues(true);
		if (mode === "unload" && load) {
			if (this.ctx && this.ctx.load !== load) this.closeLoad();
			this.scans = { equipment_raw: equipment, load_raw: loadRaw || load };
			this.openLoad(reason);
		} else if (mode === "unload" && this.ctx) {
			this.openLoad(); // quay lại bước: đọc lại mẻ đang mở
		} else {
			this.show();
		}
		this.station.focus(true);
	}

	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.reset();
		this.back.clearSession();
		this.station.screen = this.back;
		this.input.placeholder = __("Scan Set ID...");
		this.input.setAttribute("aria-label", __("Scan Set ID"));
	}

	// ---- quét ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline()) return this.station.setOffline(true);
		const code = t5Kind(raw);
		if (code.kind === "pack" && tcIsSetOrPackCode(raw))
			return this.blocked(t5SetCodeNotice(raw));
		if (this.mode === "bi") {
			if (code.kind !== "load") return this.blocked(this.scanHint());
			this.biLoad = raw;
			this.biResult = "";
			// bi_result gửi sau khi chọn kết quả, lúc đó đã hết cửa sổ chọn tay nên giữ lý do tại đây (A-87)
			this.biManual = this.station.manualEntry ? this.station.manualEntry.reason : null;
			this.notice = null;
			return this.show();
		}
		if (code.kind !== "equipment" && code.kind !== "load")
			return this.blocked(this.scanHint());
		this.notice = null;
		const rows = (this.queues && this.queues.unload) || [];
		if (code.kind === "load") {
			if (this.ctx && this.ctx.load !== code.id) this.closeLoad();
			this.scans.load_raw = raw;
			// A-103: máy của mẻ đã biết từ danh sách thì không quét lại; máy chủ vẫn kiểm cặp mã
			const row = rows.find((item) => item.id === code.id);
			if (!this.scans.equipment_raw && row) this.scans.equipment_raw = row.equipment;
		} else {
			if (this.ctx && (!this.ctx.equipment || this.ctx.equipment.name !== code.id))
				this.closeLoad();
			const open = rows.filter((item) => item.equipment === code.id);
			// máy không có mẻ mở là máy để nạp: sang bước 1 với đúng mã vừa quét
			if (!open.length && this.queues && !this.scans.load_raw && this.back.canLoad()) {
				this.back.openLoadStep();
				return this.back.scan(raw);
			}
			this.scans.equipment_raw = raw;
			if (!this.scans.load_raw && open.length === 1) this.scans.load_raw = open[0].id;
		}
		if (this.scans.equipment_raw && this.scans.load_raw) return this.openLoad();
		this.show();
	}

	// Chọn tay (A-87): tab Dỡ mẻ theo mẻ chờ dỡ của máy đã quét hoặc của trạm; tab Đọc BI theo mẻ cách ly, không cần máy
	pickContext() {
		if (this.mode === "bi") return { label: __("Loads"), purpose: "bi", noEquipment: true };
		const raw = this.scans.equipment_raw;
		return { label: __("Loads"), purpose: "unload", equipment: raw ? t5Kind(raw).id : null };
	}

	pickCodes(item) {
		if (this.mode === "bi" || this.scans.equipment_raw) return [item.id];
		const rows = (this.queues && this.queues.unload) || [];
		if (rows.some((row) => row.id === item.id)) return [item.id]; // scan() tự lấy máy từ danh sách
		return [item.id, item.equipment];
	}

	scanHint() {
		return {
			title: __("Invalid code"),
			reason: __(
				"This screen needs the QR code of the sterilizer and the QR code of the load."
			),
			action: __("Scan the QR code of the sterilizer, then the QR code on the load label."),
		};
	}

	loadName() {
		return t5Kind(this.scans.load_raw).id || "";
	}

	args(extra = {}) {
		return {
			load: this.loadName(),
			equipment_raw: this.scans.equipment_raw,
			load_raw: this.scans.load_raw,
			station: this.station.station,
			...extra,
		};
	}

	openLoad(manualReason = null) {
		const extra = manualReason ? { entry_mode: "Manual", manual_reason: manualReason } : {};
		const previous = this.ctx && this.ctx.load;
		this.request(T5B_CONTEXT, this.args(extra), (res) => {
			if (previous !== res.load.load) this.resetDraft();
			this.ctx = res.load;
			this.show();
		});
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
		if (failure) this.failure(failure);
		else if (response && response.ok === false) this.reject(response.error);
		else onOk(response);
		this.station.focus();
	}

	retry() {
		this.station.manualOffline = false;
		if (!navigator.onLine) return this.station.setOffline(true);
		this.station.setOffline(false);
		const pending = this.pending;
		if (pending) return this.request(pending.method, pending.args, pending.onOk);
		this.notice = null;
		if (this.back) {
			this.back.queuesError = false;
			this.back.loadQueues(true);
		}
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
				reason: __("This account cannot unload or release sterilization loads."),
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
		if (T5B_RESET_CODES.includes(error.code)) {
			this.ctx = null;
			this.scans = { equipment_raw: "", load_raw: "" };
		}
		this.notice = t5RejectNotice(error);
		this.show();
	}

	blocked(notice) {
		this.notice = { variant: "error", ...notice };
		this.show();
	}

	// ---- thao tác ----
	currentStep() {
		return this.mode === "bi" ? 3 : 2;
	}

	// Chọn nhanh trong danh sách: không quét nên ghi vết Manual Entry với lý do cố định (A-103)
	pickLoad(load, equipment) {
		if (this.busy) return;
		const reason = __("Chosen from the T5 load list, no scan");
		this.notice = null;
		if (this.mode === "bi") {
			this.biLoad = load;
			this.biResult = "";
			this.biManual = reason;
			return this.show();
		}
		if (this.ctx && this.ctx.load !== load) this.closeLoad();
		this.scans = { equipment_raw: equipment, load_raw: load };
		this.openLoad(reason);
	}

	// Tham số ngoài dải của mẻ đang mở: Đạt chỉ qua Vẫn chấp nhận, server kiểm lại (A-89, A-106)
	outsideNames() {
		return ((this.ctx && this.ctx.params) || [])
			.filter((row) => row.outside_range)
			.map((row) => row.parameter_name);
	}

	recordResult() {
		if (!this.form.result) {
			return this.blocked({
				title: __("Cycle result is not chosen"),
				reason: __("The cycle result needs a Pass or Fail."),
				action: __("Choose Pass or Fail, tick the confirmation, then record the result."),
			});
		}
		if (this.form.result === "Pass" && this.outsideNames().length && !this.form.accept) {
			return this.blocked({
				title: __("A Pass needs a deliberate choice"),
				reason: __("Values outside the program range: {0}.", [
					this.outsideNames().join(", "),
				]),
				action: __("Tick Accept anyway, correct the cycle data, or record Fail."),
			});
		}
		this.request(
			T5B_RESULT,
			this.args({
				result: this.form.result,
				confirmed: this.form.confirmed ? 1 : 0,
				accept_out_of_range: this.form.accept ? 1 : 0,
			}),
			() => this.afterWrite(__("Cycle result recorded"))
		);
	}

	recordIndicator(kind) {
		const draft = this.indicator[kind] || {};
		const result = kind === "biological" ? "Pending" : draft.result;
		if (!result) {
			return this.blocked({
				title: __("Indicator result is not chosen"),
				reason: __("Choose Pass or Fail for the indicator."),
				action: __("Choose the result, then record it."),
			});
		}
		const extra = { indicator: kind, result };
		if (kind === "bowie_dick") extra.test_date = draft.test_date || this.today();
		if (kind === "biological") {
			extra.lot = draft.lot || "";
			extra.incubator = draft.incubator || "";
		}
		this.request(T5B_INDICATOR, this.args(extra), () =>
			this.afterWrite(__("Indicator {0} recorded", [t5IndicatorLabel(kind)]))
		);
	}

	today() {
		return new Date().toISOString().slice(0, 10);
	}

	afterWrite(title) {
		// ghi xong thì mở lại thẻ mẻ để thấy trạng thái chỉ thị và điều kiện còn thiếu
		this.notice = { variant: "ok", title };
		this.request(T5B_CONTEXT, this.args(), (res) => {
			this.ctx = res.load;
			this.show();
		});
	}

	async verifiedProof() {
		const pin = (this.form.pin || "").trim();
		if (!/^\d{6}$/.test(pin)) {
			this.blocked({
				title: __("PIN is required"),
				reason: __("This release needs the PIN of the person signed in at this station."),
				action: __("Enter the 6-digit PIN."),
			});
			return null;
		}
		const version = this.station.sessionVersion;
		try {
			const res = await this.station.rpc(T5B_VERIFY_PIN, {
				token: this.station.session.token,
				pin,
				client_ts: clientTs(),
			});
			if (version !== this.station.sessionVersion) return null;
			this.form.pin = "";
			if (res && res.ok && res.proof) return res.proof;
			this.blocked({ ...(res && res.error) });
		} catch (error) {
			if (!error.sessionEnded) this.failure(error);
		}
		return null;
	}

	async release() {
		if (this.busy) return;
		const extra = { review_confirmed: this.form.review ? 1 : 0 };
		if (this.releaseRule() === "head") {
			if (!(this.form.outOfRangeReason || "").trim()) {
				return this.blocked({
					title: __("Reason is required"),
					reason: __("A reason is required to accept cycle data outside the range."),
					action: __("Enter the reason, then release the load."),
				});
			}
			extra.pin_proof = await this.verifiedProof();
			if (!extra.pin_proof) return;
			extra.out_of_range_reason = this.form.outOfRangeReason;
		} else if (this.emergencyAllowed() && (this.form.reason || "").trim()) {
			extra.pin_proof = await this.verifiedProof();
			if (!extra.pin_proof) return;
			extra.emergency_reason = this.form.reason;
		}
		this.request(T5B_RELEASE, this.args(extra), (res) => {
			this.closeLoad();
			if (res.status === "Quarantine") {
				// A-103: mẻ có BI sang thẳng bước Đọc BI của đúng mẻ, không quét lại
				this.mode = "bi";
				this.biLoad = res.load;
				this.biResult = "";
				this.biManual = __("Load known from the previous step, no scan");
				this.notice = {
					variant: "ok",
					title: __("Load {0} is in quarantine until the biological indicator is read", [
						res.load,
					]),
					reason: __("{0} set(s) updated.", [(res.sets || []).length]),
				};
				this.back.loadQueues(true);
				return this.show();
			}
			this.back.goStep(1, {
				notice: {
					variant: "ok",
					title: __("Load {0} released", [res.load]),
					reason: __("{0} set(s) updated.", [(res.sets || []).length]),
					action: __("The packs can now go to the sterile store."),
				},
			});
		});
	}

	rejectLoad() {
		this.request(
			T5B_REJECT,
			this.args({ reason: this.form.reject || "", redo_from: this.form.redo }),
			(res) => {
				this.closeLoad();
				this.back.goStep(1, {
					notice: {
						variant: "warn",
						title: __("Load {0} failed", [res.load]),
						reason: __(
							"Every pack of the load is no longer valid; the sets go back to reprocessing."
						),
						action: __("Take the packs back to the dirty zone."),
					},
				});
			}
		);
	}

	recordBi() {
		// T5-11: lỗi này chỉ sinh ra khi bấm Ghi, không có kết quả → lý do → hành động lặp lại dòng hướng dẫn
		if (!this.biResult || !this.biLoad) {
			return this.blocked({
				title: __("Biological indicator result is not chosen"),
				action: __("Choose Negative or Positive, then record it."),
			});
		}
		this.request(
			T5B_BI,
			{
				load: t5Kind(this.biLoad).id || "",
				result: this.biResult,
				station: this.station.station,
				...(this.biManual ? { entry_mode: "Manual", manual_reason: this.biManual } : {}),
			},
			(res) => {
				const failed = res.status === "Failed" || res.recall_needed;
				this.biManual = null;
				this.biLoad = "";
				this.biResult = "";
				this.back.goStep(1, {
					notice: {
						variant: failed ? "warn" : "ok",
						title: res.recall_needed
							? __("Positive indicator after release: recall needed")
							: res.status === "Failed"
							? __("Load {0} failed", [res.load])
							: __("Load {0} released", [res.load]),
						reason: res.recall
							? __(
									"Recall order {0} was opened for the packs of this load. Call R01.",
									[res.recall]
							  )
							: res.recall_needed
							? __("Call R01: packs of this load may already be issued or used.")
							: __("The biological indicator was recorded."),
					},
				});
			}
		);
	}

	onAction(action, button) {
		const data = (button && button.dataset) || {};
		const handlers = {
			retry: () => this.retry(),
			"t5-step": () => this.back.goStep(Number(data.step)),
			"t5-daily-test": () => {
				if (this.busy) return;
				this.back.openDailyTest();
				if (this.back.dailyTestScreen) this.back.dailyTestScreen.back = this;
			},
			"t5-label-pdf": () => this.back.printLabelPdf(),
			"t5b-pick": () => this.pickLoad(data.load, data.equipment),
			"t5b-open-data": () => {
				if (this.busy || !this.ctx) return;
				this.back.openDataKnown(
					this.ctx.load,
					this.scans.equipment_raw,
					this.scans.load_raw
				);
			},
			"t5b-refresh": () => this.openLoad(),
			"t5b-result": () => {
				this.form.result = data.value;
				this.show();
			},
			"t5b-record-result": () => this.recordResult(),
			"t5b-ind-result": () => {
				this.indicator[data.kind] = {
					...(this.indicator[data.kind] || {}),
					result: data.value,
				};
				this.show();
			},
			"t5b-record-ind": () => this.recordIndicator(data.kind),
			"t5b-release": () => this.release(),
			"t5b-redo": () => {
				this.form.redo = data.value;
				this.show();
			},
			"t5b-reject": () => this.rejectLoad(),
			"t5b-finish": () => this.finishChecking(),
			"t5b-bi-result": () => {
				this.biResult = data.value;
				if (this.notice && this.notice.variant === "error") this.notice = null;
				this.show();
			},
			"t5b-bi-record": () => this.recordBi(),
			"t5b-reset": () => {
				if (this.busy) return;
				this.closeLoad();
				this.biLoad = "";
				this.biResult = "";
				this.biManual = null;
				this.notice = null;
				this.back.loadQueues(true);
				this.show();
			},
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	onChange(event) {
		if (this.station.screen !== this) return;
		const target = event.target;
		if (target.dataset.t5bConfirm !== undefined) this.form.confirmed = target.checked;
		else if (target.dataset.t5bReview !== undefined) this.form.review = target.checked;
		else if (target.dataset.t5bInd) {
			const kind = target.dataset.t5bInd;
			this.indicator[kind] = {
				...(this.indicator[kind] || {}),
				[target.dataset.t5bField]: target.value,
			};
		}
	}

	onInput(event) {
		if (this.station.screen !== this) return;
		const target = event.target;
		if (target.dataset.t5bPin !== undefined) this.form.pin = target.value;
		else if (target.dataset.t5bAccept !== undefined) this.form.accept = target.checked;
		else if (target.dataset.t5bOutReason !== undefined)
			this.form.outOfRangeReason = target.value;
		else if (target.dataset.t5bReason !== undefined) this.form.reason = target.value;
		else if (target.dataset.t5bRejectReason !== undefined) this.form.reject = target.value;
		else if (target.dataset.t5bInd) {
			const kind = target.dataset.t5bInd;
			this.indicator[kind] = {
				...(this.indicator[kind] || {}),
				[target.dataset.t5bField]: target.value,
			};
		}
	}

	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	show() {
		const text =
			this.mode === "bi"
				? this.biLoad
					? __("Scan another load...")
					: __("Scan the load code...")
				: this.ctx
				? __("Scan another sterilizer or load...")
				: __("Scan the sterilizer or load QR code...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
		const offline = this.offline && !this.ctx;
		const state = offline ? "offline" : this.viewState();
		this.station.setState(
			state,
			`<div class="tc-t2 tc-t5 tc-t5b" data-mode="${esc(this.mode)}">
				${t5StepsHtml(this.currentStep(), this.back)}
				${t5InstructionHtml(this.instructionText())}
				${
					offline
						? this.offlineHtml()
						: `<div data-region="notice">${this.noticeHtml()}</div>
				${this.doneHtml()}
				${this.mode === "bi" ? this.biHtml() : this.ctx ? this.contextHtml() : this.idleHtml()}`
				}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
		if (this.station.revealNotice) this.station.revealNotice(this.notice);
	}

	viewState() {
		if (this.notice && (this.notice.variant || "error") === "error") return "error";
		if (this.ctx || (this.mode === "bi" && this.biLoad)) return "result";
		const queues = this.queues;
		if (!queues) return this.back && this.back.queuesError ? "error" : "loading";
		if (this.busy) return "loading";
		const rows = this.mode === "bi" ? queues.bi : queues.unload;
		return rows.length || this.notice || this.doneHtml() ? "result" : "empty";
	}

	// Thẻ mã mẻ vừa nạp (nhãn, cảnh báo in) đi cùng mẻ sang bước dỡ (A-99, A-101, A-103)
	doneHtml() {
		const done = this.back && this.back.done;
		if (!done || this.mode !== "unload" || (this.ctx && this.ctx.load !== done.load))
			return "";
		return this.back.doneHtml();
	}

	// Một dòng hướng dẫn cho mỗi trạng thái của bước, không lặp ở chỗ khác (T5-11)
	instructionText() {
		if (this.mode === "bi") {
			return this.biLoad
				? __("Load {0}: choose Negative or Positive, then press Record.", [
						t5Kind(this.biLoad).id || this.biLoad,
				  ])
				: __("Scan the QR code on the load label, or choose a load from the list.");
		}
		const ctx = this.ctx;
		if (!ctx)
			return __("Scan the sterilizer or load QR code, or choose a load from the list.");
		const stage = this.stageOf(ctx);
		if (stage === "data")
			return __("Load {0}: enter the cycle data when the sterilizer has finished.", [
				ctx.load,
			]);
		if (stage === "result")
			return __(
				"Load {0}: choose the cycle result, tick the confirmation, then record it.",
				[ctx.load]
			);
		if (stage === "failed")
			return this.isSupervisor()
				? __("Load {0} did not pass: reject the load.", [ctx.load])
				: __("Load {0} did not pass: finish checking.", [ctx.load]);
		if (stage === "release")
			if (this.releaseRule() === "head")
				return this.canRelease()
					? __("Load {0}: enter the PIN and the reason, then release the load.", [
							ctx.load,
					  ])
					: __("Load {0} is waiting for the head of KSNK.", [ctx.load]);
		if (stage === "release")
			return this.canRelease()
				? __("Load {0}: release the load.", [ctx.load])
				: __("Load {0} is waiting for release: finish checking.", [ctx.load]);
		return __("Load {0}: record {1}.", [ctx.load, t5IndicatorLabel(stage)]);
	}

	// Việc kế tiếp của mẻ đang mở: data | failed | result | <mã chỉ thị> | release. Chỉ việc này có nút chính.
	stageOf(ctx) {
		if (!ctx.data_complete) return "data";
		if (
			ctx.cycle_result === "Fail" ||
			Object.values(ctx.indicator_state || {}).includes("Fail")
		)
			return "failed";
		const next = (ctx.missing || []).find((code) => code !== "review");
		if (next) return next === "cycle_result" ? "result" : next;
		// A-103: mẻ có BI mà chưa ủ thì vào cách ly sẽ không đọc được (BI_NOT_PENDING): ủ BI là việc kế tiếp, máy chủ không đổi
		const biological = (ctx.indicator_state || {}).biological;
		return ctx.requires_bi && biological === "Missing" ? "biological" : "release";
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
				reason: __("Unloading and releasing a load needs a network connection."),
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
		return html;
	}

	// Mẻ chờ dỡ / chờ đọc BI (A-84, A-87), cùng nguồn với danh sách Chọn tay nên R01 cũng xem được
	waitingHtml() {
		const queues = this.queues;
		if (!queues) {
			if (this.back && this.back.queuesError) {
				return this.alertHtml(
					{
						variant: "error",
						title: __("The load list could not be loaded"),
						reason: __("Scanning still works."),
						action: __("Retry, or call R02 if it happens again."),
					},
					`<div class="tc-actions">
						<button type="button" class="tc-btn tc-btn-secondary" data-action="retry">${esc(
							__("Retry")
						)}</button>
						<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
							__("Call R02")
						)}</button>
					</div>`
				);
			}
			if (this.back && this.back.loadQueues) this.back.loadQueues();
			return `<p class="tc-loading" role="status">${esc(__("Loading..."))}</p>`;
		}
		if (this.mode === "bi") {
			return this.waitingSectionHtml(
				__("Loads waiting for the biological indicator ({0})", [queues.bi.length]),
				queues.bi
			);
		}
		const rows = queues.unload;
		// A-102: mẻ đã dỡ, chưa giải phóng tách khỏi mẻ còn trong máy
		const toUnload = rows.filter((row) => !row.unloaded);
		const toRelease = rows.filter((row) => row.unloaded);
		const unloadList =
			toUnload.length || !toRelease.length
				? this.waitingSectionHtml(
						__("Loads waiting to unload ({0})", [toUnload.length]),
						toUnload
				  )
				: "";
		const releaseList = toRelease.length
			? this.waitingSectionHtml(
					__("Loads waiting for release ({0})", [toRelease.length]),
					toRelease
			  )
			: "";
		return unloadList + releaseList;
	}

	waitingSectionHtml(title, rows) {
		const cell = (label, html, cls = "") =>
			`<td data-label="${esc(label)}"${cls ? ` class="${cls}"` : ""}>${html}</td>`;
		const state = (row) =>
			row.status === "Quarantine"
				? __(row.status, null, "Sterilization Load")
				: row.unloaded
				? __("Waiting for release")
				: t5MachineState(row.status, row.id, row.unloaded);
		const body = rows.length
			? `<table class="tc-t6-table tc-t5b-waiting">
				<thead><tr><th scope="col">${esc(__("Load"))}</th><th scope="col">${esc(
					__("Sterilizer")
			  )}</th><th scope="col">${esc(__("Program"))}</th><th scope="col">${esc(
					__("Started at")
			  )}</th><th scope="col">${esc(__("Status"))}</th><th scope="col">${esc(
					__("Packs")
			  )}</th><th scope="col">${esc(
					__("Actions", null, "Sterilization Load")
			  )}</th></tr></thead>
				<tbody>${rows
					.map(
						(row) =>
							`<tr data-load="${esc(row.id)}">${cell(
								__("Load"),
								esc(row.id),
								"tc-mono"
							)}${cell(
								__("Sterilizer"),
								`${esc(row.equipment_name || "")} <span class="tc-mono">${esc(
									row.equipment
								)}</span>`
							)}${cell(
								__("Program"),
								esc(row.program_name || row.program || "")
							)}${cell(__("Started at"), esc(t5DateTime(row.started_at)))}${cell(
								__("Status"),
								`<span class="tc-badge tc-badge-o">${esc(state(row))}</span>`
							)}${cell(
								__("Packs"),
								`${esc(row.count)}${row.requires_bi ? ` · ${esc(__("BI"))}` : ""}`
							)}${cell(
								__("Actions", null, "Sterilization Load"),
								`<button type="button" class="tc-btn tc-btn-secondary" data-action="t5b-pick" data-load="${esc(
									row.id
								)}" data-equipment="${esc(row.equipment)}">${esc(
									__("Choose")
								)}</button>`
							)}</tr>`
					)
					.join("")}</tbody>
			</table>`
			: `<p class="tc-empty">${esc(__("No load is waiting."))}</p>`;
		return `<section class="tc-t4-block" aria-label="${esc(title)}">
			<h3>${esc(title)}</h3>
			${body}
		</section>`;
	}

	idleHtml() {
		const have = (value, label) =>
			`<li>${esc(label)}: <b>${
				value ? "&#10003; " + esc(value) : esc(__("not scanned"))
			}</b></li>`;
		const scanned =
			this.scans.equipment_raw || this.scans.load_raw
				? `<ul class="tc-t6-hint">
				${have(this.scans.equipment_raw, __("Sterilizer"))}
				${have(this.scans.load_raw, __("Load"))}
			</ul>`
				: "";
		return `${scanned}${this.waitingHtml()}`;
	}

	statusText(value) {
		return (
			{
				Pass: __("Pass", null, "Step Gate Result"),
				Fail: __("Fail", null, "Step Gate Result"),
				Missing: __("Not recorded"),
				Optional: __("Not required"),
				Pending: __("Waiting to be read"),
			}[value] || value
		);
	}

	chip(action, field, value, label, active) {
		return `<button type="button" class="tc-chip" data-action="${action}" data-kind="${esc(
			field
		)}"
			data-value="${esc(value)}" aria-pressed="${active ? "true" : "false"}">${esc(label)}</button>`;
	}

	passFail(action, kind, current) {
		return `<div class="tc-chips" role="group">
			${this.chip(action, kind, "Pass", __("Pass", null, "Step Gate Result"), current === "Pass")}
			${this.chip(action, kind, "Fail", __("Fail", null, "Step Gate Result"), current === "Fail")}
		</div>`;
	}

	packsHtml(ctx) {
		return `<table class="tc-t6-table">
			<thead><tr><th scope="col">${esc(__("Pack"))}</th><th scope="col">${esc(
			__("Set ID")
		)}</th></tr></thead>
			<tbody>${(ctx.packs || [])
				.map(
					(row) =>
						`<tr><td>${tcPackLabelHtml(row)}</td><td class="tc-mono">${esc(
							row.set_id
						)}</td></tr>`
				)
				.join("")}</tbody>
		</table>`;
	}

	indicatorHtml(kind, state) {
		const draft = this.indicator[kind] || {};
		const badge = `<span class="tc-badge${
			state === "Pass" ? " tc-badge-g" : state === "Fail" ? " tc-badge-r" : ""
		}">${esc(this.statusText(state))}</span>`;
		// A-23: chỉ thị đã có từ test hằng ngày của máy (Bowie-Dick) và chưa ghi theo mẻ: chỉ hiển thị, không ghi lại
		const daily = (this.ctx.daily_indicators || {})[kind];
		const recorded = (this.ctx.indicator_rows || []).some((row) => row.indicator === kind);
		if (daily && !recorded) {
			const [year, month, day] = String(daily.test_date || "").split("-");
			return `<section class="tc-t4-block">
				<h3>${esc(t5IndicatorLabel(kind))} ${badge}</h3>
				<p class="tc-t6-hint">${esc(
					__("From the daily test of {0}: no need to record it again.", [
						`${day}/${month}/${year}`,
					])
				)}</p>
			</section>`;
		}
		let fields = "";
		if (kind === "bowie_dick") {
			fields = `<div class="tc-field"><label>${esc(__("Test date"))}
				<input type="date" data-t5b-ind="${kind}" data-t5b-field="test_date" value="${esc(
				draft.test_date || this.today()
			)}"></label></div>`;
		} else if (kind === "biological") {
			fields = `<div class="tc-field"><label>${esc(__("Indicator lot"))}
				<input type="text" autocomplete="off" data-t5b-ind="${kind}" data-t5b-field="lot" value="${esc(
				draft.lot || ""
			)}"></label></div>
				<div class="tc-field"><label>${esc(__("Incubator"))}
				<input type="text" autocomplete="off" data-t5b-ind="${kind}" data-t5b-field="incubator" value="${esc(
				draft.incubator || ""
			)}"></label></div>`;
		}
		const choose =
			kind === "biological" ? "" : this.passFail("t5b-ind-result", kind, draft.result);
		const primary = this.stageOf(this.ctx) === kind ? "tc-btn-primary" : "tc-btn-secondary";
		return `<section class="tc-t4-block">
			<h3>${esc(t5IndicatorLabel(kind))} ${badge}</h3>
			${choose}${fields}
			<div class="tc-actions"><button type="button" class="tc-btn ${primary}" data-action="t5b-record-ind" data-kind="${kind}">${esc(
			kind === "biological" ? __("Start incubation") : __("Record indicator")
		)}</button></div>
		</section>`;
	}

	contextHtml() {
		const ctx = this.ctx;
		const missing = ctx.missing || [];
		const form = this.form;
		const indicators = Object.entries(ctx.indicator_state || {})
			.map(([kind, state]) => this.indicatorHtml(kind, state))
			.join("");
		const stage = this.stageOf(ctx);
		const card = `<section class="tc-t4-block" aria-label="${esc(__("Load"))}">
			<div class="tc-res-head">
				<b class="tc-code">${esc(ctx.load)}</b>
				<span class="tc-badge">${esc(__(ctx.status, null, "Sterilization Load"))}</span>
			</div>
			<dl class="tc-res-grid">
				<dt>${esc(__("Sterilizer"))}</dt><dd>${esc(ctx.equipment ? ctx.equipment.equipment_name : "")}</dd>
				<dt>${esc(__("Program"))}</dt><dd>${esc(ctx.program ? ctx.program.program_name : "")}</dd>
				<dt>${esc(__("Packs in load ({0})", [(ctx.packs || []).length]))}</dt><dd>${esc(
			this.back.loadFactsText(ctx)
		)}</dd>
				<dt>${esc(__("Cycle data"))}</dt><dd>${esc(
			ctx.data_complete ? __("Entered and confirmed") : __("Not entered yet")
		)}${
			ctx.needs_review
				? ` <span class="tc-badge tc-badge-o">${esc(__("Needs review"))}</span>`
				: ""
		}</dd>
				${
					ctx.duration
						? `<dt>${esc(__("Duration", null, "Sterilization Load"))}</dt><dd>${esc(
								this.back.durationText(ctx.duration)
						  )}${
								ctx.duration.abnormal
									? ` <span class="tc-badge tc-badge-o">${esc(
											__("Abnormal duration")
									  )}</span>`
									: ""
						  }</dd>`
						: ""
				}
				<dt>${esc(__("Loaded by"))}</dt><dd>${esc(
			ctx.operator ? ctx.operator.employee_name || ctx.operator.name : "-"
		)}</dd>
				${
					ctx.unloaded_by
						? `<dt>${esc(__("Unloaded By"))}</dt><dd>${esc(
								ctx.unloaded_by.employee_name || ctx.unloaded_by.name
						  )}</dd>`
						: ""
				}
			</dl>
			${this.packsHtml(ctx)}
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="t5b-reset">${esc(
				__("Choose another load")
			)}</button></div>
		</section>`;
		// A-103: chưa có dữ liệu chu trình thì kết quả và giải phóng chưa ghi được (máy chủ cũng chặn): chỉ một việc là nhập dữ liệu
		if (stage === "data") {
			return `${card}<section class="tc-t4-block tc-t5b-data">
				<h3>${esc(__("Cycle data"))} <span class="tc-badge">${esc(__("Not entered yet"))}</span></h3>
				<div class="tc-actions">
					<button type="button" class="tc-btn tc-btn-primary" data-action="t5b-open-data">${esc(
						__("Enter cycle data")
					)}</button>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="t5b-refresh">${esc(
						__("Check the load again")
					)}</button>
				</div>
			</section>
			${this.canRelease() ? this.rejectHtml() : ""}`;
		}
		const resultButton = stage === "result" ? "tc-btn-primary" : "tc-btn-secondary";
		return `${card}<section class="tc-t4-block">
			<h3>${esc(__("Cycle result (applies to every pack)"))}
				<span class="tc-badge${
					ctx.cycle_result === "Pass"
						? " tc-badge-g"
						: ctx.cycle_result === "Fail"
						? " tc-badge-r"
						: ""
				}">${esc(
			ctx.cycle_result ? this.statusText(ctx.cycle_result) : this.statusText("Missing")
		)}</span></h3>
			${
				ctx.duration && ctx.duration.abnormal
					? this.alertHtml({
							variant: "warn",
							title: __("Abnormal duration"),
							reason: this.back.durationText(ctx.duration),
					  })
					: ""
			}
			${
				this.outsideNames().length
					? `${this.alertHtml({
							variant: "warn",
							title: __("A Pass needs head of KSNK approval"),
							reason: __("Values outside the program range: {0}.", [
								this.outsideNames().join(", "),
							]),
							action: __(
								"Correct the cycle data if it was entered wrong, record Fail, or choose Accept anyway."
							),
					  })}
					<label class="tc-t2-confirm"><input type="checkbox" class="tc-check" data-t5b-accept${
						form.accept ? " checked" : ""
					}><span>${esc(
							__("Accept anyway: record Pass with values outside the program range.")
					  )}</span></label>`
					: ""
			}
			${this.passFail("t5b-result", "result", form.result)}
			<label class="tc-t2-confirm"><input type="checkbox" class="tc-check" data-t5b-confirm${
				form.confirmed ? " checked" : ""
			}><span>${esc(
			__("I confirm that the result above matches the sterilizer printout or screen.")
		)}</span></label>
			<div class="tc-actions">
				<button type="button" class="tc-btn ${resultButton}" data-action="t5b-record-result">${esc(
			__("Record cycle result")
		)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="t5b-open-data">${esc(
					__("Enter cycle data")
				)}</button>
			</div>
		</section>
		${indicators}
		${this.releaseHtml(ctx, missing)}`;
	}

	releaseHtml(ctx, missing) {
		const form = this.form;
		const review =
			ctx.needs_review && this.releaseRule() === "supervisor" && this.isSupervisor()
				? `<label class="tc-t2-confirm"><input type="checkbox" class="tc-check" data-t5b-review${
						form.review ? " checked" : ""
				  }><span>${esc(__("The CSSD supervisor reviewed this load."))}</span></label>`
				: "";
		const waiting = missing.length
			? `<p class="tc-t6-hint">${esc(
					__("Still missing: {0}.", [
						missing.map((m) => this.missingLabel(m)).join(", "),
					])
			  )}</p>`
			: "";
		const failed =
			ctx.cycle_result === "Fail" ||
			Object.values(ctx.indicator_state || {}).includes("Fail");
		// mẻ không đạt không giải phóng được: KTV không có nút, chỉ R02, R01 loại mẻ
		const controls = this.canRelease() && (!failed || this.isSupervisor());
		return `<section class="tc-t4-block">
			<h3>${esc(__("Release", null, "Sterilization Load"))}</h3>
			${waiting}${review}
			${
				controls
					? this.releaseControlsHtml(this.releaseReady(ctx, missing))
					: this.releaseElsewhereHtml(missing, ctx)
			}
		</section>
		${this.isSupervisor() ? this.rejectHtml() : ""}`;
	}

	releaseReady(ctx, missing) {
		const failed =
			ctx.cycle_result === "Fail" ||
			Object.values(ctx.indicator_state || {}).includes("Fail");
		if (failed || missing.filter((code) => code !== "review").length) return false;
		return !(ctx.requires_bi && (ctx.indicator_state || {}).biological === "Missing");
	}

	// A-102: chỉ R02, R01 loại mẻ; máy chủ cũng từ chối vai trò khác
	rejectHtml() {
		const form = this.form;
		return `<section class="tc-t4-block">
			<h3>${esc(__("Reject the load"))}</h3>
			<p class="tc-t6-hint">${esc(__("Use it when the cycle or an indicator failed."))}</p>
			<div class="tc-chips" role="group" aria-label="${esc(__("Restart from"))}">
				${this.chip(
					"t5b-redo",
					"redo",
					"T4",
					__("Restart from {0}", [(window.tcGateLabels || {}).T4 || "T4"]),
					form.redo === "T4"
				)}
				${this.chip(
					"t5b-redo",
					"redo",
					"T2",
					__("Restart from {0}", [(window.tcGateLabels || {}).T2 || "T2"]),
					form.redo === "T2"
				)}
			</div>
			<div class="tc-field">
				<label for="tc-t5b-reject">${esc(__("Reason"))}</label>
				<textarea id="tc-t5b-reject" rows="2" data-t5b-reject-reason>${esc(form.reject)}</textarea>
			</div>
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-danger" data-action="t5b-reject">${esc(
				__("Reject: the load failed")
			)}</button></div>
		</section>`;
	}

	sessionRoles() {
		return (this.station.session && this.station.session.roles) || [];
	}

	isSupervisor() {
		const roles = this.sessionRoles();
		return roles.includes("TC R02") || roles.includes("TC R01");
	}

	// Quy tắc máy chủ tính (`releasing.release_rule`, A-106): technician | supervisor | head
	releaseRule() {
		const ctx = this.ctx || {};
		return ctx.release_rule || (ctx.needs_review ? "supervisor" : "technician");
	}

	emergencyAllowed() {
		const roles = this.sessionRoles();
		return roles.includes("TC R01") && !roles.includes("TC R02");
	}

	canRelease() {
		const roles = this.sessionRoles();
		const rule = this.releaseRule();
		if (rule === "head") return roles.includes("TC R01");
		if (rule === "supervisor") return this.isSupervisor();
		return this.isSupervisor() || roles.includes("TC R05");
	}

	releaseElsewhereHtml(missing, ctx = {}) {
		const action = __(
			"Log out, then the CSSD supervisor signs in with the card at this station and enters the PIN."
		);
		const failed =
			ctx.cycle_result === "Fail" ||
			Object.values(ctx.indicator_state || {}).includes("Fail");
		if (failed && this.isSupervisor()) return "";
		if (!failed && this.releaseRule() === "head") {
			return this.alertHtml({
				variant: "warn",
				title: __(
					"Head of KSNK approval is needed because the cycle data is outside the range: {0}",
					[(ctx.out_of_range_names || this.outsideNames()).join(", ")]
				),
				action: __(
					"The head of KSNK signs in with the card at this station, enters the PIN and the reason."
				),
			});
		}
		if (failed) {
			return `${this.alertHtml({
				variant: "warn",
				title: __("A CSSD supervisor must handle this load"),
				action,
			})}
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="t5b-finish">${esc(
				__("Finish checking")
			)}</button></div>`;
		}
		const incubate = ctx.requires_bi && (ctx.indicator_state || {}).biological === "Missing";
		if (missing.length || incubate) {
			return this.alertHtml({
				variant: "info",
				title: __("A CSSD supervisor must release the load"),
				action,
			});
		}
		return `${this.alertHtml({
			variant: "ok",
			title: __(
				"Checks are finished. The load waits for the CSSD supervisor to release it."
			),
			action,
		})}
		<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="t5b-finish">${esc(
			__("Finish checking")
		)}</button></div>`;
	}

	// Không đổi trạng thái mẻ: kết quả đã lưu khi ghi, nút chỉ đóng mẻ để KTV làm mẻ khác
	finishChecking() {
		const load = this.ctx && this.ctx.load;
		this.closeLoad();
		// A-103: KTV xong phần mình thì về bước 1, mẻ nằm ở danh sách Mẻ chờ giải phóng
		this.back.goStep(1, {
			notice: {
				variant: "ok",
				title: __("Load {0} is waiting for the CSSD supervisor to release it", [load]),
			},
		});
	}

	pinFieldHtml(hint) {
		return `<div class="tc-field">
				<label for="tc-t5b-pin">${esc(__("PIN"))}</label>
				<input id="tc-t5b-pin" type="password" inputmode="numeric" maxlength="6" autocomplete="off" data-t5b-pin value="">
				<p class="tc-hint">${esc(hint)}</p>
			</div>`;
	}

	releaseControlsHtml(ready = true) {
		let fields = "";
		if (this.releaseRule() === "head") {
			fields = `${this.alertHtml({
				variant: "warn",
				title: __("Cycle data outside the program range: {0}", [
					this.outsideNames().join(", "),
				]),
				action: __("Your PIN and reason are recorded as the approval of this load."),
			})}
			<div class="tc-field">
				<label for="tc-t5b-out-reason">${esc(__("Reason for accepting the values"))}</label>
				<textarea id="tc-t5b-out-reason" rows="2" data-t5b-out-reason>${esc(
					this.form.outOfRangeReason
				)}</textarea>
			</div>
			${this.pinFieldHtml(__("Enter your 6-digit PIN."))}`;
		} else if (this.emergencyAllowed()) {
			fields = `<div class="tc-field">
				<label for="tc-t5b-reason">${esc(__("Emergency release reason (R01 only)"))}</label>
				<textarea id="tc-t5b-reason" rows="2" data-t5b-reason>${esc(this.form.reason)}</textarea>
			</div>
			${this.pinFieldHtml(__("An emergency release skips the BI wait and needs your PIN."))}`;
		}
		return `${fields}
			<div class="tc-actions"><button type="button" class="tc-btn ${
				ready ? "tc-btn-primary" : "tc-btn-secondary"
			}" data-action="t5b-release">${esc(__("Release the load"))}</button></div>`;
	}

	missingLabel(code) {
		return code === "cycle_result"
			? __("cycle result")
			: code === "review"
			? __("review confirmation")
			: t5IndicatorLabel(code);
	}

	biHtml() {
		const chosen = this.biLoad ? t5Kind(this.biLoad).id || this.biLoad : "";
		if (!chosen) return this.waitingHtml();
		const row = ((this.queues && this.queues.bi) || []).find((item) => item.id === chosen);
		const facts = row
			? ` · ${row.equipment_name || row.equipment} · ${
					row.program_name || row.program || ""
			  } · ${__("{0} pack(s)", [row.count])}`
			: "";
		return `<section class="tc-t4-block">
			<h3>${esc(__("Biological indicator of a load in quarantine"))}</h3>
			<p>${esc(`${__("Load {0}", [chosen])}${facts}`)}</p>
			<div class="tc-chips" role="group" aria-label="${esc(__("Biological indicator"))}">
				${this.chip("t5b-bi-result", "bi", "Pass", __("Negative (Pass)"), this.biResult === "Pass")}
				${this.chip("t5b-bi-result", "bi", "Fail", __("Positive (Fail)"), this.biResult === "Fail")}
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="t5b-bi-record">${esc(
					__("Record the biological indicator")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="t5b-reset">${esc(
					__("Choose another load")
				)}</button>
			</div>
		</section>`;
	}
}

// T5Load chuyển sang bước 2, 3 của thanh bước (xem station_t5.js)
T5Load.prototype.openRelease = function (options = {}) {
	if (this.busy || typeof T5Release === "undefined") return;
	this.releaseScreen = this.releaseScreen || new T5Release(this.station, this);
	this.releaseScreen.open(options);
};
