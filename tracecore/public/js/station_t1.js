/* global tcErrorTitle, tcGuideButton */
/* global uuid4, clientTs, esc, tcScanId */
// Màn T1 tiếp nhận đồ bẩn (SCR-05 STN, SCR-34 PDA, FEAT-019) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// Một ô quét duy nhất luôn ở đầu và có focus: quét thẻ người giao mở phiếu, rồi quét liên tiếp từng Set ID. Mỗi bộ hiện
// danh sách thành phần theo BOM có ảnh (tick từng dòng hoặc Xác nhận tất cả), ghi chú bất thường, rồi Xác nhận bộ; cuối
// cùng Ghi sổ phiếu. Mã quét đến khi đang chờ máy chủ được xếp hàng và chạy lần lượt (không bỏ mất). Lỗi chặn =
// alert-error inline (kết quả → lý do → hành động). RPC do shell gắn token phiên trong body.

const T1_API = "tracecore.v1.receive.";
const T1_VERIFY_PIN = "tracecore.v1.station.verify_pin";
const T1_PHOTO_MAX_EDGE = 1600;
const T1_STATUS_BADGE = { New: "x", "At Department": "", "Awaiting Receipt": "o", Sterile: "g" };
// từ chối làm phiếu đang mở không còn dùng được → bỏ phiếu để quét thẻ mở phiếu mới
const T1_RESET_CODES = ["RECEIPT_NOT_FOUND", "RECEIPT_CLOSED", "STATION_WRONG_STEP"];

