// Hàng đợi offline của trạm/PDA (FEAT-009, ADR-003, A-40): IndexedDB `tracecore` giữ outbox, snapshot đọc và dải
// Cycle ID cấp trước. Phát lại tuần tự theo client_ts, cùng X-Idempotency-Key, header X-TC-Replay: 2xx → xóa; 4xx →
// xóa (server đã ghi Sync Conflict cho R02); 5xx / mất mạng → dừng, thử lại sau 15 s.
// Nối sau station.js qua hook page_js; TraceCoreStation gọi TcOutbox / tcSync khi chạy.

const TC_DB_NAME = "tracecore";
const TC_DB_VERSION = 1;
const TC_REPLAY_MS = 15000;
const TC_SNAPSHOT_MS = 10 * 60 * 1000;
const TC_MAX_ATTEMPTS = 5; // mục lỗi lặp lại quá số lần này được bỏ qua trong lượt phát lại (giữ lại, báo lỗi)
// RPC ghi được xếp hàng khi mất mạng (A-40 Q1): T1 cả phiếu, T4 sinh Cycle ID, T8 xác nhận sử dụng
const TC_QUEUEABLE = [
	"tracecore.v1.receive.submit_offline",
	"tracecore.v1.pack.generate_cycle_id",
	"tracecore.v1.usage.confirm",
];

function tcLocalDay(date = new Date()) {
	const pad = (n) => String(n).padStart(2, "0");
	return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

// mã quét → mã định danh: bỏ tiền tố symbology (]d2, ]Q1…), ký tự điều khiển; GS1 lấy AI (8004) Set ID / (21) Cycle ID
function tcScanId(raw) {
	let text = String(raw || "")
		.replace(/^\][A-Za-z]\d/, "")
		.trim();
	const cycle = /CY-\d{6}-(?:T\d{2,3}-)?\d{4}/.exec(text);
	if (cycle) return cycle[0];
	text = text.replace(/[\x00-\x1f]/g, "\x1d");
	const giai = /(?:^|\x1d)8004([^\x1d]+)/.exec(text);
	return (giai ? giai[1] : text.replace(/\x1d/g, "")).trim();
}

class TcOutbox {
	static open() {
		if (!TcOutbox.db) {
			TcOutbox.db = new Promise((resolve, reject) => {
				if (!window.indexedDB) return reject(new Error("IndexedDB unavailable"));
				const request = indexedDB.open(TC_DB_NAME, TC_DB_VERSION);
				request.onupgradeneeded = () => {
					const db = request.result;
					if (!db.objectStoreNames.contains("outbox"))
						db.createObjectStore("outbox", { keyPath: "key" });
					if (!db.objectStoreNames.contains("snapshot"))
						db.createObjectStore("snapshot", { keyPath: "station" });
					if (!db.objectStoreNames.contains("ranges"))
						db.createObjectStore("ranges", { keyPath: "id" });
				};
				request.onsuccess = () => resolve(request.result);
				request.onerror = () => reject(request.error);
			}).catch((error) => {
				TcOutbox.db = null;
				throw error;
			});
		}
		return TcOutbox.db;
	}

	static async tx(store, mode, work) {
		const db = await TcOutbox.open();
		return new Promise((resolve, reject) => {
			const transaction = db.transaction(store, mode);
			const result = work(transaction.objectStore(store));
			transaction.oncomplete = () =>
				resolve(result && "result" in result ? result.result : result);
			transaction.onerror = () => reject(transaction.error);
			transaction.onabort = () => reject(transaction.error);
		});
	}

	static put(entry) {
		return TcOutbox.tx("outbox", "readwrite", (store) => store.put(entry));
	}

	static async list() {
		const rows = (await TcOutbox.tx("outbox", "readonly", (store) => store.getAll())) || [];
		return rows.sort(
			(a, b) => Date.parse(a.client_ts) - Date.parse(b.client_ts) || a.seq - b.seq
		);
	}

	static remove(key) {
		return TcOutbox.tx("outbox", "readwrite", (store) => store.delete(key));
	}

	static async count() {
		try {
			return (await TcOutbox.tx("outbox", "readonly", (store) => store.count())) || 0;
		} catch (error) {
			return 0;
		}
	}

	static saveSnapshot(station, data) {
		return TcOutbox.tx("snapshot", "readwrite", (store) =>
			store.put({ station, data, saved_at: Date.now() })
		);
	}

	static async snapshot(station) {
		try {
			const row = await TcOutbox.tx("snapshot", "readonly", (store) => store.get(station));
			return row ? row.data : null;
		} catch (error) {
			return null;
		}
	}

