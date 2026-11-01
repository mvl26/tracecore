/* global tcErrorTitle, tcGuideButton, tcWarningsHtml */
// Page station — kiosk trạm quét (surface STN), khung FEAT-001.
// Ô quét luôn focus; 4 trạng thái loading / empty / error / offline (FR-M9-14);
// gọi RPC tracecore.v1.* với X-Idempotency-Key + client_ts (ADR-003).
// Trạm bước T4 giao cho T4Packing (public/js/station_t4.js), bước T6 giao cho T6Storage (public/js/station_t6.js),
// bước T1 giao cho T1Receiving, T2 cho T2Wash, T3 cho T3Assembly, T5 cho T5Load, T7 cho T7Issue (public/js/station_t*.js),
// bước LIN (trạm đồ vải, FEAT-033, FEAT-034) cho LinenStation: LinenCollect (station_linen.js) và LaundryBatch (station_laundry.js);
// các file này nối sau file này qua hook page_js.
// Màn riêng của bước nằm ở this.screen.
/* global T4Packing, T6Storage, T2Wash, T1Receiving, T3Assembly, T5Load, T7Issue, T8Usage, LinenCollect, LinenStation, WasteCollect, WasteStation, TcOutbox, tcSync, TC_SNAPSHOT_MS, TcStationHelp, TcPicker, PICK_SCAN_METHODS */

const RPC_TIMEOUT_MS = 8000;
const RPC_READ_RETRY_MS = 600;
const STATION_IDLE_MS = 10 * 60 * 1000;
const STATION_HEARTBEAT_MS = 30000;
const TC_NOTIFY_MS = 60000; // chuông thông báo hỏi lại mỗi 60 giây (FR-M9-10, SCR-42)
// Lớp màn theo Station Function.screen_key; lớp nằm ở các file nối sau qua page_js nên kiểm typeof lúc chạy.
function tcScreenClass(key) {
	switch (key) {
		case "receive":
			return typeof T1Receiving !== "undefined" ? T1Receiving : null;
		case "wash":
			return typeof T2Wash !== "undefined" ? T2Wash : null;
		case "assembly":
			return typeof T3Assembly !== "undefined" ? T3Assembly : null;
		case "pack":
			return typeof T4Packing !== "undefined" ? T4Packing : null;
		case "sterilize":
			return typeof T5Load !== "undefined" ? T5Load : null;
		case "storage":
			return typeof T6Storage !== "undefined" ? T6Storage : null;
		case "issue":
			return typeof T7Issue !== "undefined" ? T7Issue : null;
		case "usage":
			return typeof T8Usage !== "undefined" ? T8Usage : null;
		case "linen":
			if (typeof LinenStation !== "undefined") return LinenStation; // thu gom + lô giặt (FEAT-034)
			return typeof LinenCollect !== "undefined" ? LinenCollect : null;
		case "waste":
			if (typeof WasteStation !== "undefined") return WasteStation; // thu gom + kho tạm (FEAT-048)
			return typeof WasteCollect !== "undefined" ? WasteCollect : null;
		default:
			return null;
	}
}
const ZONE_LABEL = {
	Dirty: "Dirty zone",
	Clean: "Clean zone",
	Sterile: "Sterile zone",
	Department: "Department",
	Linen: "Linen station",
	Waste: "Waste station",
};
const STATUS_BADGE = {
	New: "x",
	"In Circulation": "",
	Processing: "",
	Reprocess: "o",
	Sterile: "g",
	"At Department": "",
	"Awaiting Receipt": "o",
	"End of Life": "r",
	Disposed: "x",
	Returned: "x",
};

function uuid4() {
	// crypto.randomUUID chỉ có trong secure context; kiosk LAN có thể chạy http
	const bytes = crypto.getRandomValues(new Uint8Array(16));
	bytes[6] = (bytes[6] & 0x0f) | 0x40;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;
	const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(
		16,
		20
	)}-${hex.slice(20)}`;
}

function clientTs(date = new Date()) {
	const pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
	const offset = -date.getTimezoneOffset();
	const sign = offset >= 0 ? "+" : "-";
	return (
		`${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
		`T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}` +
		`${sign}${pad(offset / 60)}:${pad(offset % 60)}`
	);
}

function esc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

// Nhãn gói dùng chung các màn T5-T8 (A-88, #1836): "Tên bộ – Khoa (CY-…)"; thiếu tên thì chỉ còn mã
function tcPackNames(row) {
	return [row.set_name, row.department_name].filter(Boolean).join(" – ");
}

// eslint-disable-next-line no-unused-vars
function tcPackLabel(row) {
	const names = [row.set_name, row.department_name].filter(Boolean).join(" – ");
	return names ? `${names} (${row.cycle_id})` : row.cycle_id || "";
}

// Như `tcPackLabel` nhưng mã dùng font mã định danh
// eslint-disable-next-line no-unused-vars
function tcPackLabelHtml(row) {
	const names = tcPackNames(row);
	const code = `<span class="tc-mono">${esc(row.cycle_id)}</span>`;
	return names ? `${esc(names)} (${code})` : code;
}

// Hàng đợi bộ của bước hiện trên màn chính (#1834 T3-03, #1835 T4-01): chỉ để xem, vẫn quét từng Set ID như T2.
// eslint-disable-next-line no-unused-vars
// #1830 G-02: tiêu đề tab theo trạm; tên trạm đã có số thì không lặp số
function tcStationTitle(station) {
	const label = station.label || station.name || "";
	const prefix = station.station_no && !/^T\d/.test(label) ? `T${station.station_no} ` : "";
	return `${prefix}${label} – TraceCore`;
}

const STATION_ACTIVE_KEY = "tc-station-active";

class TcStepQueue {
	constructor(station, screen) {
		this.station = station;
		this.screen = screen;
		this.reset();
	}

	reset() {
		this.items = null;
		this.total = 0;
		this.failed = null;
		this.busy = false;
	}

	async load(done) {
		const station = this.station;
		if (this.busy || !station.session || station.isOffline()) return;
		const version = station.sessionVersion;
		this.busy = true;
		this.failed = null;
		try {
			const res = await station.rpcRead("tracecore.v1.lookup.set_units", {
				station: station.station,
				screen: this.screen,
				page_length: 20,
				client_ts: clientTs(),
			});
			if (version !== station.sessionVersion) return;
			if (res && res.ok !== false) {
				this.items = res.items || [];
				this.total = res.total || 0;
			} else this.failed = station.failureCause(null, res);
		} catch (error) {
			if (error.sessionEnded) return;
			this.failed = station.failureCause(error);
		} finally {
			this.busy = false;
		}
		if (version === station.sessionVersion) done();
	}

	html(title, empty) {
		if (this.failed)
			return `<section class="tc-t4-block tc-step-queue">
				<p class="tc-hint">${esc(this.failed)}</p>
			</section>`;
		if (!this.items)
			return `<section class="tc-t4-block tc-step-queue"><p class="tc-loading">${esc(
				__("Loading...")
			)}</p></section>`;
		const heading = title(this.total);
		const body = this.items.length
			? this.items
					.map((row) => {
						const detail = [row.name, row.department_name].filter(Boolean).join(" · ");
						return `<p data-set="${esc(row.id)}"><b class="tc-code">${esc(
							row.id
						)}</b> ${esc(detail)}</p>`;
					})
					.join("")
			: `<p class="tc-empty">${esc(empty)}</p>`;
		return `<section class="tc-t4-block tc-step-queue" aria-label="${esc(heading)}">
			<h3>${esc(heading)}</h3>
			${body}
		</section>`;
	}
}

