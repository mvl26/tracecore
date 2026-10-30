// Page station — kiosk trạm quét (surface STN), khung FEAT-001.
// Ô quét luôn focus; 4 trạng thái loading / empty / error / offline (FR-M9-14);
// gọi RPC tracecore.v1.* với X-Idempotency-Key + client_ts (ADR-003).
// Trạm bước T4 giao cho T4Packing (public/js/station_t4.js), bước T6 giao cho T6Storage (public/js/station_t6.js),
// bước T1 giao cho T1Receiving, T2 cho T2Wash, T3 cho T3Assembly, T5 cho T5Load, T7 cho T7Issue (public/js/station_t*.js),
// bước LIN (trạm đồ vải, FEAT-033, FEAT-034) cho LinenStation: LinenCollect (station_linen.js) và LaundryBatch (station_laundry.js);
// các file này nối sau file này qua hook page_js.
// Màn riêng của bước nằm ở this.screen.
/* global T4Packing, T6Storage, T2Wash, T1Receiving, T3Assembly, T5Load, T7Issue, T8Usage, LinenCollect, LinenStation, TcOutbox, tcSync, TC_SNAPSHOT_MS */

const RPC_TIMEOUT_MS = 8000;
const STATION_IDLE_MS = 10 * 60 * 1000;
const STATION_HEARTBEAT_MS = 30000;
const TC_NOTIFY_MS = 60000; // chuông thông báo hỏi lại mỗi 60 giây (FR-M9-10, SCR-42)
const ZONE_CLASS = {
	Dirty: "dirty",
	Clean: "clean",
	Sterile: "sterile",
	Department: "dept",
	Waste: "waste",
};
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
		this.zonebar = this.root.querySelector(".tc-zonebar");
		this.banner = this.root.querySelector(".tc-offline-banner");
		this.form = this.root.querySelector(".tc-work .tc-scan");
		this.input = this.root.querySelector("#tc-scan-input");
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

		this.bind();
		this.addManifestLink();
		this.registerServiceWorker();
		this.renderLogin();
		this.initialHandshake = Promise.resolve();
		if (typeof tcSync !== "undefined") {
			this.unsubscribeSync = tcSync.onChange((state) => this.renderSync(state));
			tcSync.refreshCount();
			tcSync.replay();
		}
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
		if ((this.screen && this.screen.dialogOpen) || this.pinChange) return;
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
			this.listen(
				this.root,
				name,
				() => {
					if (!this.session) return;
					// Check the old deadline before counting the first interaction after sleep.
					if (Date.now() - this.lastActivity >= STATION_IDLE_MS) this.checkSession();
					else this.lastActivity = Date.now();
				},
				true
			);
		}
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
		if (action === "logout" || action === "rescan-card") return this.endSession();
		if (action === "toggle-notifications") return this.toggleNotifications();
		if (action === "read-notification") return this.readNotification(button.dataset.name);
		if (!this.session) {
			if (action === "retry") {
				this.manualOffline = false;
				return this.handshake();
			}
			return;
		}
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

	renderLogin(error) {
		this.authForm.hidden = false;
		this.work.hidden = true;
		this.sessionBar.hidden = true;
		this.authResult.innerHTML = error
			? `<div class="tc-card tc-alert tc-alert-error" role="alert">
				<p class="tc-alert-title">${esc(error.title)}</p>
				<p class="tc-alert-reason">${esc(error.reason)}</p>
				<p class="tc-alert-action">${esc(error.action)}</p></div>`
			: "";
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
		this.pending = null;
		this.lastRaw = null;
		this.input.value = "";
		this.cardInput.value = "";
		if (this.screen && this.screen.clearSession) this.screen.clearSession();
		this.result.innerHTML = "";
		this.result.dataset.state = "locked";
		this.form.classList.remove("is-error");
		this.closePinChange();
		for (const selector of [
			".tc-session-person",
			".tc-session-station",
			".tc-session-expiry",
			".tc-session-roles",
		])
			this.root.querySelector(selector).textContent = "";
		this.resetNotifications();
		this.renderLogin(error);
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
		banner.textContent = summary.urgent ? __("Urgent: {0}", [summary.urgent.subject]) : "";
		if (!this.root.querySelector(".tc-notify-panel").hidden) this.loadNotificationPanel();
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
		this.lastActivity = Date.now();
		this.heartbeatActivity = this.lastActivity;
		this.heartbeatAttempt = Date.now();
		this.authForm.hidden = true;
		this.authResult.innerHTML = "";
		this.sessionBar.hidden = false;
		this.work.hidden = false;
		this.root.querySelector(".tc-session-person").textContent =
			session.employee_name || session.employee;
		this.root.querySelector(".tc-session-station").textContent = session.station;
		this.root.querySelector(".tc-session-roles").textContent = __("Roles: {0}", [
			(session.roles || []).map((role) => __(role)).join(", "),
		]);
		this.root.querySelector(".tc-session-expiry").textContent = __("Session expires: {0}", [
			this.formatExpiry(session.expires_at),
		]);
		if (this.stationInfo) this.applyStation(this.stationInfo);
		this.renderEmpty();
		this.focus(true);
		if (session.pin_change_required) this.openPinChange();
		this.loadOfflineData();
		this.refreshNotifications();
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
			["T1", "T4", "T8"].includes(this.stationInfo && this.stationInfo.step)
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

	async restoreSession(token) {
		const candidate = { token, attempt: ++this.authGeneration };
		this.restoreCandidate = candidate;
		try {
			const result = await this.rpc(
				"tracecore.v1.station.heartbeat",
				{
					token,
					client_ts: clientTs(),
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
			method.startsWith("tracecore.v1.sync.") ||
			method.startsWith("tracecore.v1.code_range.") ||
			method === "tracecore.v1.printer.set_roll" ||
			method === "tracecore.v1.account.change_pin";
		const version = this.sessionVersion;
		const sessionCall =
			!candidate &&
			(protectedCall ||
				method === "tracecore.v1.station.heartbeat" ||
				method === "tracecore.v1.set_unit.get");
		const activeToken = this.session && this.session.token;
		const ended = () =>
			Object.assign(new Error("Station session ended"), { sessionEnded: true });
		if (protectedCall) {
			if (!this.ownsPage() || !this.session) throw ended();
			args = { ...args, token: this.session.token };
		}
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
			return data.message;
		} catch (error) {
			if (error.name === "AbortError" || error instanceof TypeError) error.offline = true;
			throw error;
		} finally {
			clearTimeout(timer);
			this.controllers.delete(controller);
		}
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
				else if (!this.authBusy) this.renderLogin();
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
		// màn riêng của bước (this.screen): T1 tiếp nhận, T2 lô rửa, T3 kiểm đếm, T4 đóng gói, T6 kho vô khuẩn; bước khác
		// dùng tra cứu Set ID chung
		if (this.session && !this.screen) {
			if (station.step === "T4" && typeof T4Packing !== "undefined") {
				this.screen = this.t4 = new T4Packing(this);
			} else if (station.step === "T6" && typeof T6Storage !== "undefined") {
				this.screen = new T6Storage(this);
			} else if (station.step === "T2" && typeof T2Wash !== "undefined") {
				this.screen = new T2Wash(this);
			} else if (station.step === "T7" && typeof T7Issue !== "undefined") {
				this.screen = new T7Issue(this);
			} else if (station.step === "T8" && typeof T8Usage !== "undefined") {
				this.screen = new T8Usage(this);
			} else if (station.step === "T5" && typeof T5Load !== "undefined") {
				this.screen = new T5Load(this);
			} else if (station.step === "T3" && typeof T3Assembly !== "undefined") {
				this.screen = new T3Assembly(this);
			} else if (station.step === "T1" && typeof T1Receiving !== "undefined") {
				this.screen = new T1Receiving(this);
			} else if (station.step === "LIN" && typeof LinenCollect !== "undefined") {
				// trạm đồ vải: thu gom + lô giặt (FEAT-034) chuyển bằng tab; không có station_laundry.js thì chỉ thu gom
				this.screen =
					typeof LinenStation !== "undefined"
						? new LinenStation(this)
						: new LinenCollect(this);
			}
		}
		this.zonebar.className = `tc-zonebar tc-zone-${ZONE_CLASS[station.zone_type] || "web"}`;
		this.root.querySelector(".tc-station-name").textContent = station.label;
		// context "Zone Station": khu khoa là "Khoa", không lấy bản dịch chung "Department" của Frappe ("Cục")
		this.root.querySelector(".tc-zone-label").textContent = __(
			ZONE_LABEL[station.zone_type] || "Station",
			null,
			"Zone Station"
		);
		this.root.querySelector(".tc-station-code").textContent = station.name;
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

	async scan(raw, retry = false) {
		if (!this.session) return this.focus();
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
				<p class="tc-alert-title"><span aria-hidden="true">&#10005;</span> ${esc(error.title)}</p>
				<p class="tc-alert-reason">${esc(error.reason)}</p>
				<p class="tc-alert-action">${esc(error.action)}</p>
				<div class="tc-actions">
					<button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
						__("Retry")
					)}</button>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="offline">${esc(
						__("Switch to offline")
					)}</button>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="call-r02">${esc(
						__("Call R02")
					)}</button>
				</div>
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
};

frappe.pages["station"].on_page_show = function () {
	if (frappe.tc_station) frappe.tc_station.show();
};

frappe.pages["station"].on_page_hide = function () {
	if (frappe.tc_station) frappe.tc_station.hide();
};