	// ngày của dải lấy từ chính mã (`CY-YYMMDD-T<NNN>-`), không theo lúc kiosk nhận snapshot (review I8)
	static rangeDay(prefix) {
		const m = /^CY-(\d{2})(\d{2})(\d{2})-/.exec(prefix || "");
		return m ? `20${m[1]}-${m[2]}-${m[3]}` : null;
	}

	// dải mã của trạm theo ngày của dải: số đã dùng = số dùng cục bộ (chưa đồng bộ) ∪ số server đã ghi sổ (`used`),
	// để thiết bị mất dữ liệu cục bộ không cấp lại mã đã có
	static async saveRanges(station, ranges) {
		const byDay = {};
		for (const range of ranges) {
			const day = TcOutbox.rangeDay(range.prefix);
			if (day) (byDay[day] = byDay[day] || []).push(range);
		}
		for (const [day, rows] of Object.entries(byDay)) {
			const id = `${station}|${day}`;
			const old = await TcOutbox.tx("ranges", "readonly", (store) => store.get(id));
			const used = [
				...new Set([
					...(old ? old.used : []),
					...rows.flatMap((range) => range.used || []),
				]),
			];
			await TcOutbox.tx("ranges", "readwrite", (store) =>
				store.put({ id, ranges: rows, used })
			);
		}
	}

	// mã offline kế tiếp của trạm cho ngày `day` (mặc định hôm nay theo giờ kiosk); đọc và giữ số trong MỘT giao dịch
	// IndexedDB để hai lần bấm liền không lấy trùng số (review I10); hết dải → null
	static async nextCode(station, day = tcLocalDay()) {
		const db = await TcOutbox.open();
		const id = `${station}|${day}`;
		return new Promise((resolve, reject) => {
			const transaction = db.transaction("ranges", "readwrite");
			const store = transaction.objectStore("ranges");
			let code = null;
			store.get(id).onsuccess = (event) => {
				const row = event.target.result;
				if (!row) return;
				const used = new Set(row.used);
				for (const range of row.ranges) {
					for (let no = range.from_no; no <= range.to_no && !code; no++) {
						if (used.has(no)) continue;
						row.used.push(no);
						code = `${range.prefix}${String(no).padStart(4, "0")}`;
					}
					if (code) break;
				}
				if (code) store.put(row);
			};
			transaction.oncomplete = () => resolve(code);
			transaction.onerror = () => reject(transaction.error);
			transaction.onabort = () => reject(transaction.error);
		});
	}
}
TcOutbox.db = null;