class TraceCoreStation {
	constructor(wrapper, authBarrier = Promise.resolve()) {
		this.wrapper = wrapper;
		this.station = new URLSearchParams(window.location.search).get("station");
		this.stationInfo = null;
		// lần quét chưa có phản hồi dứt khoát: {raw, key, ts} — Thử lại gửi lại y nguyên key + client_ts
		this.pending = null;
		this.lastRaw = null;
		this.pendingScans = []; // mã quét đến khi màn của bước đang chờ máy chủ: quét lại khi màn rảnh
		this.scanTimer = null;
		this.manualOffline = false;
		this.visible = false;
		this.session = null;
		this.sessionVersion = 0;
		this.authGeneration = 0;
		this.restoreCandidate = null;
		this.queuedLogin = null;
		this.authWorker = null;
		this.authBarrier = authBarrier;
		this.disposed = false;
		this.listeners = [];
		this.globalListeners = [];
		this.controllers = new Set();
		this.sessionTimer = null;
		this.notifyTimer = null;
		this.authBusy = false;
		this.heartbeatBusy = false;
		this.lastActivity = Date.now();
		this.heartbeatActivity = 0;
		this.heartbeatAttempt = 0;
		this.pinChange = null; // modal đổi PIN tạm bắt buộc: {overlay, error, busy}

		$(wrapper).html(frappe.render_template("station", {}));
		this.root = wrapper.querySelector(".tc-station");
		// máy kiosk chỉ hiện tên; riêng admin có đường về trang chủ, nạp lại để bỏ ?station= khỏi URL
		const roles = frappe.user_roles || [];
		this.adminMode = roles.includes("System Manager");
		// role làm tại trạm có hàng nút trạm; role văn phòng có đường về trang chủ (NAV-04)
		this.railMode = this.adminMode || roles.some((role) => /^TC R0[2-8]$/.test(role));
		const hasHome = this.adminMode || roles.some((role) => /^TC R(01|02|09|10)$/.test(role));
		for (const brand of this.root.querySelectorAll(".tc-brand")) {
			if (hasHome)
				brand.addEventListener("click", (event) => {
					event.preventDefault();
					event.stopPropagation();
					window.location.assign(brand.getAttribute("href"));
				});
			else brand.removeAttribute("href");
		}
		this.zonebar = this.root.querySelector(".tc-zonebar");
		this.banner = this.root.querySelector(".tc-offline-banner");
		this.form = this.root.querySelector(".tc-work .tc-scan");
		this.input = this.root.querySelector("#tc-scan-input");
		window.tcBindScanLabel(this.input);
		this.result = this.root.querySelector(".tc-result");
		this.authForm = this.root.querySelector(".tc-auth-form");
		this.cardInput = this.root.querySelector("#tc-card-input");
		this.authResult = this.root.querySelector(".tc-auth-result");
		this.work = this.root.querySelector(".tc-work");
		this.sessionBar = this.root.querySelector(".tc-session");
		this.root.dataset.shellMs = String(Math.round(performance.now()));

		this.syncBar = this.root.querySelector(".tc-sync-bar");
		this.offlineData = null; // snapshot đọc offline của trạm (FEAT-009): T1/T4/T8
		this.snapshotAt = 0;

		this.renderNetStatus(0);
		this.setupStationNav();
		this.bind();
		this.addManifestLink();
		this.registerServiceWorker();
		this.notice = this.takeNotice();
		// còn token của trạm này (tải lại trang, đổi trạm): hiện khung xương, không nháy màn quét thẻ
		if (this.storedToken() && !this.notice) this.renderResuming();
		else this.renderLogin(this.notice);
		this.initialHandshake = Promise.resolve();
		if (typeof tcSync !== "undefined") {
			this.unsubscribeSync = tcSync.onChange((state) => this.renderSync(state));
			tcSync.refreshCount();
			tcSync.replay();
		}
	}

	// ---- hàng nút trạm (A-91): một thanh điều hướng, đổi trạm tại chỗ, thao tác vẫn theo thẻ đã quét ----
	setupStationNav() {
		if (!this.railMode) return;
		this.root.classList.toggle("tc-admin-station", this.adminMode);
		frappe
			.call({ method: "tracecore.v1.navigation.context", type: "GET" })
			.then((response) => {
				this.deskStations = this.deskVisibleStations(response.message);
				if (!this.session) this.renderStationPills(this.deskStations);
			})
			.catch(() => {}); // không có danh sách thì vẫn làm được trạm hiện tại
	}

	// trước khi quét thẻ: theo tài khoản Desk; role không quản lý chỉ thấy khu của trạm đang mở (A-91)
	deskVisibleStations(context) {
		const stations = context.stations.filter((station) => station.implemented);
		if (context.see_all_stations) return stations;
		const own = stations.find((station) => station.name === this.station);
		return own ? stations.filter((station) => station.zone === own.zone) : [];
	}

	// sau khi quét thẻ: theo thẻ (A-91); lỗi mạng thì giữ hàng nút đang có
	async loadCardStations() {
		if (!this.railMode || !this.session) return;
		const version = this.sessionVersion;
		try {
			const result = await this.rpc("tracecore.v1.station.stations", {
				token: this.session.token,
			});
			if (version === this.sessionVersion && result && result.ok)
				this.renderStationPills(result.stations);
		} catch (error) {
			// hàng nút không được làm hỏng màn quét
		}
	}

	renderStationPills(stations) {
		const pills = this.root.querySelector(".tc-station-pills");
		// chỉ có trạm hiện tại thì không có gì để đổi
		pills.hidden = stations.filter((station) => station.name !== this.station).length === 0;
		const buttons = stations
			.map((station) => {
				const full = __(station.label);
				const hasNumber = !station.station_no || full.startsWith(`T${station.station_no}`);
				const label = hasNumber ? full : `T${station.station_no} ${full}`;
				const current = station.name === this.station ? ' aria-current="page"' : "";
				return `<button type="button" data-action="tc-switch-station"
					data-station="${esc(station.name)}"${current}>${esc(label)}</button>`;
			})
			.join("");
		pills.innerHTML = buttons;
	}

	renderNetStatus(queued) {
		this.root.querySelector(".tc-net-status").textContent = `${
			this.isOffline() ? __("Offline", null, "TraceCore Launcher") : __("Online")
		} · ${__("{0} transaction(s) waiting", [queued || 0])}`;
	}

	// Đổi trạm không tải lại trang (A-91): bỏ instance cũ, dựng instance mới trên cùng wrapper. Instance mới đi đúng đường
	// của tải lại trang (ping, heartbeat kiểm lại năng lực), mọi màn, giỏ và bộ đếm thuộc trạm cũ được bỏ theo instance cũ.
	openStation(station, label, notice) {
		if (notice) this.storeNotice(notice);
		// phiên trên máy chủ đã đóng hoặc đã chuyển: dispose không được thu hồi token
		this.session = null;
		this.restoreCandidate = null;
		window.history.replaceState(
			window.history.state,
			"",
			`/app/station?station=${encodeURIComponent(station)}`
		);
		const pills = this.root.querySelector(".tc-station-pills").innerHTML;
		const next = new TraceCoreStation(this.wrapper, this.dispose());
		frappe.tc_station = next;
		if (label) next.root.querySelector(".tc-station-name").textContent = label;
		const nav = next.root.querySelector(".tc-station-pills");
		if (next.railMode && pills) nav.innerHTML = pills;
		next.show();
		return next;
	}

	// đưa kết quả lên ngay dưới ô quét (ô quét dính ở đầu màn), không cuộn tay qua phần đầu trang (#1827);
	// `below`: chiều cao khối dính thêm của màn (T3: dòng tên bộ) để nội dung không nằm khuất sau nó
	scrollResultIntoView(target = this.result, below = 0) {
		this.syncStickyHeight();
		const top = target.getBoundingClientRect().top;
		window.scrollTo({ top: window.scrollY + top - this.form.offsetHeight - below });
	}

	syncStickyHeight() {
		this.root.style.setProperty("--tc-scan-h", `${this.form.offsetHeight}px`);
	}

	// Thông báo chặn nằm ngoài khung nhìn thì đưa vào, mỗi thông báo một lần: vẽ lại màn không được giật về thông báo cũ.
	// Cuộn tức thì, không hiệu ứng (motion chỉ theo token); phần dính phía trên do scroll-padding, scroll-margin lo.
	revealNotice(notice) {
		const blocking =
			notice &&
			((notice.variant || "error") === "error" || notice.code === "CONFIRM_INCOMPLETE");
		if (!blocking) {
			this.revealed = null;
			return;
		}
		if (this.revealed === notice) return;
		this.revealed = notice;
		const node = this.result.querySelector(
			'.tc-t3-form .tc-alert, [data-region="notice"] .tc-alert'
		);
		if (!node) return;
		this.syncStickyHeight();
		const box = node.getBoundingClientRect();
		if (box.top < this.form.offsetHeight || box.bottom > window.innerHeight)
			node.scrollIntoView({ block: "start" });
	}

	renderSwitching() {
		this.authResult.innerHTML = `<div class="tc-skeleton" aria-busy="true"><span></span><span></span><span></span></div>
			<span class="tc-sr-only">${esc(__("Loading..."))}</span>`;
	}

	async switchStation(station, label) {
		if (!station || station === this.station || this.switching) return;
		if (!this.session) return this.openStation(station, label);
		if (this.isOffline() || (this.screen && this.screen.busy)) return;
		if (this.pendingScans && this.pendingScans.length) return;
		this.switching = true;
		this.renderSwitching();
		try {
			const result = await this.rpc("tracecore.v1.station.switch_station", {
				token: this.session.token,
				station,
				client_ts: clientTs(),
			});
			if (!result.ok) {
				// khác khu (A-90): máy chủ đã đóng phiên, trạm đích hiện màn quét thẻ kèm lý do
				if (result.error.code === "STATION_ZONE_RESCAN") {
					this.storedToken(null);
					this.rememberActive(null);
					return this.openStation(station, label, result.error);
				}
				this.authResult.innerHTML = this.blockHtml(result.error);
				return;
			}
			// phiên cũ đã đóng; trang mới của trạm đích khôi phục phiên từ token này
			this.storedToken(null);
			sessionStorage.setItem(`tc-station-session:${station}`, result.session.token);
			this.openStation(station, label);
		} catch (error) {
			this.authResult.innerHTML = "";
			this.handleFailure(error);
		} finally {
			this.switching = false;
		}
	}