class T1Receiving {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.reset();
		// tick dòng, ghi chú, chọn ảnh: sự kiện nổi lên từ vùng kết quả, chỉ xử lý khi màn của trạm đang hiển thị
		station.listen(this.result, "change", (event) => {
			if (event.target.id === "tc-t1-photo") this.onPhoto(event);
			else this.onChange(event);
		});
		station.listen(this.result, "input", (event) => this.onInput(event));
	}

	reset() {
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.offline = false;
		this.busy = null;
		this.queue = []; // mã quét đến khi đang chờ máy chủ: giữ lại, quét lần lượt sau khi xong
		this.loaded = false;
		this.receipt = null; // phiếu nháp (view của receiving.open_receipt)
		this.departments = [];
		this.waiting = []; // chi tiết các bộ chưa Xác nhận bộ
		this.currentId = null;
		this.notes = {}; // ghi chú đang gõ theo Set ID
		this.notice = null;
		this.manual = false; // form người giao không có thẻ
		this.force = null; // form tiếp nhận cưỡng bức {raw}
		this.discarding = false; // đã bấm Hủy phiếu, chờ xác nhận lần hai
		this.done = null; // kết quả ghi sổ
		this.imagesReady = false;
		this.lastRefused = null;
		this.today = null; // phiếu đã tiếp nhận hôm nay {receipts, total_*}; null = chưa tải
		this.todayFailed = false;
		this.todayBusy = false;
		this.todayOpen = null; // phiếu đang xem nhanh
		this.todaySets = {}; // bộ của từng phiếu đã mở, theo tên phiếu ("loading" | danh sách | "failed")
		this.updatePlaceholder();
	}

	get dialogOpen() {
		return Boolean(this.manual || this.force);
	}

	// Hết phiên trạm (rút thẻ, idle 10 phút, đổi người): xóa phiếu và yêu cầu dở của người trước
	clearSession() {
		this.reset();
	}

	roles() {
		return (this.station.session && this.station.session.roles) || [];
	}

	// ---- quét ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline() && !this.localReceipt()) return this.station.setOffline(true);
		if (this.busy) {
			// không bỏ mất mã quét trong lúc chờ máy chủ: xếp hàng, chạy sau khi lần trước xong
			this.queue.push(raw);
			return;
		}
		this.force = null;
		this.manual = false;
		this.discarding = false;
		this.done = null;
		if (!this.receipt) return this.openWithCard(raw);
		return this.addSet(raw);
	}

	openWithCard(raw) {
		return this.request("open", { raw, station: this.station.station }, (res) =>
			this.applyOpen(res)
		);
	}

	openManual() {
		const dept = this.result.querySelector("#tc-t1-dept");
		const name = this.result.querySelector("#tc-t1-name");
		if (!dept || !dept.value || !name || !name.value.trim()) {
			this.notice = {
				variant: "error",
				title: __("Department and name are required"),
				reason: __(
					"The deliverer has no card, so the department and the name must be entered."
				),
				action: __("Choose the department and type the name of the deliverer."),
			};
			return this.show();
		}
		return this.request(
			"open",
			{
				department: dept.value,
				deliverer_name: name.value.trim(),
				station: this.station.station,
			},
			(res) => this.applyOpen(res)
		);
	}

	applyOpen(res) {
		this.loaded = true;
		this.notice = null;
		this.manual = false;
		if (!res.receipt) {
			this.receipt = null;
			this.waiting = [];
			this.currentId = null;
			this.departments = res.departments || this.departments;
		} else {
			this.receipt = res;
			this.waiting = res.current ? [res.current] : [];
			this.currentId = res.current ? res.current.set_id : null;
		}
		this.imagesReady = false;
		this.show();
		if (!this.today) this.loadToday();
	}

	addSet(raw, extra = {}, quiet = false) {
		this.lastRefused = null;
		return this.request(
			"scan_set",
			{ receipt: this.receipt.receipt, raw, station: this.station.station, ...extra },
			(res) => {
				this.receipt = { ...this.receipt, ...res.summary };
				this.force = null;
				if (res.duplicate && !quiet) {
					this.notice = {
						variant: "warn",
						title: __("Set {0} is already on this receipt", [res.item.set_id]),
						reason: __("A set that was already scanned is not added a second time."),
						action: res.item.confirmed
							? __("Scan the next set.")
							: __("Confirm the components of this set."),
					};
				} else {
					this.notice = null;
				}
				if (!res.item.confirmed) this.setWaiting(res.item);
				this.imagesReady = false;
				this.show();
			}
		);
	}

	setWaiting(item) {
		const at = this.waiting.findIndex((row) => row.set_id === item.set_id);
		if (at >= 0) this.waiting[at] = item;
		else this.waiting.push(item);
		this.currentId = item.set_id;
	}

	current() {
		return this.waiting.find((row) => row.set_id === this.currentId) || null;
	}

	// ---- offline (FEAT-009, UC-05 E3, A-40 D3): phiếu làm trên thiết bị, Ghi sổ thành một mục hàng đợi ----
	offlineReady() {
		const data = this.station.offlineData;
		return Boolean(this.station.offlineCapable() && data && data.function === "RECEIVE");
	}

	// phiếu offline đi hết vòng đời cục bộ (kể cả khi mạng về giữa chừng); phiếu online không chuyển sang offline
	localReceipt() {
		if (this.receipt) return Boolean(this.receipt.offline);
		return this.station.isOffline() && this.offlineReady();
	}

	offlineRefusal(code, title, reason, action) {
		return { ok: false, error: { code, title, reason, action } };
	}

	offlineItem(row, raw) {
		return {
			set_id: row.set_id,
			raw,
			set_name: row.set_name,
			set_type: row.set_type,
			status_before: row.status,
			bom_version: "-",
			confirmed: 0,
			needs_review: 0,
			forced: 0,
			lines_total: row.bom.length,
			lines_confirmed: 0,
			lines: row.bom.map((line) => ({ ...line, actual_qty: line.qty, confirmed: 0 })),
			tray_images: [],
			note: "",
			photo: null,
		};
	}

	async offlineCall(name, args) {
		const data = this.station.offlineData;
		if (name === "open" && !args.raw && !args.department) {
			return { receipt: null, departments: data.departments || [] };
		}
		if (name === "open") {
			const id = tcScanId(args.raw);
			if (args.raw && data.sets.some((row) => row.set_id === id)) {
				return this.offlineRefusal(
					"SCAN_INVALID",
					__("Scan the deliverer card first"),
					__(
						"{0} is a Set ID; a receipt starts with the employee card of the deliverer.",
						[id]
					),
					__("Scan the deliverer card, or choose Deliverer has no card.")
				);
			}
			const department = (data.departments || []).find(
				(row) => row.name === args.department
			);
			this.offlineItems = {};
			return {
				offline: true,
				receipt: __("Offline receipt"),
				deliverer_raw: args.raw || null,
				department: args.department || null,
				department_name: department ? department.department_name : "",
				deliverer_name: args.raw
					? __("Card {0} (checked when synced)", [args.raw])
					: args.deliverer_name,
				needs_card: args.raw ? 0 : 1,
				items: [],
				set_count: 0,
				flagged_count: 0,
			};
		}
		if (name === "scan_set") {
			if (args.force_reason) {
				return this.offlineRefusal(
					"FORCE_NOT_ALLOWED",
					__("Forced receipt needs the network"),
					__("R02 can receive a refused set by force only online."),
					__("Keep the set aside until the connection returns.")
				);
			}
			const id = tcScanId(args.raw);
			const row = data.sets.find((set) => set.set_id === id);
			if (!row) {
				return this.offlineRefusal(
					"STATUS_INVALID_FOR_STATION",
					__("Set not in offline data"),
					__(
						"{0} is not among the sets T1 could receive when the station went offline.",
						[id]
					),
					__("Keep the set aside and receive it when the connection returns.")
				);
			}
			const known = this.offlineItems[id];
			const item = known || this.offlineItem(row, args.raw);
			this.offlineItems[id] = item;
			if (!known) this.upsertSummary(item);
			return { duplicate: Boolean(known), item, summary: {} };
		}
		if (name === "confirm_line") {
			const item = this.offlineItems[args.set_id];
			const done = args.lines.filter((line) => line.confirmed).length;
			Object.assign(item, {
				confirmed: 1,
				note: args.note,
				ack_incomplete: args.ack_incomplete,
				lines_confirmed: done,
				needs_review: args.note || done < item.lines.length ? 1 : 0,
			});
			return { item };
		}
		if (name === "submit") return this.offlineSubmit();
		if (name === "discard") {
			this.offlineItems = {};
			return { receipt: null, departments: data.departments || [] };
		}
		return this.offlineRefusal(
			"OFFLINE_NOT_AVAILABLE",
			__("Needs the network"),
			__("Photos of abnormalities are taken online only."),
			__("Write the abnormality in the note instead.")
		);
	}

	async offlineSubmit() {
		const items = Object.values(this.offlineItems);
		const receipt = {
			deliverer_raw: this.receipt.deliverer_raw,
			department: this.receipt.deliverer_raw ? null : this.receipt.department,
			deliverer_name: this.receipt.deliverer_raw ? null : this.receipt.deliverer_name,
			items: items.map((item) => ({
				set_id: item.raw,
				lines: item.lines.map((line) => ({
					instrument: line.instrument,
					confirmed: line.confirmed ? 1 : 0,
					actual_qty: line.actual_qty,
				})),
				note: item.note || null,
				ack_incomplete: item.ack_incomplete ? 1 : 0,
			})),
		};
		await this.station.queueCall(
			T1_API + "submit_offline",
			{ station: this.station.station, receipt },
			uuid4(),
			clientTs()
		);
		const data = this.station.offlineData;
		const ids = new Set(items.map((item) => item.set_id));
		data.sets = data.sets.filter((row) => !ids.has(row.set_id)); // không nhận lại bộ đã vào phiếu chờ đồng bộ
		this.offlineItems = {};
		return {
			offline: true,
			receipt: __("Offline receipt"),
			sets: [...ids],
			flagged: items.filter((item) => item.needs_review).map((item) => item.set_id),
			rejected: [],
		};
	}

	async offlineRequest(name, args, onOk) {
		this.busy = T1_API + name;
		let response;
		try {
			response = await this.offlineCall(name, args);
		} catch (error) {
			this.busy = null;
			if (error.sessionEnded) return;
			response = this.offlineRefusal(
				"OFFLINE_STORE_FAILED",
				__("Could not keep the transaction on this device"),
				__("The station storage is not available."),
				__("Keep the sets aside and call R10.")
			);
		}
		this.busy = null;
		if (response && response.ok === false)
			this.reject(response.error, { method: T1_API + name, args });
		else onOk(response);
		this.station.focus(true);
		this.runQueued();
	}

	// ---- RPC ----
	async request(name, args, onOk) {
		if (this.busy || !this.station.session) return;
		if (this.localReceipt()) return this.offlineRequest(name, args, onOk);
		const method = T1_API + name;
		const version = this.station.sessionVersion;
		const sig = method + JSON.stringify(args);
		if (!this.pending || this.pending.sig !== sig) {
			this.pending = { sig, method, args, onOk, key: uuid4(), ts: clientTs() };
		}
		const pending = this.pending;
		this.busy = method;
		this.refreshNotice();
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
		else if (response && response.ok === false) this.reject(response.error, pending);
		else onOk(response);
		this.station.focus(true);
		this.runQueued();
	}

	runQueued() {
		if (this.busy || !this.queue.length) return;
		this.scan(this.queue.shift());
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
		if (pending)
			return this.request(pending.method.slice(T1_API.length), pending.args, pending.onOk);
		this.notice = null;
		this.loaded = false;
		this.show();
	}

	failure(error) {
		this.queue = [];
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
				reason: __("This account cannot receive sets at this station."),
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

	reject(error, pending) {
		this.queue = [];
		this.discarding = false;
		if (T1_RESET_CODES.includes(error.code)) {
			this.receipt = null;
			this.waiting = [];
			this.currentId = null;
		}
		this.lastRefused =
			error.code === "STATUS_INVALID_FOR_STATION" && pending.method === T1_API + "scan_set"
				? pending.args.raw
				: null;
		this.notice = { variant: "error", ...error };
		this.loaded = true;
		this.show();
	}

	// ---- thao tác trên màn ----
	onAction(action, button) {
		const handlers = {
			retry: () => this.retry(),
			manual: () => this.toggleManual(true),
			"manual-cancel": () => this.toggleManual(false),
			"manual-open": () => this.openManual(),
			"confirm-set": () => this.confirmSet(false),
			"confirm-anyway": () => this.confirmSet(true),
			photo: () => this.pickPhoto(),
			open: () => this.openItem(button.dataset.set),
			"today-toggle": () => this.toggleToday(button.dataset.receipt),
			"today-retry": () => this.loadToday(),
			submit: () => this.submit(),
			discard: () => this.discard(),
			force: () => this.openForce(),
			"force-cancel": () => this.closeForce(),
			"force-submit": () => this.submitForce(),
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		this.station.focus(true);
		return true;
	}

	toggleManual(open) {
		this.manual = open;
		this.notice = null;
		this.show();
		if (open) {
			const select = this.result.querySelector("#tc-t1-dept");
			if (select) select.focus();
		}
	}

	openItem(setId) {
		this.currentId = setId;
		this.notice = null;
		this.imagesReady = false;
		this.show();
		// bộ chưa có chi tiết (phiếu mở lại sau khi tải lại trang): quét lại để lấy dòng BOM
		if (!this.current() && this.receipt) this.addSet(setId, {}, true);
	}

	onInput(event) {
		if (event.target.matches(".tc-t1-actual")) return this.onActual(event.target);
		if (event.target.id !== "tc-t1-note" || !this.currentId) return;
		this.notes[this.currentId] = event.target.value;
	}

	// Không vẽ lại bảng khi đang gõ: giữ focus và con trỏ của ô số lượng
	onActual(box) {
		const item = this.current();
		const line = item && item.lines[Number(box.dataset.line)];
		if (!line) return;
		const raw = String(box.value).trim();
		line.actual_qty = raw === "" ? null : Number(raw);
		line.confirmed = line.actual_qty === line.qty ? 1 : 0;
		const row = box.closest("tr");
		if (row) row.classList.toggle("is-diff", !line.confirmed);
		const foot = this.result.querySelector("[data-region='foot']");
		if (foot) foot.innerHTML = this.footHtml(item);
	}

	noteOf(item) {
		return this.currentId in this.notes ? this.notes[this.currentId] : item.note || "";
	}

	unticked(item) {
		return item.lines.filter((line) => line.actual_qty !== line.qty);
	}

	confirmSet(anyway) {
		const item = this.current();
		if (!item) return;
		const note = this.noteOf(item).trim();
		if (item.lines.some((line) => line.actual_qty === null || Number.isNaN(line.actual_qty))) {
			this.notice = {
				variant: "error",
				title: __("Actual quantity is missing"),
				reason: __("Every component needs an actual quantity."),
				action: __("Enter the actual quantity, then confirm the set."),
			};
			return this.show();
		}
		const missing = this.unticked(item);
		if (missing.length && !note && !anyway) {
			// nhắc trước khi cho xác nhận (FR-M2-23.6); server vẫn kiểm lại
			this.notice = {
				variant: "warn",
				code: "CONFIRM_INCOMPLETE",
				title: __("Some components are not confirmed"),
				reason: __(
					"{0} component(s) differ from the BOM quantity and there is no abnormal note.",
					[missing.length]
				),
				items: missing.map((line) => `${line.instrument_name} (${line.instrument})`),
				action: __(
					"Correct the actual quantity, write an abnormal note, or confirm the set anyway."
				),
			};
			return this.show();
		}
		this.notice = null;
		return this.request(
			"confirm_line",
			{
				receipt: this.receipt.receipt,
				set_id: item.set_id,
				station: this.station.station,
				lines: item.lines.map((line) => ({
					instrument: line.instrument,
					confirmed: line.actual_qty === line.qty ? 1 : 0,
					actual_qty: line.actual_qty,
				})),
				note,
				finalize: 1,
				ack_incomplete: anyway ? 1 : 0,
			},
			(res) => {
				this.waiting = this.waiting.filter((row) => row.set_id !== res.item.set_id);
				delete this.notes[res.item.set_id];
				this.upsertSummary(res.item);
				const next = this.waiting[this.waiting.length - 1];
				this.currentId = next ? next.set_id : null;
				this.notice = {
					variant: "ok",
					title: __("Set {0} confirmed", [res.item.set_id]),
					reason: res.item.needs_review
						? __("The set has an abnormal note; assembly will check it in detail.")
						: "",
					action: __("Scan the next set, or submit the receipt."),
				};
				this.imagesReady = false;
				this.show();
			}
		);
	}

	upsertSummary(item) {
		const summary = {
			set_id: item.set_id,
			set_name: item.set_name,
			set_type: item.set_type,
			status_before: item.status_before,
			bom_version: item.bom_version,
			confirmed: item.confirmed,
			needs_review: item.needs_review,
			forced: item.forced,
			lines_total: item.lines_total,
			lines_confirmed: item.lines_confirmed,
		};
		const items = this.receipt.items.slice();
		const at = items.findIndex((row) => row.set_id === item.set_id);
		if (at >= 0) items[at] = summary;
		else items.push(summary);
		this.receipt = {
			...this.receipt,
			items,
			set_count: items.length,
			flagged_count: items.filter((row) => row.needs_review).length,
		};
	}

	submit() {
		if (!this.receipt || this.waiting.length || !this.receipt.items.length) return;
		return this.request(
			"submit",
			{ receipt: this.receipt.receipt, station: this.station.station },
			(res) => {
				this.done = res;
				this.receipt = null;
				this.waiting = [];
				this.currentId = null;
				this.notice = null;
				this.show();
				this.loadToday(); // phiếu vừa ghi sổ vào danh sách hôm nay
			}
		);
	}

	discard() {
		if (!this.receipt) return;
		if (!this.discarding) {
			this.discarding = true;
			return this.show();
		}
		this.discarding = false;
		return this.request(
			"discard",
			{ receipt: this.receipt.receipt, station: this.station.station },
			(res) => this.applyOpen(res)
		);
	}

	// ---- tiếp nhận cưỡng bức (R02, FR-M2-02.2) ----
	openForce() {
		if (!this.lastRefused) return;
		this.force = { raw: this.lastRefused };
		this.show();
		const box = this.result.querySelector("#tc-t1-force-reason");
		if (box) box.focus();
	}

	closeForce() {
		this.force = null;
		this.show();
	}

	async submitForce() {
		const reason = (this.result.querySelector("#tc-t1-force-reason") || {}).value || "";
		const pin = ((this.result.querySelector("#tc-t1-force-pin") || {}).value || "").trim();
		if (!reason.trim() || !/^\d{6}$/.test(pin)) {
			this.notice = {
				variant: "error",
				title: __("Reason and PIN are required"),
				reason: __("Forced receipt needs a reason and the 6-digit PIN of R02."),
				action: __("Enter the reason and the PIN, then confirm."),
			};
			this.show();
			return;
		}
		const raw = this.force.raw;
		let proof;
		try {
			const res = await this.station.rpc(T1_VERIFY_PIN, {
				token: this.station.session.token,
				pin,
				client_ts: clientTs(),
			});
			if (res.ok === false) {
				this.notice = { variant: "error", ...res.error };
				return this.show();
			}
			proof = res.proof;
		} catch (error) {
			if (error.sessionEnded) return;
			return this.failure(error);
		}
		this.notice = null;
		this.addSet(raw, { force_reason: reason.trim(), reviewer_proof: proof });
	}

	// ---- ảnh bất thường ----
	pickPhoto() {
		const file = this.result.querySelector("#tc-t1-photo");
		if (file) file.click();
	}

	async onPhoto(event) {
		const file = event.target.files && event.target.files[0];
		const item = this.current();
		event.target.value = "";
		if (!file || !item) return;
		let content;
		try {
			content = await this.shrink(file);
		} catch (error) {
			this.notice = {
				variant: "error",
				title: __("Photo is not valid"),
				reason: __("The photo could not be read."),
				action: __("Take the photo again (JPEG, PNG or WebP, up to 5 MB)."),
			};
			return this.show();
		}
		this.request(
			"attach_photo",
			{
				receipt: this.receipt.receipt,
				set_id: item.set_id,
				file_name: file.name || "photo.jpg",
				content,
				station: this.station.station,
			},
			(res) => {
				// giữ tick và ghi chú đang gõ: chỉ lấy ảnh và cờ Cần xem xét từ server
				item.photo = res.item.photo;
				item.needs_review = res.item.needs_review;
				this.notice = null;
				this.refresh();
			}
		);
	}

	// Thu nhỏ ảnh chụp từ camera PDA (cạnh dài ≤ 1600 px, JPEG) để nằm trong giới hạn 5 MB của server
	shrink(file) {
		return new Promise((resolve, reject) => {
			const url = URL.createObjectURL(file);
			const image = new Image();
			image.onload = () => {
				const scale = Math.min(1, T1_PHOTO_MAX_EDGE / Math.max(image.width, image.height));
				const canvas = document.createElement("canvas");
				canvas.width = Math.max(1, Math.round(image.width * scale));
				canvas.height = Math.max(1, Math.round(image.height * scale));
				canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
				URL.revokeObjectURL(url);
				resolve(canvas.toDataURL("image/jpeg", 0.85).split(",")[1]);
			};
			image.onerror = () => {
				URL.revokeObjectURL(url);
				reject(new Error("unreadable"));
			};
			image.src = url;
		});
	}

	// ---- trạng thái mạng ----
	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	// ---- phiếu đã tiếp nhận hôm nay (A-67): chỉ đọc, của mọi người nhận tại trạm ----
	async loadToday() {
		if (this.todayBusy || !this.station.session || this.station.isOffline()) return;
		const version = this.station.sessionVersion;
		this.todayBusy = true;
		this.todayFailed = false;
		this.todaySets = {};
		try {
			const res = await this.station.rpcRead(T1_API + "received_today", {
				station: this.station.station,
				client_ts: clientTs(),
			});
			if (version !== this.station.sessionVersion) return;
			if (res && res.ok) this.today = res;
			else this.todayFailed = this.station.failureCause(null, res);
		} catch (error) {
			if (error.sessionEnded) return;
			this.todayFailed = this.station.failureCause(error);
		} finally {
			this.todayBusy = false;
		}
		if (version === this.station.sessionVersion) this.refreshToday();
	}

	async toggleToday(receipt) {
		if (!receipt) return;
		if (this.todayOpen === receipt) {
			this.todayOpen = null;
			return this.refreshToday();
		}
		this.todayOpen = receipt;
		if (!Array.isArray(this.todaySets[receipt])) {
			this.todaySets[receipt] = "loading";
			this.refreshToday();
			const version = this.station.sessionVersion;
			let sets = "failed";
			try {
				const res = await this.station.rpcRead(T1_API + "receipt_sets", {
					receipt,
					station: this.station.station,
					client_ts: clientTs(),
				});
				if (res && res.ok) sets = res.sets || [];
			} catch (error) {
				if (error.sessionEnded) return;
			}
			if (version !== this.station.sessionVersion) return;
			this.todaySets[receipt] = sets;
		}
		this.refreshToday();
	}

	refreshToday() {
		const node = this.result.querySelector('[data-region="today"]');
		if (node) node.innerHTML = this.todayHtml();
	}

	todayHtml() {
		if (!this.today) {
			if (this.todayFailed)
				return `<section class="tc-t4-block tc-t1-today">
					<p class="tc-hint">${esc(__("Could not load the receipts received today."))}</p>
					<p class="tc-hint">${esc(this.todayFailed)}</p>
					<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="today-retry">${esc(
						__("Retry")
					)}</button></div>
				</section>`;
			return `<section class="tc-t4-block tc-t1-today"><p class="tc-loading">${esc(
				__("Loading...")
			)}</p></section>`;
		}
		const today = this.today;
		const title = __("Receipts received today ({0} receipts, {1} sets)", [
			today.total_receipts,
			today.total_sets,
		]);
		// #1831 S-04: chỉ họ tên, mã nhân viên để tooltip
		const who = (code, name) =>
			`<td${name && code ? ` title="${esc(code)}"` : ""}>${esc(name || code)}</td>`;
		const rows = today.receipts
			.map((row) => {
				const open = this.todayOpen === row.receipt;
				const flag = row.flagged_count
					? `<span class="tc-badge tc-badge-o"><span aria-hidden="true">!</span> ${esc(
							row.flagged_count
					  )}</span>`
					: esc(row.flagged_count);
				return `<tr data-receipt="${esc(row.receipt)}">
					<td><button type="button" class="tc-btn tc-btn-secondary tc-mono" data-action="today-toggle" data-receipt="${esc(
						row.receipt
					)}" aria-expanded="${open}">${esc(row.receipt)}</button></td>
					<td>${esc(String(row.received_at || "").slice(11, 16))}</td>
					<td>${esc(row.department_name || row.department)}</td>
					${who(row.deliverer, row.deliverer_name)}
					${who(row.receiver, row.receiver_name)}
					<td>${esc(row.set_count)}</td>
					<td>${flag}</td>
				</tr>${
					open
						? `<tr class="tc-t1-today-sets"><td colspan="7">${this.todaySetsHtml(
								row.receipt
						  )}</td></tr>`
						: ""
				}`;
			})
			.join("");
		return `<section class="tc-t4-block tc-t1-today" aria-label="${esc(title)}">
			<h3>${esc(title)}</h3>
			${
				rows
					? `<table class="tc-t2-table"><thead><tr>
						<th scope="col">${esc(__("Receipt", null, "Dirty Receipt"))}</th>
						<th scope="col">${esc(__("Received at"))}</th>
						<th scope="col">${esc(__("Returning Department", null, "Dirty Receipt"))}</th>
						<th scope="col">${esc(__("Deliverer", null, "Dirty Receipt"))}</th>
						<th scope="col">${esc(__("Receiver", null, "Dirty Receipt"))}</th>
						<th scope="col">${esc(__("Sets"))}</th>
						<th scope="col">${esc(__("Abnormal note"))}</th>
					</tr></thead><tbody>${rows}</tbody></table>`
					: `<p class="tc-empty">${esc(__("No receipt has been received today."))}</p>`
			}
		</section>`;
	}

	todaySetsHtml(receipt) {
		const sets = this.todaySets[receipt];
		if (sets === "failed")
			return `<p class="tc-hint">${esc(__("Could not load the sets of this receipt."))}</p>`;
		if (!Array.isArray(sets)) return `<p class="tc-loading">${esc(__("Loading..."))}</p>`;
		if (!sets.length) return `<p class="tc-hint">${esc(__("This receipt has no set."))}</p>`;
		return `<ul class="tc-t1-today-list">${sets
			.map(
				(row) =>
					`<li><b class="tc-mono">${esc(row.set_id)}</b> ${esc(
						row.set_name
					)} <span class="tc-badge">${esc(__(row.status, null, "Set Unit"))}</span></li>`
			)
			.join("")}</ul>`;
	}

	updatePlaceholder() {
		const text = this.receipt
			? __("Scan the Set ID of the next set...")
			: __("Scan the employee card of the deliverer...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
		// #1832 T1-03: nhãn liên kết của ô quét theo đúng bước
		for (const label of this.input.labels || []) label.textContent = text;
	}

	show() {
		this.updatePlaceholder();
		if (this.offline && !this.receipt && !this.offlineReady()) {
			return this.station.setState("offline", this.offlineHtml());
		}
		if (!this.loaded && !this.notice && !this.busy) {
			this.loadResume();
			return this.station.renderLoading();
		}
		const error = this.notice && this.notice.variant === "error";
		const state = error ? "error" : this.receipt || this.done ? "result" : "empty";
		this.station.setState(
			state,
			`<div class="tc-t1">
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.done ? this.doneHtml() : ""}
				${this.receipt ? this.receiptHtml() : this.startHtml()}
				<div data-region="today">${this.todayHtml()}</div>
			</div>`
		);
		this.station.form.classList.toggle("is-error", Boolean(error));
		this.watchImages();
		if (error) window.scrollTo({ top: 0 });
	}

	loadResume() {
		if (this.busy) return;
		this.request("open", { station: this.station.station }, (res) => this.applyOpen(res));
	}

	// cập nhật từng vùng, giữ nguyên ô ghi chú đang gõ
	refresh() {
		if (!this.result.querySelector(".tc-t1")) return this.show();
		const regions = {
			notice: () => this.noticeHtml(),
			lines: () => this.linesHtml(this.current()),
			foot: () => this.footHtml(this.current()),
			list: () => this.listHtml(),
			bar: () => this.barHtml(),
			photo: () => this.photoNoteHtml(this.current()),
			today: () => this.todayHtml(),
		};
		this.result.querySelectorAll("[data-region]").forEach((node) => {
			const build = regions[node.dataset.region];
			if (build) node.innerHTML = build();
		});
		this.watchImages();
	}

	refreshNotice() {
		const node = this.result.querySelector('[data-region="notice"]');
		if (node) node.innerHTML = this.noticeHtml();
	}

	watchImages() {
		// "Xác nhận tất cả" chỉ bật khi mọi ảnh của lưới BOM đã tải xong hoặc báo lỗi (như T4, D1)
		const item = this.current();
		const images = [...this.result.querySelectorAll(".tc-inst img")];
		if (this.imagesReady || !item || !images.length) {
			if (item && !images.length && !this.imagesReady) {
				this.imagesReady = true;
				this.refresh();
			}
			return;
		}
		const check = () => {
			if (this.imagesReady || this.current() !== item) return;
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
			.map(
				(item) =>
					`<li>${esc(typeof item === "object" ? item.reason || item.set_id : item)}</li>`
			)
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
				reason: this.offlineReady()
					? __(
							"Receiving continues from the data loaded before the connection was lost; the receipt is sent when the connection returns."
					  )
					: __("Receiving sets needs a network connection."),
				action: this.offlineReady()
					? __("Photos and forced receipt need the connection.")
					: __("Retry when the connection returns."),
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
			let buttons = "";
			if (this.notice.technical) buttons = this.standardButtons();
			else if (this.notice.code) buttons = this.station.businessButtons(this.notice);
			else if (this.notice.code === "CONFIRM_INCOMPLETE")
				buttons = `<div class="tc-actions">
					<button type="button" class="tc-btn tc-btn-warn" data-action="confirm-anyway">${esc(
						__("Confirm the set anyway")
					)}</button>
				</div>`;
			else if (this.notice.code === "STATUS_INVALID_FOR_STATION" && this.lastRefused)
				buttons = this.forceButton();
			else if (!this.receipt && this.notice.variant === "error")
				buttons = `<div class="tc-actions">
					<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
						__("Call R02")
					)}</button>
				</div>`;
			html += this.alertHtml(this.notice, buttons);
		}
		return html;
	}

	forceButton() {
		if (!this.roles().includes("TC R02")) return "";
		return `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-warn" data-action="force">${esc(
				__("Receive by force (R02)")
			)}</button>
		</div>`;
	}

	// ---- chưa có phiếu: quét thẻ người giao hoặc nhập tay ----
	startHtml() {
		const prompt = `<section class="tc-t4-block">
			<p class="tc-empty">${esc(__("Scan the employee card of the person who hands the sets over."))}</p>
			${this.manual ? "" : this.manualButtonHtml()}
		</section>`;
		return this.manual ? this.manualHtml() : prompt;
	}

	manualButtonHtml() {
		return `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-secondary" data-action="manual">${esc(
				__("Deliverer has no card")
			)}</button>
		</div>`;
	}

	manualHtml() {
		const options = this.departments
			.map(
				(row) =>
					`<option value="${esc(row.name)}">${esc(
						row.department_name || row.name
					)}</option>`
			)
			.join("");
		return `<section class="tc-t4-block">
			<h3>${esc(__("Deliverer without a card"))}</h3>
			<div class="tc-field">
				<label for="tc-t1-dept">${esc(__("Returning Department"))} *</label>
				<select id="tc-t1-dept"><option value="">${esc(
					__("Choose the department")
				)}</option>${options}</select>
			</div>
			<div class="tc-field">
				<label for="tc-t1-name">${esc(__("Deliverer Name"))} *</label>
				<input id="tc-t1-name" type="text" autocomplete="off" />
			</div>
			<p class="tc-hint">${esc(__("R02 will issue a card for this person later."))}</p>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="manual-open">${esc(
					__("Open receipt")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="manual-cancel">${esc(
					__("Cancel")
				)}</button>
			</div>
		</section>`;
	}

	// ---- phiếu đang mở ----
	receiptHtml() {
		const receipt = this.receipt;
		const item = this.current();
		return `<section class="tc-t4-block tc-t1-head">
				<div class="tc-res-head">
					<b class="tc-code">${esc(receipt.receipt)}</b>
					<span class="tc-badge">${esc(receipt.department_name || receipt.department)}</span>
					${receipt.needs_card ? `<span class="tc-badge tc-badge-o">${esc(__("Needs card"))}</span>` : ""}
				</div>
				<dl class="tc-res-grid">
					<dt>${esc(__("Deliverer"))}</dt><dd>${esc(receipt.deliverer_name)}</dd>
				</dl>
			</section>
			${this.force ? this.forceFormHtml() : ""}
			${item ? this.itemHtml(item) : ""}
			<section class="tc-t4-block"><div data-region="list">${this.listHtml()}</div></section>
			<div class="tc-actionsbar" data-region="bar">${this.barHtml()}</div>`;
	}

	itemHtml(item) {
		const tray = (item.tray_images || [])[0];
		const trayUrl = tray && (tray.thumbnail_url || tray.image_url);
		const figure = trayUrl
			? `<figure class="tc-tray">
				<img src="${esc(trayUrl)}" alt="${esc(__("Arranged set photo"))}">
				<figcaption>${esc(__("Arranged set photo"))}</figcaption>
			</figure>`
			: "";
		const variant = T1_STATUS_BADGE[item.status_before] || "";
		return `<section class="tc-t4-block tc-t1-item">
			<div class="tc-res-head">
				<b class="tc-code">${esc(item.set_id)}</b>
				<span class="tc-badge${variant ? " tc-badge-" + variant : ""}">${esc(
			__(item.status_before, null, "Set Unit")
		)}</span>
				${item.forced ? `<span class="tc-badge tc-badge-o">${esc(__("Forced receipt"))}</span>` : ""}
			</div>
			<p class="tc-t4-setname">${esc(item.set_name)}</p>
			<h3>${esc(__("Set components (BOM v{0})", [item.bom_version]))}</h3>
			<div class="tc-bom${
				figure ? " has-tray" : ""
			}">${figure}<div class="tc-inst" data-region="lines">${this.linesHtml(
			item
		)}</div></div>
			<div data-region="foot">${this.footHtml(item)}</div>
			<div class="tc-field">
				<label for="tc-t1-note">${esc(
					__("Abnormal note (missing, damaged, foreign object, sharps)")
				)}</label>
				<textarea id="tc-t1-note" rows="3">${esc(this.noteOf(item))}</textarea>
			</div>
			<div data-region="photo">${this.photoNoteHtml(item)}</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="confirm-set"${
					this.busy ? " disabled" : ""
				}>${esc(__("Confirm set"))}</button>
			</div>
		</section>`;
	}

	photoHtml(url, alt) {
		return url
			? `<img class="tc-photo" src="${esc(url)}" alt="${esc(alt)}">`
			: `<span class="tc-photo tc-photo-empty">${esc(__("No photo"))}</span>`;
	}

	linesHtml(item) {
		if (!item) return "";
		if (!item.lines.length)
			return `<p class="tc-empty">${esc(__("This set type has no BOM."))}</p>`;
		const rows = item.lines
			.map((line, index) => {
				const differs = line.actual_qty !== line.qty;
				const label = `${line.instrument_name}: ${__("Actual quantity")}`;
				return `<tr class="${differs ? "is-diff" : ""}">
					<td>${index + 1}</td>
					<td><span class="tc-t1-line-name" title="${esc(line.instrument)}">${this.photoHtml(
					line.thumbnail || line.image,
					line.instrument_name
				)}<span class="tc-ins-name">${esc(line.instrument_name)}</span></span></td>
					<td>${esc(line.qty)}</td>
					<td><input class="tc-t1-actual" type="number" min="0" max="9999" step="1" inputmode="numeric" data-line="${index}" aria-label="${esc(
					label
				)}" value="${esc(line.actual_qty === null ? "" : line.actual_qty)}"></td>
				</tr>`;
			})
			.join("");
		return `<table class="tc-t2-table tc-t1-lines"><thead><tr>
				<th scope="col">${esc(__("No."))}</th>
				<th scope="col">${esc(__("Instrument name"))}</th>
				<th scope="col">${esc(__("Quantity in set"))}</th>
				<th scope="col">${esc(__("Actual quantity"))}</th>
			</tr></thead><tbody>${rows}</tbody></table>`;
	}

	footHtml(item) {
		if (!item || !item.lines.length) return "";
		const differs = this.unticked(item).length;
		return `<div class="tc-actions"><span class="tc-hint">${
			differs
				? `<span aria-hidden="true">!</span> ${esc(
						__("{0} line(s) differ from the BOM", [differs])
				  )}`
				: `<span aria-hidden="true">&#10003;</span> ${esc(__("All lines match the BOM"))}`
		}</span></div>`;
	}

	photoNoteHtml(item) {
		if (!item) return "";
		return `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-secondary" data-action="photo">${esc(
				__("Take a photo of the abnormality")
			)}</button>
			<input id="tc-t1-photo" class="tc-sr-only" type="file" accept="image/*" capture="environment" tabindex="-1">
			${
				item.photo
					? `<span class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(
							__("Photo attached")
					  )}</span>`
					: `<span class="tc-hint">${esc(__("The photo is optional."))}</span>`
			}
		</div>`;
	}

	listHtml() {
		const receipt = this.receipt;
		if (!receipt) return "";
		const rows = receipt.items
			.map((row) => {
				const state = row.confirmed
					? `<span class="tc-badge tc-badge-g"><span aria-hidden="true">&#10003;</span> ${esc(
							__("Confirmed", null, "Dirty Receipt Item")
					  )}</span>`
					: `<button type="button" class="tc-btn tc-btn-secondary" data-action="open" data-set="${esc(
							row.set_id
					  )}">${esc(__("Open"))}</button>`;
				const flag = row.needs_review
					? `<span class="tc-badge tc-badge-o"><span aria-hidden="true">!</span> ${esc(
							__("Abnormal note")
					  )}</span>`
					: "";
				return `<tr>
					<td class="tc-mono">${esc(row.set_id)}</td>
					<td>${esc(row.set_name)}</td>
					<td>${state} ${flag}</td>
				</tr>`;
			})
			.join("");
		return `<h3>${esc(
			__("{0} sets received · {1} with abnormal note", [
				receipt.items.length,
				receipt.items.filter((row) => row.needs_review).length,
			])
		)}</h3>
			${
				rows
					? `<table class="tc-t2-table"><thead><tr>
						<th scope="col">${esc(__("Set ID"))}</th>
						<th scope="col">${esc(__("Set Name"))}</th>
						<th scope="col">${esc(__("Status"))}</th>
					</tr></thead><tbody>${rows}</tbody></table>`
					: `<p class="tc-hint">${esc(__("No set has been scanned yet."))}</p>`
			}`;
	}

	barHtml() {
		const receipt = this.receipt;
		if (!receipt) return "";
		const waiting = this.waiting.length;
		const empty = !receipt.items.length;
		const hint = empty
			? __("Scan the Set ID of the first set.")
			: waiting
			? __("{0} set(s) are waiting for confirmation.", [waiting])
			: __("All sets are confirmed.");
		const discard = this.discarding
			? `<button type="button" class="tc-btn tc-btn-danger" data-action="discard">${esc(
					__("Confirm: drop this receipt")
			  )}</button>`
			: `<button type="button" class="tc-btn tc-btn-secondary" data-action="discard">${esc(
					__("Drop receipt")
			  )}</button>`;
		return `<button type="button" class="tc-btn tc-btn-primary" data-action="submit"${
			empty || waiting || this.busy ? " disabled" : ""
		}>${esc(__("Submit receipt"))}</button>
			${discard}
			<span class="tc-hint">${esc(hint)}</span>`;
	}

	forceFormHtml() {
		return `<section class="tc-t4-block">
			<h3>${esc(__("Receive by force (R02)"))}</h3>
			<p>${esc(__("Set {0} was refused by the station.", [this.force.raw]))}</p>
			<div class="tc-field">
				<label for="tc-t1-force-reason">${esc(
					__("Why is the set received although it was refused?")
				)} *</label>
				<textarea id="tc-t1-force-reason" rows="3"></textarea>
			</div>
			<div class="tc-field">
				<label for="tc-t1-force-pin">${esc(__("R02 PIN"))} *</label>
				<input id="tc-t1-force-pin" type="password" inputmode="numeric" maxlength="6" autocomplete="off">
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-warn" data-action="force-submit">${esc(
					__("Confirm forced receipt")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="force-cancel">${esc(
					__("Cancel")
				)}</button>
			</div>
		</section>`;
	}

	doneHtml() {
		const done = this.done;
		const rejected = (done.rejected || []).map((row) => `${row.set_id}: ${row.reason}`);
		return `<section class="tc-t4-block">
			${this.alertHtml({
				variant: "ok",
				title: done.offline
					? __("Receipt kept on this device; it is sent when the connection returns")
					: __("Receipt {0} submitted", [done.receipt]),
				reason: __("{0} set(s) are waiting for washing; {1} have an abnormal note.", [
					done.sets.length,
					done.flagged.length,
				]),
				action: __("Scan the employee card of the next deliverer to open a new receipt."),
			})}
			${
				rejected.length
					? this.alertHtml({
							variant: "warn",
							title: __("Some sets were not received"),
							reason: __(
								"These sets were taken by another receipt or are no longer valid."
							),
							items: rejected,
							action: __("Check their status before scanning them again."),
					  })
					: ""
			}
		</section>`;
	}
}