// Đồng bộ: một lượt phát lại tại một thời điểm cho cả trang
const tcSync = {
	running: null,
	seq: 0,
	replayedLabels: [], // A-101, A-107: nhãn của gói vừa phát lại, chờ người dùng bấm in một file PDF
	listeners: new Set(),
	state: { queued: 0, sending: 0, conflicts: 0, error: null },

	onChange(fn) {
		this.listeners.add(fn);
		return () => this.listeners.delete(fn);
	},

	emit(patch) {
		Object.assign(this.state, patch);
		for (const fn of this.listeners) fn({ ...this.state });
	},

	queueable(method) {
		return TC_QUEUEABLE.includes(method);
	},

	async refreshCount() {
		this.emit({ queued: await TcOutbox.count() });
	},

	// xếp một RPC ghi vào hàng đợi; giữ nguyên key + client_ts để phát lại idempotent
	async enqueue(station, endpoint, args, key, clientTs) {
		await TcOutbox.put({
			key,
			endpoint,
			args: { ...args, client_ts: clientTs },
			client_ts: clientTs,
			station,
			seq: Date.now() * 1000 + (this.seq++ % 1000),
			attempts: 0,
			state: "queued",
			queued_at: new Date().toISOString(),
		});
		await this.refreshCount();
		return { ok: true, queued: true, key };
	},

	replay() {
		if (this.running) return this.running;
		this.running = this.replayAll().finally(() => {
			this.running = null;
		});
		return this.running;
	},

	async replayAll() {
		if (!navigator.onLine) return;
		let entries;
		try {
			entries = await TcOutbox.list();
		} catch (error) {
			return;
		}
		if (!entries.length) {
			this.noteWaitingLabels();
			return this.emit({ queued: 0, sending: 0 });
		}
		let done = 0;
		let failed = null;
		for (const entry of entries) {
			this.emit({ queued: entries.length - done, sending: done + 1, error: null });
			let response;
			try {
				response = await fetch(`/api/method/${entry.endpoint}`, {
					method: "POST",
					headers: {
						Accept: "application/json",
						"Content-Type": "application/json",
						"X-Frappe-CSRF-Token": frappe.csrf_token,
						"X-TC-Station": entry.station,
						"X-Idempotency-Key": entry.key,
						"X-TC-Replay": "1",
					},
					body: JSON.stringify(entry.args),
					credentials: "same-origin",
				});
			} catch (error) {
				return this.stop(entry, __("No network"));
			}
			// chỉ xóa mục khi chính TraceCore trả lời dứt khoát: ghi nhận (ok) hoặc đã ghi Sync Conflict cho R02.
			// Mọi trả lời khác (proxy 408/413/429, trang HTML của captive portal, 5xx, CSRF…) giữ mục để thử lại (review C1)
			const body = await response.json().catch(() => null);
			const message = body && body.message;
			if (message && message.ok === true) {
				this.noteReplayedLabel(entry, message);
			} else if (
				message &&
				message.ok === false &&
				message.error &&
				message.error.sync_conflict
			) {
				this.emit({ conflicts: this.state.conflicts + 1 });
			} else {
				failed = `HTTP ${response.status}`;
				// mục lỗi lặp lại (≥ TC_MAX_ATTEMPTS lần) không chặn cả hàng đợi: giữ lại, đi tiếp (review I7)
				if (!(await this.fail(entry, failed))) break;
				continue;
			}
			await TcOutbox.remove(entry.key);
			done++;
		}
		this.noteWaitingLabels();
		const queued = await TcOutbox.count();
		this.emit({
			queued,
			sending: 0,
			error: failed,
			synced_at: queued ? this.state.synced_at : Date.now(),
		});
	},

	// ghi lần thử thất bại; trả true nếu mục đã thử quá nhiều lần và được bỏ qua để phát lại các mục sau
	async fail(entry, reason) {
		entry.attempts = (entry.attempts || 0) + 1;
		entry.state = "error";
		entry.last_error = reason;
		await TcOutbox.put(entry);
		return entry.attempts >= TC_MAX_ATTEMPTS;
	},

	// gói T4 đóng offline: nhãn in khi có mạng (A-40 D1); A-101: ra file PDF, không qua Station Agent
	noteReplayedLabel(entry, message) {
		const print = message.print;
		if (entry.endpoint !== "tracecore.v1.pack.generate_cycle_id" || !print) return;
		if (print.status !== "Queued") return; // nhãn chờ: giữ Waiting, quét cuộn ở T4 như mọi nhãn chờ
		this.replayedLabels.push({
			print_job: print.print_job,
			station: entry.station,
			token: entry.args.token,
		});
	},

	// A-107: không tự tải; báo số nhãn chờ để màn trạm hiện nút In n nhãn chờ
	noteWaitingLabels() {
		if (this.replayedLabels.length) this.emit({ waiting_labels: this.replayedLabels.length });
	},

	// bấm nút: mỗi trạm một file PDF cho cả lượt phát lại; lỗi thì nhãn ở lại, nút vẫn còn
	async printWaitingLabels() {
		const labels = this.replayedLabels;
		if (!labels.length) return;
		this.replayedLabels = [];
		for (const station of new Set(labels.map((label) => label.station))) {
			const group = labels.filter((label) => label.station === station);
			const reason = await this.requestLabelsPdf(station, group);
			if (!reason) continue;
			this.replayedLabels.push(...group);
			this.emit({ label_error: reason, label_file: null });
		}
		this.emit({ waiting_labels: this.replayedLabels.length });
	},

	// trả lý do lỗi, hoặc null khi đã lưu file
	async requestLabelsPdf(station, group) {
		try {
			const response = await fetch("/api/method/tracecore.v1.pack.waiting_labels_pdf", {
				method: "POST",
				headers: {
					Accept: "application/json",
					"Content-Type": "application/json",
					"X-Frappe-CSRF-Token": frappe.csrf_token,
					"X-TC-Station": station,
				},
				body: JSON.stringify({
					print_jobs: group.map((label) => label.print_job),
					station,
					token: group[group.length - 1].token,
					client_ts: new Date().toISOString(),
				}),
				credentials: "same-origin",
			});
			const body = await response.json().catch(() => null);
			const message = body && body.message;
			if (message && message.ok && message.pdf_b64) {
				window.tcSavePdf(message.pdf_b64, message.filename);
				this.emit({ label_file: message.filename, label_error: null });
				return null;
			}
			return (message && message.error && message.error.reason) || `HTTP ${response.status}`;
		} catch (error) {
			return __("No network");
		}
	},

	async stop(entry, reason) {
		entry.attempts = (entry.attempts || 0) + 1;
		entry.state = "error";
		entry.last_error = reason;
		await TcOutbox.put(entry);
		this.emit({ queued: await TcOutbox.count(), sending: 0, error: reason });
	},
};

window.addEventListener("online", () => tcSync.replay());
setInterval(() => {
	if (navigator.onLine) tcSync.replay();
}, TC_REPLAY_MS);