	storeNotice(error) {
		try {
			sessionStorage.setItem("tc-station-notice", JSON.stringify(error));
		} catch (failure) {
			// PDA tắt storage: trạm đích vẫn hiện màn quét thẻ, chỉ thiếu lý do
		}
	}

	takeNotice() {
		try {
			const raw = sessionStorage.getItem("tc-station-notice");
			sessionStorage.removeItem("tc-station-notice");
			return raw ? JSON.parse(raw) : null;
		} catch (failure) {
			return null;
		}
	}

	// Nút của lỗi nghiệp vụ (A-93): mở trạm của bước phải làm lại, gọi giám sát; không Thử lại, không ngoại tuyến.
	businessButtons(notice) {
		if (!notice || !notice.code || (notice.variant && notice.variant !== "error")) return "";
		const stations = (this.stationInfo && this.stationInfo.gate_stations) || {};
		const redo = notice.redo_step && stations[notice.redo_step];
		const open =
			redo && redo.name !== this.station
				? `<button type="button" class="tc-btn tc-btn-primary" data-action="tc-switch-station" data-station="${esc(
						redo.name
				  )}">${esc(__("Open station {0}", [redo.label]))}</button>`
				: "";
		return `<div class="tc-actions">${open}
			<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
				__("Call R02")
			)}</button>
		</div>`;
	}

	blockHtml(error) {
		return `<div class="tc-card tc-alert tc-alert-error" role="alert">
				<p class="tc-alert-title">${esc(tcErrorTitle(error))}</p>
				<p class="tc-alert-reason">${esc(error.reason)}</p>
				<p class="tc-alert-action">${esc(error.action)}</p>
				${tcGuideButton(error)}</div>`;
	}

	// ---- vòng đời Page ----
	show() {
		if (this.disposed || frappe.tc_station !== this || this.visible) return;
		this.visible = true;
		document.body.classList.add("tc-kiosk");
		this.bindGlobal();
		this.sessionTimer = setInterval(() => {
			if (this.ownsPage()) this.checkSession();
		}, 1000);
		this.notifyTimer = setInterval(() => this.refreshNotifications(), TC_NOTIFY_MS);
		this.initialHandshake = this.handshake();
		this.focus(true);
	}

	hide() {
		this.visible = false;
		for (const [target, name, handler] of this.globalListeners)
			target.removeEventListener(name, handler);
		this.globalListeners = [];
		clearInterval(this.sessionTimer);
		this.sessionTimer = null;
		clearInterval(this.notifyTimer);
		this.notifyTimer = null;
		for (const controller of this.controllers) {
			// A login may already have committed server-side: receive and revoke its stale token.
			if (
				!controller.stationMethod.endsWith("station.login") &&
				!controller.stationMethod.endsWith("station.logout")
			)
				controller.abort();
		}
		const ending = this.endSession(undefined, { keepStoredCandidate: true });
		if (frappe.tc_station === this) document.body.classList.remove("tc-kiosk");
		return ending;
	}

	dispose() {
		const ending = this.hide();
		this.disposed = true;
		for (const [target, name, handler, options] of this.listeners)
			target.removeEventListener(name, handler, options);
		this.listeners = [];
		if (this.unsubscribeSync) this.unsubscribeSync();
		return Promise.all([this.authBarrier, ending, this.authWorker]);
	}

	ownsPage() {
		return !this.disposed && this.visible && frappe.tc_station === this;
	}

	listen(target, name, handler, options) {
		const owned = (event) => {
			if (this.ownsPage()) handler(event);
		};
		target.addEventListener(name, owned, options);
		this.listeners.push([target, name, owned, options]);
	}

	focus(force = false) {
		if (!this.ownsPage()) return;
		// dialog đang mở giữ focus cho ô nhập của nó; đóng dialog thì focus về ô quét
		if (
			(this.screen && this.screen.dialogOpen) ||
			this.pinChange ||
			(this.help && this.help.isOpen) ||
			(this.picker && this.picker.isOpen)
		)
			return;
		// Preserve keyboard navigation and deliberate focus on every interactive control.
		if (
			!force &&
			document.activeElement &&
			document.activeElement.offsetParent !== null &&
			this.root.contains(document.activeElement) &&
			document.activeElement.matches("button, input, textarea, select, a, [tabindex]")
		)
			return;
		const input = this.session ? this.input : this.cardInput;
		if (this.visible && document.activeElement !== input) {
			input.focus({ preventScroll: true });
		}
	}

	bind() {
		this.listen(this.authForm, "submit", (event) => {
			event.preventDefault();
			this.login(this.cardInput.value);
		});
		this.listen(this.form, "submit", (event) => {
			event.preventDefault();
			this.scan(this.input.value);
		});
		this.listen(this.root, "click", (event) => {
			const button = event.target.closest("[data-action]");
			if (button) this.onAction(button.dataset.action, button);
			// nút vừa bấm còn giữ focus (màn không chuyển focus sang ô nhập nào): trả focus về ô quét, để ký tự máy quét
			// không rơi vào nút (Enter còn bấm lại nút)
			setTimeout(() => this.focus(Boolean(button) && document.activeElement === button), 0);
		});
		this.listen(this.input, "blur", () => setTimeout(() => this.focus(), 150));
		this.listen(this.cardInput, "blur", () => setTimeout(() => this.focus(), 150));
		for (const name of ["pointerdown", "keydown", "input", "change"]) {
			this.listen(this.root, name, (event) => this.noteActivity(event), true);
		}
	}

	noteActivity(event) {
		if (!this.session) return;
		// Check the old deadline before counting the first interaction after sleep.
		if (Date.now() - this.lastActivity < STATION_IDLE_MS) {
			this.lastActivity = Date.now();
			return;
		}
		// Chạm Đăng xuất đúng lúc quá hạn: người dùng chủ động thoát, không hiện "Phiên trạm đã bị khóa"
		const leaving =
			event.target.closest &&
			event.target.closest('[data-action="logout"], [data-action="rescan-card"]');
		if (leaving) this.endSession();
		else this.checkSession();
	}

	bindGlobal() {
		const handlers = {
			"tc-card-removed": () => this.endSession(),
			// CustomEvent("tc-card-scanned", {detail: {card_id: string}}) stays separate from T4 scans.
			"tc-card-scanned": (event) => this.login(event.detail && event.detail.card_id),
			offline: () => this.setOffline(true),
			online: () => {
				if (!this.manualOffline) {
					this.setOffline(false);
					this.handshake();
				}
			},
		};
		for (const [name, handler] of Object.entries(handlers)) {
			const owned = (event) => {
				if (this.ownsPage()) handler(event);
			};
			window.addEventListener(name, owned);
			this.globalListeners.push([window, name, owned]);
		}
	}

	onAction(action, button) {
		// Trợ giúp theo trạm (FEAT-013, public/js/station_help.js): mở được cả trước khi quét thẻ
		if (action === "open-help" && typeof TcStationHelp !== "undefined") {
			this.help = this.help || new TcStationHelp(this);
			return this.help.open();
		}
		if (this.help && this.help.onAction(action, button)) return;
		if (
			this.session &&
			action.startsWith("pick-") &&
			this.picker &&
			this.picker.onAction(action, button)
		)
			return;
		if (this.session && action === "manual-pick" && typeof TcPicker !== "undefined") {
			this.picker = this.picker || new TcPicker(this);
			return this.picker.onAction(action, button);
		}
		if (action === "logout" || action === "rescan-card") return this.endSession();
		if (action === "tc-switch-station")
			return this.switchStation(button.dataset.station, button.textContent);
		if (action === "toggle-session-details") return this.toggleSessionDetails();
		if (action === "toggle-station-menu") {
			const open = this.root.classList.toggle("tc-menu-open");
			button.setAttribute("aria-expanded", String(open));
			return;
		}
		if (action === "toggle-notifications") return this.toggleNotifications();
		if (action === "read-notification") return this.readNotification(button.dataset.name);
		if (!this.session) {
			if (action === "retry") {
				this.manualOffline = false;
				return this.handshake();
			}
			return;
		}
		if (action === "tc-screen") return this.switchScreen(button.dataset.screen);
		if (this.screen && this.screen.onAction(action, button)) return;
		if (action === "retry") {
			this.manualOffline = false;
			if (!navigator.onLine) return this.setOffline(true);
			this.setOffline(false);
			if (this.lastRaw) this.scan(this.lastRaw, true);
			else this.handshake();
		} else if (action === "offline") {
			this.manualOffline = true;
			this.setOffline(true);
		} else if (action === "call-r02") {
			const alert = this.result.querySelector(".tc-alert");
			if (alert && !alert.querySelector(".tc-help")) {
				alert.insertAdjacentHTML(
					"beforeend",
					`<p class="tc-help">${esc(
						__("Ask R02 (zone supervisor) at this station for help.")
					)}</p>`
				);
			}
		}
	}

