/* global T4_AGENT_URL */
// Hàng đợi offline của trạm/PDA (FEAT-009, ADR-003, A-40): IndexedDB `tracecore` giữ outbox, snapshot đọc và dải
// Cycle ID cấp trước. Phát lại tuần tự theo client_ts, cùng X-Idempotency-Key, header X-TC-Replay: 2xx → xóa; 4xx →
// xóa (server đã ghi Sync Conflict cho R02); 5xx / mất mạng → dừng, thử lại sau 15 s.
// Nối sau station.js qua hook page_js; TraceCoreStation gọi TcOutbox / tcSync khi chạy.

const TC_DB_NAME = "tracecore";
const TC_DB_VERSION = 1;
const TC_REPLAY_MS = 15000;
const TC_SNAPSHOT_MS = 10 * 60 * 1000;
const TC_RANGE_REFILL = 0.2;
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

	// dải mã của trạm trong ngày: giữ danh sách số đã dùng cục bộ khi server cấp thêm dải
	static async saveRanges(station, ranges) {
		const day = tcLocalDay();
		const id = `${station}|${day}`;
		const old = await TcOutbox.tx("ranges", "readonly", (store) => store.get(id));
		const used = old ? old.used : [];
		return TcOutbox.tx("ranges", "readwrite", (store) => store.put({ id, ranges, used }));
	}

	static async rangeState(station) {
		const id = `${station}|${tcLocalDay()}`;
		const row = await TcOutbox.tx("ranges", "readonly", (store) => store.get(id));
		if (!row) return { id, ranges: [], used: [], left: 0, total: 0 };
		const total = row.ranges.reduce((sum, r) => sum + (r.to_no - r.from_no + 1), 0);
		return { ...row, total, left: total - row.used.length };
	}

	// mã offline kế tiếp `CY-YYMMDD-T<NNN>-NNNN` của trạm hôm nay; hết dải → null
	static async nextCode(station) {
		const state = await TcOutbox.rangeState(station);
		const used = new Set(state.used);
		for (const range of state.ranges) {
			for (let no = range.from_no; no <= range.to_no; no++) {
				if (used.has(no)) continue;
				state.used.push(no);
				await TcOutbox.tx("ranges", "readwrite", (store) =>
					store.put({ id: state.id, ranges: state.ranges, used: state.used })
				);
				return `${range.prefix}${String(no).padStart(4, "0")}`;
			}
		}
		return null;
	}
}
TcOutbox.db = null;

// Đồng bộ: một lượt phát lại tại một thời điểm cho cả trang
const tcSync = {
	running: null,
	seq: 0,
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
		if (!entries.length) return this.emit({ queued: 0, sending: 0 });
		let done = 0;
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
			if (response.status >= 500) return this.stop(entry, `HTTP ${response.status}`);
			if (response.status >= 400) this.emit({ conflicts: this.state.conflicts + 1 });
			else await this.printReplayed(entry, response);
			await TcOutbox.remove(entry.key);
			done++;
		}
		this.emit({ queued: 0, sending: 0, error: null, synced_at: Date.now() });
	},

	// gói T4 đóng offline: nhãn in khi có mạng (A-40 D1) — gửi ZPL server vừa dựng sang Station Agent như màn T4;
	// agent lỗi thì nhãn vẫn ở Print Job, in lại từ Desk/T4 như mọi nhãn chờ
	async printReplayed(entry, response) {
		if (
			entry.endpoint !== "tracecore.v1.pack.generate_cycle_id" ||
			typeof T4_AGENT_URL === "undefined"
		)
			return;
		try {
			const data = await response.json();
			const print = data.message && data.message.print;
			if (!print || print.status !== "Queued" || !print.zpl) return;
			await fetch(T4_AGENT_URL, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					zpl: print.zpl,
					print_job: print.print_job,
					printer: print.printer,
				}),
			});
		} catch (error) {
			// không chặn đồng bộ vì máy in
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