	// ---- employee-card session: bearer stays in memory/tab storage, never in rendered markup ----
	storageKey() {
		return `tc-station-session:${this.station}`;
	}

	storedToken(value) {
		try {
			if (value === undefined) return sessionStorage.getItem(this.storageKey());
			if (value) sessionStorage.setItem(this.storageKey(), value);
			else sessionStorage.removeItem(this.storageKey());
		} catch (error) {
			// Storage may be disabled on a managed PDA; memory-only sessions still work.
		}
		return null;
	}

	// FEAT-052 A-71: cảnh báo không chặn thao tác; nằm trên khối kết quả, thay khi có giao dịch ghi tiếp theo
	showWarnings(body, isWrite) {
		const warnings = (body && body.warnings) || [];
		if (!warnings.length && !isWrite) return;
		if (!this.warningBar) {
			this.warningBar = document.createElement("div");
			this.warningBar.className = "tc-warnings";
			this.result.parentElement.insertBefore(this.warningBar, this.result);
		}
		this.warningBar.innerHTML = tcWarningsHtml(warnings);
	}

	renderResuming() {
		this.authForm.hidden = true;
		this.work.hidden = true;
		this.sessionBar.hidden = true;
		this.renderSwitching();
	}

	renderLogin(error) {
		this.authForm.hidden = false;
		this.work.hidden = true;
		this.sessionBar.hidden = true;
		this.authResult.innerHTML = error ? this.blockHtml(error) : "";
		this.focus();
	}

	clearSession(error, { invalidateAuth = true, keepStoredCandidate = false } = {}) {
		const token =
			(this.session && this.session.token) ||
			(!keepStoredCandidate && this.restoreCandidate && this.restoreCandidate.token);
		if (invalidateAuth) {
			this.authGeneration++;
			this.queuedLogin = null;
		}
		this.restoreCandidate = null;
		this.sessionVersion++;
		this.session = null;
		// A retired instance may share this storage key with its replacement.
		if (!this.disposed && frappe.tc_station === this && token && this.storedToken() === token)
			this.storedToken(null);
		if (token && (this.activeSession() || {}).token === token) this.rememberActive(null);
		this.pending = null;
		this.lastRaw = null;
		this.input.value = "";
		this.cardInput.value = "";
		for (const screen of Object.values(this.screens || {})) {
			if (screen.clearSession) screen.clearSession();
		}
		if (this.screenTabs) this.screenTabs.hidden = true;
		if (this.picker) this.picker.reset();
		this.manualEntry = null;
		this.result.innerHTML = "";
		this.result.dataset.state = "locked";
		this.form.classList.remove("is-error");
		this.closePinChange();
		if (this.help) this.help.sessionChanged();
		for (const selector of [".tc-session-person", ".tc-session-expiry", ".tc-session-roles"])
			this.root.querySelector(selector).textContent = "";
		this.toggleSessionDetails(false);
		this.resetNotifications();
		if (this.deskStations) this.renderStationPills(this.deskStations);
		this.renderLogin(error);
	}

	toggleSessionDetails(open) {
		const details = this.root.querySelector(".tc-session-details");
		details.hidden = open === undefined ? !details.hidden : !open;
		this.root
			.querySelector(".tc-session-more")
			.setAttribute("aria-expanded", String(!details.hidden));
	}

	// ---- thông báo (FEAT-010, SCR-42 trên trạm/PDA) ----
	// Chuông + số chưa đọc cạnh tên người đăng nhập, banner khi có thông báo khẩn, bảng danh sách mở bằng nút chuông.
	// Hỏi lại 60 giây một lần bằng token phiên thẻ (chỉ đọc, không kéo dài phiên); lỗi mạng thì giữ số cũ.
	async notifyCall(method, args) {
		const version = this.sessionVersion;
		const result = await this.rpc(`tracecore.v1.notification.${method}`, {
			...args,
			token: this.session.token,
		});
		return version === this.sessionVersion && result && result.ok ? result : null;
	}

	async refreshNotifications() {
		if (!this.ownsPage() || !this.session || this.isOffline()) return;
		try {
			const result = await this.notifyCall("station_summary", {});
			if (result) this.renderNotifications(result);
		} catch (error) {
			// chuông không được làm hỏng màn quét
		}
	}

	renderNotifications(summary) {
		const button = this.root.querySelector(".tc-notify-btn");
		const banner = this.root.querySelector(".tc-notify-banner");
		button.hidden = false;
		button.querySelector(".tc-notify-count").textContent = String(summary.unread);
		banner.hidden = !summary.urgent;
		banner.innerHTML = summary.urgent ? this.urgentHtml(summary.urgent) : "";
		if (!this.root.querySelector(".tc-notify-panel").hidden) this.loadNotificationPanel();
	}

	// #1831 S-06: thông báo khẩn nói rõ ai xử lý; Xử lý mở chứng từ ở tab mới để không mất phiên trạm
	urgentHtml(urgent) {
		const who = (urgent.handled_by || []).join(", ") || __("You");
		const open =
			urgent.link && urgent.link.startsWith("/")
				? `<a class="tc-btn tc-btn-primary" href="${esc(
						urgent.link
				  )}" target="_blank" rel="noopener">${esc(__("Handle"))}</a>`
				: "";
		return `<span><span>${esc(__("Urgent: {0}", [urgent.subject]))}</span>
				<span class="tc-notify-who">${esc(__("To be handled by: {0}", [who]))}</span></span>
			<span class="tc-notify-actions">${open}
				<button type="button" class="tc-btn tc-btn-secondary" data-action="read-notification" data-name="${esc(
					urgent.name
				)}">${esc(__("Seen"))}</button></span>`;
	}

	async loadNotificationPanel() {
		const panel = this.root.querySelector(".tc-notify-panel");
		try {
			const result = await this.notifyCall("station_inbox", { limit: 20 });
			if (!result) return;
			panel.innerHTML = result.rows.length
				? result.rows
						.map(
							(row) => `<div class="tc-notify-row">
								<span>${
									row.urgency === "Urgent"
										? `<b class="tc-notify-urgent">${esc(
												__("Urgent", null, "Notification Center")
										  )}</b> `
										: ""
								}${esc(row.subject)}</span>
								<button type="button" class="tc-btn tc-btn-secondary" data-action="read-notification" data-name="${esc(
									row.name
								)}">${esc(__("Mark as read"))}</button>
							</div>`
						)
						.join("")
				: `<p>${esc(__("No unread notifications"))}</p>`;
		} catch (error) {
			panel.textContent = __("Cannot load notifications");
		}
	}

	toggleNotifications() {
		const panel = this.root.querySelector(".tc-notify-panel");
		const button = this.root.querySelector(".tc-notify-btn");
		panel.hidden = !panel.hidden;
		button.setAttribute("aria-expanded", String(!panel.hidden));
		if (!panel.hidden) this.loadNotificationPanel();
	}

	async readNotification(name) {
		try {
			const result = await this.notifyCall("station_mark_read", { names: [name] });
			if (result) await this.refreshNotifications();
		} catch (error) {
			// giữ nguyên danh sách; lần hỏi lại kế tiếp sẽ cập nhật
		}
	}

	resetNotifications() {
		this.root.querySelector(".tc-notify-btn").hidden = true;
		this.root.querySelector(".tc-notify-banner").hidden = true;
		const panel = this.root.querySelector(".tc-notify-panel");
		panel.hidden = true;
		panel.innerHTML = "";
	}

	async endSession(error, options = {}) {
		const owner = !this.disposed && frappe.tc_station === this;
		const token = owner
			? (this.session && this.session.token) ||
			  (!options.keepStoredCandidate &&
					((this.restoreCandidate && this.restoreCandidate.token) ||
						(this.ownsPage() && this.storedToken())))
			: null;
		this.clearSession(error, options);
		// Explicit removal also ends a saved credential before/after candidate validation.
		// Hide/dispose preserve unvalidated storage; a retired owner cannot remove a replacement's token.
		if (
			!options.keepStoredCandidate &&
			this.ownsPage() &&
			token &&
			this.storedToken() === token
		)
			this.storedToken(null);
		return this.revokeToken(token);
	}

	async revokeToken(token) {
		if (!token) return;
		try {
			await this.rpc("tracecore.v1.station.logout", { token, client_ts: clientTs() });
		} catch (failure) {
			// Local lock is immediate even offline. Server expiry/revocation remains authoritative.
		}
	}

	activateSession(session) {
		this.session = session;
		this.storedToken(session.token);
		this.rememberActive({ station: this.station, token: session.token });
		this.lastActivity = Date.now();
		this.heartbeatActivity = this.lastActivity;
		this.heartbeatAttempt = Date.now();
		this.notice = null;
		this.authForm.hidden = true;
		this.authResult.innerHTML = "";
		this.sessionBar.hidden = false;
		this.work.hidden = false;
		this.root.querySelector(".tc-session-person").textContent =
			session.employee_name || session.employee;
		// #1831 S-02: chỉ vai trò chính tại trạm; mã nhân viên và đủ vai trò mở bằng nút Chi tiết
		const main = session.station_role || (session.roles || [])[0];
		this.root.querySelector(".tc-session-roles").textContent = main
			? __("Role: {0}", [__(main)])
			: "";
		this.root.querySelector(".tc-session-details").textContent = [
			__("Employee ID: {0}", [session.employee]),
			__("Roles: {0}", [(session.roles || []).map((role) => __(role)).join(", ")]),
		].join(" · ");
		this.root.querySelector(".tc-session-expiry").textContent = __("Session expires: {0}", [
			this.formatExpiry(session.expires_at),
		]);
		if (this.stationInfo) this.applyStation(this.stationInfo);
		this.renderEmpty();
		this.focus(true);
		if (session.pin_change_required) this.openPinChange();
		this.loadBackground();
	}

	// Dữ liệu nền chạy lần lượt (#1825): mỗi RPC theo token khóa dòng Employee, chạy song song với khối của màn làm đầy worker
	// và làm RPC của màn chạm giới hạn 8 giây trên máy chủ ít worker.
	async loadBackground() {
		const version = this.sessionVersion;
		for (const load of [
			() => this.loadCardStations(),
			() => this.refreshNotifications(),
			() => this.loadOfflineData(),
		]) {
			if (version !== this.sessionVersion || !this.ownsPage()) return;
			try {
				await load();
			} catch (error) {
				// dữ liệu nền không được làm hỏng màn quét
			}
		}
	}

	// ---- đổi PIN tạm bắt buộc ngay sau quét thẻ (FR-M9-09, FR-M9-09.1, UC-33 A3) ----
	// PIN do R10/R02 đặt trên Desk là PIN tạm: phiên báo pin_change_required thì modal §4.13 bắt buộc (không Esc, không
	// Hủy) che màn trạm tới khi đổi xong; lối ra duy nhất là Đăng xuất. Lỗi hiện alert-error ngay trong modal.
	pinChangeError({ old_pin, new_pin, confirm_pin }) {
		if (![old_pin, new_pin, confirm_pin].every((pin) => /^\d{6}$/.test(pin || "")))
			return {
				title: __("PIN is invalid"),
				reason: __("PIN must contain exactly 6 digits."),
				action: __("Enter a 6-digit PIN."),
			};
		if (new_pin !== confirm_pin)
			return {
				title: __("New PIN entries do not match"),
				reason: __("The two entries of the new PIN are different."),
				action: __("Enter the same new PIN in both fields."),
			};
		if (new_pin === old_pin)
			return {
				title: __("New PIN must be different"),
				reason: __("The new PIN is the same as the current PIN."),
				action: __("Choose a different PIN."),
			};
		return null;
	}

	pinChangeHtml(error, busy) {
		const field = (name, label) => `<div class="tc-field">
				<label for="tc-pin-${name}">${esc(label)}</label>
				<input id="tc-pin-${name}" name="${name}" class="tc-pin-input" type="password" inputmode="numeric"
					maxlength="6" autocomplete="off">
			</div>`;
		return `<div class="tc-modal-box" role="dialog" aria-modal="true" aria-labelledby="tc-pin-title">
			<h3 id="tc-pin-title">${esc(__("Change your PIN"))}</h3>
			<p class="tc-modal-intro">${esc(
				__(
					"A supervisor set a temporary PIN for you. Choose your own 6-digit PIN before using this station."
				)
			)}</p>
			${
				error
					? `<div class="tc-alert tc-alert-error" role="alert">
				<p class="tc-alert-title"><span aria-hidden="true">&#10005;</span> ${esc(error.title)}</p>
				<p class="tc-alert-reason">${esc(error.reason)}</p>
				<p class="tc-alert-action">${esc(error.action)}</p></div>`
					: ""
			}
			<form class="tc-modal-form" novalidate>
				${field("old_pin", __("Temporary PIN"))}
				${field("new_pin", __("New PIN"))}
				${field("confirm_pin", __("Enter the new PIN again"))}
				<div class="tc-modal-actions">
					<button type="submit" class="tc-btn tc-btn-primary"${busy ? " disabled" : ""}>${esc(
			busy ? __("Saving...", null, "Change PIN") : __("Change PIN")
		)}</button>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="logout">${esc(
						__("Log out")
					)}</button>
				</div>
			</form>
		</div>`;
	}

	openPinChange() {
		if (this.pinChange) return;
		const overlay = document.createElement("div");
		overlay.className = "tc-modal";
		overlay.addEventListener("submit", (event) => {
			event.preventDefault();
			const fields = event.target.elements;
			this.changePin({
				old_pin: fields.old_pin.value,
				new_pin: fields.new_pin.value,
				confirm_pin: fields.confirm_pin.value,
			});
		});
		overlay.addEventListener("keydown", (event) => {
			// modal bắt buộc: Esc không đóng; Tab vòng trong modal
			if (event.key === "Escape") event.preventDefault();
			if (event.key !== "Tab") return;
			const items = [...overlay.querySelectorAll("input, button:not([disabled])")];
			const edge = event.shiftKey ? items[0] : items[items.length - 1];
			if (document.activeElement === edge) {
				event.preventDefault();
				(event.shiftKey ? items[items.length - 1] : items[0]).focus();
			}
		});
		this.pinChange = { overlay, error: null, busy: false };
		this.root.appendChild(overlay);
		this.renderPinChange();
	}

	renderPinChange() {
		const state = this.pinChange;
		if (!state) return;
		state.overlay.innerHTML = this.pinChangeHtml(state.error, state.busy);
		const first = state.overlay.querySelector("input");
		if (first) first.focus({ preventScroll: true });
	}

	closePinChange() {
		if (!this.pinChange) return;
		this.pinChange.overlay.remove();
		this.pinChange = null;
	}

	async changePin(values) {
		const state = this.pinChange;
		if (!state || state.busy) return;
		state.error = this.pinChangeError(values);
		if (state.error) return this.renderPinChange();
		state.busy = true;
		this.renderPinChange();
		try {
			// không gửi X-Idempotency-Key: Idempotency Key lưu băm tham số, PIN 6 số dò ngược được (như station.verify_pin)
			const result = await this.rpc("tracecore.v1.account.change_pin", {
				old_pin: values.old_pin,
				new_pin: values.new_pin,
				client_ts: clientTs(),
			});
			if (this.pinChange !== state) return;
			if (result && result.ok) {
				this.session.pin_change_required = 0;
				this.closePinChange();
				return this.focus(true);
			}
			state.error = result.error;
		} catch (error) {
			if (error.sessionEnded || this.pinChange !== state) return;
			state.error = error.offline
				? {
						title: __("Station offline"),
						reason: __("Changing the PIN needs the server."),
						action: __("Reconnect, then try again."),
				  }
				: {
						title: __("Server error"),
						reason: __("The server could not process the request ({0}).", [
							error.status || "?",
						]),
						action: __("Retry, or call R02 if it happens again."),
				  };
		}
		state.busy = false;
		this.renderPinChange();
	}

	// ---- offline (FEAT-009, ADR-003, A-40) ----
	offlineCapable() {
		return (
			typeof TcOutbox !== "undefined" &&
			Boolean(window.indexedDB) &&
			((this.stationInfo && this.stationInfo.functions) || []).some((code) =>
				["RECEIVE", "PACK", "USE"].includes(code)
			)
		);
	}

	async loadOfflineData() {
		if (!this.offlineCapable()) return;
		this.offlineData = (await TcOutbox.snapshot(this.station)) || this.offlineData;
		return this.refreshSnapshot(true);
	}

	// snapshot đọc offline: khi đăng nhập, rồi mỗi 10 phút khi còn mạng (D4); T4 kèm dải Cycle ID cấp trước
	async refreshSnapshot(force = false) {
		if (!this.offlineCapable() || !this.session || this.isOffline()) return;
		if (!force && Date.now() - this.snapshotAt < TC_SNAPSHOT_MS) return;
		this.snapshotAt = Date.now();
		const version = this.sessionVersion;
		try {
			const data = await this.rpc("tracecore.v1.sync.snapshot", {
				station: this.station,
				client_ts: clientTs(),
			});
			if (version !== this.sessionVersion || !data || !data.ok || !data.offline) return;
			this.offlineData = data;
			await TcOutbox.saveSnapshot(this.station, data);
			if (data.ranges) await TcOutbox.saveRanges(this.station, data.ranges);
		} catch (error) {
			this.snapshotAt = 0; // lần sau thử lại; snapshot cũ vẫn dùng được
		}
	}

	// xếp một RPC ghi của màn bước vào hàng đợi (token của phiên đi cùng để phát lại sau khi khóa máy)
	queueCall(method, args, key, ts) {
		if (!this.session)
			throw Object.assign(new Error("Station session ended"), { sessionEnded: true });
		return tcSync.enqueue(
			this.station,
			method,
			{ ...args, token: this.session.token },
			key,
			ts
		);
	}

	renderSync(state) {
		this.renderNetStatus(state.queued);
		if (!this.syncBar) return;
		let text = "";
		if (state.sending)
			text = __("Syncing {0}/{1}...", [state.sending, state.sending + state.queued - 1]);
		else if (state.queued && state.error)
			text = __("{0} transaction(s) waiting · last attempt failed: {1}", [
				state.queued,
				state.error,
			]);
		else if (state.queued) text = __("Offline – {0} transaction(s) waiting", [state.queued]);
		else if (state.label_error)
			text = __("Labels of offline packs were not printed: {0}", [state.label_error]);
		else if (state.label_file) text = __("Label printed to PDF file: {0}", [state.label_file]);
		else if (state.conflicts)
			text = __("Synced · {0} transaction(s) sent to R02 as sync conflicts", [
				state.conflicts,
			]);
		else if (state.synced_at) text = __("All offline transactions are synced");
		this.syncBar.hidden = !text;
		this.syncBar.textContent = text;
		this.syncBar.dataset.state = state.conflicts ? "warn" : state.queued ? "queued" : "ok";
	}

	formatExpiry(value) {
		const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(value || "");
		return match
			? `${match[3]}/${match[2]}/${match[1]} ${match[4]}:${match[5]}`
			: value || "-";
	}

	login(raw) {
		this.cardInput.value = "";
		if (!this.ownsPage() || !this.station || typeof raw !== "string" || !raw.trim())
			return Promise.resolve();
		const closing = this.endSession();
		const attempt = this.authGeneration;
		this.queuedLogin = { card: raw.trim(), attempt, closing };
		if (this.authWorker) return this.authWorker;
		this.authBusy = true;
		this.authWorker = this.processLogins().finally(() => {
			this.authWorker = null;
			this.authBusy = false;
			this.focus();
		});
		return this.authWorker;
	}

	async processLogins() {
		await this.authBarrier;
		while (this.queuedLogin && this.ownsPage()) {
			const intent = this.queuedLogin;
			this.queuedLogin = null;
			await intent.closing;
			if (!this.stationInfo) await this.initialHandshake;
			if (!this.isCurrentAuth(intent.attempt) || !this.stationInfo) continue;
			if (this.isOffline()) {
				this.setOffline(true);
				continue;
			}
			try {
				const result = await this.rpc("tracecore.v1.station.login", {
					card_id: intent.card,
					station: this.station,
					client_ts: clientTs(),
				});
				if (!this.isCurrentAuth(intent.attempt)) {
					if (result.ok) await this.revokeToken(result.session.token);
					continue;
				}
				if (result.ok) this.activateSession(result.session);
				else this.renderLogin(result.error);
			} catch (error) {
				if (this.isCurrentAuth(intent.attempt)) this.handleFailure(error);
			}
		}
	}

	isCurrentAuth(attempt) {
		return this.ownsPage() && attempt === this.authGeneration;
	}

	// A-102 (#1822): phiên thẻ đang mở của tab này, để mở trạm khác bằng URL đi đúng đường của nút chuyển trạm
	activeSession() {
		try {
			return JSON.parse(sessionStorage.getItem(STATION_ACTIVE_KEY) || "null");
		} catch (failure) {
			return null;
		}
	}

	rememberActive(value) {
		try {
			if (value) sessionStorage.setItem(STATION_ACTIVE_KEY, JSON.stringify(value));
			else sessionStorage.removeItem(STATION_ACTIVE_KEY);
		} catch (failure) {
			// PDA tắt storage: mở bằng URL phải quét thẻ lại
		}
	}

	// true: đã xử lý xong (khôi phục phiên, hoặc màn thẻ kèm lý do); false: hiện màn quét thẻ như thường
	async adoptSession() {
		const active = this.activeSession();
		if (!active || !active.token || active.station === this.station) return false;
		let result;
		try {
			result = await this.rpc("tracecore.v1.station.switch_station", {
				token: active.token,
				station: this.station,
				client_ts: clientTs(),
			});
		} catch (failure) {
			return false; // mất mạng không nói gì về phiên: quét thẻ như thường
		}
		if (result.ok) {
			this.storedToken(result.session.token);
			await this.restoreSession(result.session.token);
			return true;
		}
		const code = (result.error && result.error.code) || "";
		if (code === "STATION_ZONE_RESCAN" || code.startsWith("SESSION_"))
			this.rememberActive(null);
		if (code.startsWith("SESSION_")) return false;
		this.renderLogin(result.error);
		return true;
	}

	async restoreSession(token) {
		const candidate = { token, attempt: ++this.authGeneration };
		this.restoreCandidate = candidate;
		try {
			const result = await this.rpc(
				"tracecore.v1.station.heartbeat",
				{
					token,
					client_ts: clientTs(),
					recheck: 1, // tải lại trang hay đổi trạm đều kiểm lại năng lực (A-90)
				},
				undefined,
				candidate
			);
			if (!this.isCurrentCandidate(candidate)) return;
			if (result.ok && result.station === this.station) {
				this.restoreCandidate = null;
				this.activateSession({ ...result, token });
			} else this.clearSession(result.error);
		} catch (error) {
			if (this.isCurrentCandidate(candidate)) {
				// A transport failure proves nothing about the stored token's validity.
				this.clearSession(undefined, { keepStoredCandidate: true });
				this.handleFailure(error);
			}
		}
	}

	isCurrentCandidate(candidate) {
		return (
			this.isCurrentAuth(candidate.attempt) &&
			this.restoreCandidate === candidate &&
			this.storedToken() === candidate.token
		);
	}

	async heartbeat() {
		if (!this.ownsPage() || !this.session || this.heartbeatBusy || this.isOffline())
			return false;
		this.heartbeatBusy = true;
		const version = this.sessionVersion;
		const activity = this.lastActivity;
		this.heartbeatAttempt = Date.now();
		try {
			const result = await this.rpc("tracecore.v1.station.heartbeat", {
				token: this.session.token,
				client_ts: clientTs(),
			});
			if (!this.ownsPage() || version !== this.sessionVersion) return false;
			this.heartbeatActivity = activity;
			return result;
		} catch (error) {
			if (!error.sessionEnded && this.ownsPage() && version === this.sessionVersion)
				this.handleFailure(error);
			return false;
		} finally {
			this.heartbeatBusy = false;
		}
	}

	async checkSession() {
		if (!this.ownsPage() || !this.session) return;
		if (Date.now() - this.lastActivity >= STATION_IDLE_MS) {
			return this.endSession({
				title: __("Station session was locked"),
				reason: __("There was no activity for 10 minutes."),
				action: __("Scan your employee card again."),
			});
		}
		this.refreshSnapshot();
		// Heartbeat itself must not count as operator activity or keep an idle session alive.
		if (
			this.lastActivity > this.heartbeatActivity &&
			Date.now() - this.heartbeatAttempt >= STATION_HEARTBEAT_MS
		)
			return this.heartbeat();
	}

	// ---- mạng ----
	isOffline() {
		return this.manualOffline || !navigator.onLine;
	}

	setOffline(offline) {
		this.banner.hidden = !offline;
		this.root.dataset.offline = offline ? "1" : "0";
		this.renderNetStatus(typeof tcSync !== "undefined" ? tcSync.state.queued : 0);
		if (!offline && typeof tcSync !== "undefined") tcSync.replay();
		if (!this.session) {
			if (offline)
				this.renderLogin({
					title: __("Station offline"),
					reason: __("Card login needs the server."),
					action: __("Reconnect, then scan your employee card again."),
				});
			return;
		}
		if (this.screen) return this.screen.setOffline(offline);
		if (offline) this.renderOffline();
	}

	async rpc(method, args, idempotencyKey, candidate = null) {
		// RPC của màn trạm cần token phiên thẻ nhân viên (FEAT-003): T4 pack/cuộn nhãn, T6 putaway (FEAT-025),
		// T2 lô rửa (FEAT-021), T1 tiếp nhận (FEAT-019), T3 kiểm đếm lắp ráp (FEAT-020), T7 cấp phát (FEAT-026)
		const protectedCall =
			method.startsWith("tracecore.v1.pack.") ||
			method.startsWith("tracecore.v1.assembly.") ||
			method.startsWith("tracecore.v1.putaway.") ||
			method.startsWith("tracecore.v1.wash.") ||
			method.startsWith("tracecore.v1.issue.") ||
			method.startsWith("tracecore.v1.usage.") ||
			method.startsWith("tracecore.v1.load.") ||
			method.startsWith("tracecore.v1.release.") ||
			method.startsWith("tracecore.v1.daily_test.") ||
			method.startsWith("tracecore.v1.receive.") ||
			method.startsWith("tracecore.v1.linen.") ||
			method.startsWith("tracecore.v1.laundry.") ||
			method.startsWith("tracecore.v1.waste.") ||
			method.startsWith("tracecore.v1.sync.") ||
			method.startsWith("tracecore.v1.lookup.") ||
			method.startsWith("tracecore.v1.code_range.") ||
			method.startsWith("tracecore.v1.feedback.") ||
			method === "tracecore.v1.printer.set_roll" ||
			method === "tracecore.v1.account.change_pin";
		const version = this.sessionVersion;
		const sessionCall =
			!candidate &&
			(protectedCall ||
				method === "tracecore.v1.station.heartbeat" ||
				method === "tracecore.v1.station.switch_station" ||
				method === "tracecore.v1.set_unit.get");
		const activeToken = this.session && this.session.token;
		const ended = () =>
			Object.assign(new Error("Station session ended"), { sessionEnded: true });
		if (protectedCall) {
			if (!this.ownsPage() || !this.session) throw ended();
			args = { ...args, token: this.session.token };
		}
		// chọn tay (A-68): RPC quét trong lúc đang xử lý mã chọn tay mang cách nhập và lý do
		if (
			this.manualEntry &&
			typeof PICK_SCAN_METHODS !== "undefined" &&
			PICK_SCAN_METHODS.includes(method)
		)
			args = { ...args, entry_mode: "Manual", manual_reason: this.manualEntry.reason };
		const controller = new AbortController();
		controller.stationMethod = method;
		this.controllers.add(controller);
		const timer = setTimeout(() => controller.abort(), RPC_TIMEOUT_MS);
		const headers = {
			Accept: "application/json",
			"Content-Type": "application/json",
			"X-Frappe-CSRF-Token": frappe.csrf_token,
		};
		if (this.station) headers["X-TC-Station"] = this.station;
		if (idempotencyKey) headers["X-Idempotency-Key"] = idempotencyKey;
		try {
			const response = await fetch(`/api/method/${method}`, {
				method: "POST",
				headers,
				body: JSON.stringify(args),
				credentials: "same-origin",
				signal: controller.signal,
			});
			const data = await response.json().catch(() => ({}));
			if (candidate && !this.isCurrentCandidate(candidate)) throw ended();
			if (
				sessionCall &&
				(!this.ownsPage() ||
					version !== this.sessionVersion ||
					activeToken !== (this.session && this.session.token))
			)
				throw ended();
			const block = data.message && data.message.error;
			if (
				sessionCall &&
				(response.status === 401 ||
					(block && String(block.code || "").startsWith("SESSION_")))
			) {
				this.clearSession(
					block || {
						title: __("Station session is invalid"),
						reason: __("The session has ended or the token is invalid."),
						action: __("Scan your employee card again."),
					}
				);
				throw ended();
			}
			if (!response.ok) {
				// Từ chối nghiệp vụ (404/409/422) vẫn mang body {ok: false, error}: trả để màn hình hiện alert,
				// không coi là lỗi máy chủ (lỗi khác như 403, 5xx, khóa idempotent sai giữ nguyên đường ném lỗi)
				const rejected = response.status >= 400 && response.status < 500;
				if (rejected && data.message && data.message.ok === false) return data.message;
				const error = new Error(`HTTP ${response.status}`);
				error.status = response.status;
				throw error;
			}
			this.showWarnings(data.message, idempotencyKey);
			return data.message;
		} catch (error) {
			if (error.name === "AbortError" || error instanceof TypeError) error.offline = true;
			throw error;
		} finally {
			clearTimeout(timer);
			this.controllers.delete(controller);
		}
	}

	// RPC chỉ đọc của khối dữ liệu mở cùng trạm (#1825): tự thử lại 1 lần trước khi báo lỗi cho người dùng.
	// Từ chối nghiệp vụ cũng thử lại vì phiên vừa mở có thể chưa ổn định; hết phiên thì dừng ngay.
	async rpcRead(method, args) {
		const version = this.sessionVersion;
		let first = true;
		for (;;) {
			let result;
			let failure = null;
			try {
				result = await this.rpc(method, args);
				if (!result || result.ok !== false) return result;
			} catch (error) {
				if (error.sessionEnded) throw error;
				failure = error;
			}
			if (!first || version !== this.sessionVersion || this.isOffline()) {
				if (failure) throw failure;
				return result;
			}
			first = false;
			await new Promise((resolve) => setTimeout(resolve, RPC_READ_RETRY_MS));
			if (version !== this.sessionVersion)
				throw Object.assign(new Error("Station session ended"), { sessionEnded: true });
		}
	}

	// câu nêu nguyên nhân cho khối dữ liệu không tải được: mất mạng, hết phiên, lỗi máy chủ, hoặc lý do từ chối
	failureCause(error, result) {
		if (result && result.error && result.error.reason) return result.error.reason;
		if (error && error.offline)
			return __("Cause: no connection to the server, or the server answered too slowly.");
		if (error && error.status === 401) return __("Cause: the station session has ended.");
		return __("Cause: server error ({0}).", [(error && error.status) || "?"]);
	}

	async handshake() {
		if (!this.ownsPage()) return;
		const generation = this.authGeneration;
		if (!this.station) {
			return this.renderError({
				title: __("Station not configured"),
				reason: __("The kiosk address has no station code (?station=TR-...)."),
				action: __("Check the kiosk address or call R10."),
			});
		}
		if (this.isOffline()) return this.setOffline(true);
		try {
			const info = await this.rpc("tracecore.v1.ping", { station: this.station });
			if (!this.ownsPage()) return;
			if (this.isOffline()) return this.setOffline(true);
			if (info.station_error) return this.renderError(info.station_error);
			this.applyStation(info.station);
			if (generation !== this.authGeneration) return;
			if (!this.session) {
				const token = this.storedToken();
				if (token && !this.authBusy) await this.restoreSession(token);
				else if (!this.authBusy && (this.notice || !(await this.adoptSession())))
					this.renderLogin(this.notice);
			} else {
				const session = this.session;
				await this.heartbeat();
				if (this.ownsPage() && this.session === session) this.renderEmpty();
			}
		} catch (error) {
			if (generation === this.authGeneration) this.handleFailure(error);
		} finally {
			this.root.dataset.readyMs = String(Math.round(performance.now()));
		}
	}

	applyStation(station) {
		this.stationInfo = station;
		document.title = tcStationTitle(station);
		// màn nghiệp vụ theo chức năng của trạm (A-64); trạm không có màn dùng tra cứu Set ID chung
		window.tcGateLabels = station.gate_labels || {};
		if (this.session && !this.screen) this.openScreen((station.screens || [])[0]);
		this.renderScreenTabs();
		this.zonebar.className = `tc-zonebar tc-zone-${station.zone_color || "web"}`;
		this.root.querySelector(".tc-station-name").textContent = station.label;
		// context "Zone Station": khu khoa là "Khoa", không lấy bản dịch chung "Department" của Frappe ("Cục")
		this.root.querySelector(".tc-zone-label").textContent = __(
			ZONE_LABEL[station.zone_type] || station.zone_type || "Station",
			null,
			"Zone Station"
		);
		this.root.querySelector(".tc-station-code").textContent = station.name;
	}

	// Mỗi màn giữ một instance: đổi tab không mất giỏ đang nạp dở (A-64).
	openScreen(tab) {
		if (!tab) return;
		this.screens = this.screens || {};
		if (!this.screens[tab.key]) {
			const Screen = tcScreenClass(tab.key);
			if (!Screen) return;
			this.screens[tab.key] = new Screen(this);
		}
		this.screen = this.screens[tab.key];
		this.activeTab = tab.key;
	}

	switchScreen(key) {
		const tab = ((this.stationInfo && this.stationInfo.screens) || []).find(
			(row) => row.key === key
		);
		if (!tab || key === this.activeTab) return;
		if ((this.screen && this.screen.busy) || (this.pendingScans && this.pendingScans.length))
			return;
		if (this.picker) this.picker.reset();
		this.openScreen(tab);
		this.renderScreenTabs();
		this.result.innerHTML = "";
		this.screen.setOffline(this.isOffline());
		this.screen.show();
		this.input.focus();
	}

	renderScreenTabs() {
		if (!this.screenTabs) {
			this.screenTabs = document.createElement("div");
			this.screenTabs.className = "tc-chips tc-screen-tabs";
			this.screenTabs.setAttribute("role", "group");
			this.screenTabs.setAttribute("aria-label", __("Station screens"));
			this.result.before(this.screenTabs);
		}
		const tabs = (this.stationInfo && this.stationInfo.screens) || [];
		const visible = this.session && tabs.length > 1;
		this.screenTabs.hidden = !visible;
		this.screenTabs.innerHTML = visible
			? tabs
					.map(
						(tab) =>
							`<button type="button" class="tc-chip" data-action="tc-screen" data-screen="${esc(
								tab.key
							)}" aria-pressed="${
								tab.key === this.activeTab ? "true" : "false"
							}">${esc(tab.label)}</button>`
					)
					.join("")
			: "";
	}

	// quét lần lượt các mã giữ lại khi màn của bước hết chờ máy chủ; đổi phiên hoặc chờ quá lâu thì bỏ hàng đợi
	drainScans() {
		if (this.scanTimer) return;
		const version = this.sessionVersion;
		const started = Date.now();
		const tick = () => {
			this.scanTimer = null;
			if (version !== this.sessionVersion || !this.screen) {
				this.pendingScans = [];
				return;
			}
			if (this.screen.busy) {
				if (Date.now() - started > 2 * RPC_TIMEOUT_MS) this.pendingScans = [];
				else this.scanTimer = setTimeout(tick, 100);
				return;
			}
			const next = this.pendingScans.shift();
			if (!next) return;
			Promise.resolve(this.screen.scan(next)).finally(() => {
				if (this.pendingScans.length) this.drainScans();
			});
		};
		this.scanTimer = setTimeout(tick, 100);
	}

	// khoa đang giao của phiếu T1 đang mở: danh sách chọn tay ưu tiên bộ của khoa đó
	pickDepartment() {
		const receipt = this.screen && this.screen.receipt;
		return (receipt && receipt.department) || null;
	}

	busyForPick() {
		return Boolean(this.screen && this.screen.busy) || this.pendingScans.length > 0;
	}

	// chờ màn xử lý xong mã vừa chọn (kể cả mã xếp hàng nội bộ) để RPC sau còn mang cách nhập chọn tay
	async waitIdle() {
		const started = Date.now();
		while (Date.now() - started < 2 * RPC_TIMEOUT_MS && this.busyForPick())
			await new Promise((resolve) => setTimeout(resolve, 100));
	}

	async scan(raw, retry = false) {
		if (!this.session) return this.focus();
		this.authResult.innerHTML = "";
		if (this.screen) {
			// màn của bước đang chờ máy chủ thì bỏ qua mã quét; T1, T3, T7 tự xếp hàng, các màn khác xếp ở đây (mã mới
			// cũng xếp sau các mã còn chờ để giữ đúng thứ tự quét)
			const ownQueue = ["queue", "scanQueue", "queuedScan"].some(
				(key) => key in this.screen
			);
			if ((this.screen.busy || this.pendingScans.length) && !ownQueue) {
				const text = (raw || "").trim();
				this.input.value = "";
				if (text) this.pendingScans.push(text);
				return this.drainScans();
			}
			return this.screen.scan(raw);
		}
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.focus();
		if (!retry || !this.pending || this.pending.raw !== raw)
			this.pending = { raw, key: uuid4(), ts: clientTs() };
		this.lastRaw = raw;
		if (this.isOffline()) return this.setOffline(true);

		this.renderLoading();
		const started = performance.now();
		try {
			const result = await this.rpc(
				"tracecore.v1.set_unit.get",
				{ set_id: raw, client_ts: this.pending.ts },
				this.pending.key
			);
			this.pending = null;
			this.result.dataset.ms = String(Math.round(performance.now() - started));
			if (result.ok) {
				this.lastRaw = null;
				this.renderResult(result.set_unit);
			} else {
				this.renderError(result.error);
			}
		} catch (error) {
			this.handleFailure(error);
		}
		this.focus();
	}

	handleFailure(error) {
		if (!this.ownsPage()) return;
		if (error.sessionEnded) return;
		if (error.offline) return this.setOffline(true);
		// 4xx là câu trả lời dứt khoát của server: lần quét sau phải dùng key mới
		if (error.status >= 400 && error.status < 500) this.pending = null;
		if (error.status === 403) {
			return this.renderError({
				title: __("Not permitted"),
				reason: __("This account cannot read set records."),
				action: __("Log in with the station account or call R10."),
			});
		}
		this.renderError({
			title: __("Server error"),
			reason: __("The server could not process the request ({0}).", [error.status || "?"]),
			action: __("Retry, or call R02 if it happens again."),
		});
	}

	// ---- 4 trạng thái + kết quả ----
	setState(state, html) {
		this.result.dataset.state = state;
		this.result.innerHTML = html;
		this.form.classList.toggle("is-error", state === "error");
	}

	renderLoading() {
		this.setState(
			"loading",
			`<div class="tc-skeleton" aria-busy="true"><span></span><span></span><span></span></div>
			<span class="tc-sr-only">${esc(__("Loading..."))}</span>`
		);
	}

	renderEmpty() {
		if (!this.session) return this.renderLogin();
		if (this.screen) return this.screen.show();
		this.setState(
			"empty",
			`<p class="tc-empty">${esc(__("Scan the Set ID on the set tag."))}</p>`
		);
	}

	renderError(error) {
		if (!this.session) return this.renderLogin(error);
		this.setState(
			"error",
			`<div class="tc-alert tc-alert-error" role="alert">
				<p class="tc-alert-title"><span aria-hidden="true">&#10005;</span> ${esc(tcErrorTitle(error))}</p>
				<p class="tc-alert-reason">${esc(error.reason)}</p>
				<p class="tc-alert-action">${esc(error.action)}</p>
				${tcGuideButton(error)}
				${
					error.code
						? this.businessButtons(error)
						: `<div class="tc-actions">
					<button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
						__("Retry")
					)}</button>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="offline">${esc(
						__("Switch to offline")
					)}</button>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
						__("Call R02")
					)}</button>
				</div>`
				}
			</div>`
		);
	}

	renderOffline() {
		this.setState(
			"offline",
			`<div class="tc-alert tc-alert-info" role="status">
				<p class="tc-alert-title">${esc(__("Station offline"))}</p>
				<p>${esc(__("Set lookup needs the server. Scanning resumes when the connection returns."))}</p>
				<div class="tc-actions">
					<button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
						__("Retry")
					)}</button>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
						__("Call R02")
					)}</button>
				</div>
			</div>`
		);
	}

	renderResult(unit) {
		const variant = STATUS_BADGE[unit.status] || "";
		const percent = unit.max_cycles
			? Math.round((100 * unit.cycles_used) / unit.max_cycles)
			: 0;
		this.setState(
			"result",
			`<div class="tc-res">
				<div class="tc-res-head">
					<b class="tc-code">${esc(unit.set_id)}</b>
					<span class="tc-badge${variant ? " tc-badge-" + variant : ""}">${esc(
				__(unit.status, null, "Set Unit")
			)}</span>
					${unit.is_loaner ? `<span class="tc-badge tc-badge-o">${esc(__("Loaner"))}</span>` : ""}
				</div>
				<dl class="tc-res-grid">
					<dt>${esc(__("Set Type"))}</dt>
					<dd>${esc(unit.set_type_name)} <span class="tc-tag">${esc(unit.set_type)}</span></dd>
					<dt>${esc(__("Sterilization Method"))}</dt>
					<dd>${esc(__(unit.method, null, "Instrument Set Type"))}</dd>
					<dt>${esc(__("Cycles"))}</dt>
					<dd>${esc(__("{0}/{1} cycles ({2}%)", [unit.cycles_used, unit.max_cycles, percent]))}</dd>
					<dt>${esc(__("Current Station"))}</dt>
					<dd class="tc-mono">${esc(unit.current_station || "-")}</dd>
				</dl>
			</div>`
		);
	}

	// ---- PWA shell ----
	addManifestLink() {
		if (!document.querySelector('link[rel="manifest"]')) {
			document.head.insertAdjacentHTML(
				"beforeend",
				'<link rel="manifest" href="/manifest.json">'
			);
		}
	}

	registerServiceWorker() {
		if ("serviceWorker" in navigator && window.isSecureContext) {
			navigator.serviceWorker.register("/sw.js", { scope: "/app/station" }).catch(() => {});
		}
	}
}

frappe.pages["station"].on_page_load = function (wrapper) {
	const previous = frappe.tc_station;
	const barrier = previous ? previous.dispose() : Promise.resolve();
	frappe.tc_station = new TraceCoreStation(wrapper, barrier);
	// Frappe v15 không gọi on_page_hide của Page, chỉ phát sự kiện "hide" trên wrapper
	$(wrapper).on("hide", () => frappe.pages["station"].on_page_hide());
};

frappe.pages["station"].on_page_show = function () {
	if (frappe.tc_station) frappe.tc_station.show();
	// router của Frappe đặt lại tiêu đề khi quay về trang
	if (frappe.tc_station && frappe.tc_station.stationInfo)
		document.title = tcStationTitle(frappe.tc_station.stationInfo);
};

frappe.pages["station"].on_page_hide = function () {
	if (frappe.tc_station) frappe.tc_station.hide();
};
