// Page station — kiosk trạm quét (surface STN), khung FEAT-001.
// Ô quét luôn focus; 4 trạng thái loading / empty / error / offline (FR-M9-14);
// gọi RPC tracecore.v1.* với X-Idempotency-Key + client_ts (ADR-003).

const RPC_TIMEOUT_MS = 8000;
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
	"End of Life": "r",
	Disposed: "x",
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
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.station = new URLSearchParams(window.location.search).get("station");
		this.stationInfo = null;
		this.pending = null; // lần quét chưa có phản hồi server: {raw, key}
		this.lastRaw = null;
		this.manualOffline = false;
		this.visible = false;

		$(wrapper).html(frappe.render_template("station", {}));
		this.root = wrapper.querySelector(".tc-station");
		this.zonebar = this.root.querySelector(".tc-zonebar");
		this.banner = this.root.querySelector(".tc-offline-banner");
		this.form = this.root.querySelector(".tc-scan");
		this.input = this.root.querySelector(".tc-scan-input");
		this.result = this.root.querySelector(".tc-result");
		this.root.dataset.shellMs = String(Math.round(performance.now()));

		this.bind();
		this.addManifestLink();
		this.registerServiceWorker();
		this.renderLoading();
		this.handshake();
	}

	// ---- vòng đời Page ----
	show() {
		this.visible = true;
		document.body.classList.add("tc-kiosk");
		this.focus();
	}

	hide() {
		this.visible = false;
		document.body.classList.remove("tc-kiosk");
	}

	focus() {
		if (this.visible && document.activeElement !== this.input) {
			this.input.focus({ preventScroll: true });
		}
	}

	bind() {
		this.form.addEventListener("submit", (event) => {
			event.preventDefault();
			this.scan(this.input.value);
		});
		this.root.addEventListener("click", (event) => {
			const button = event.target.closest("[data-action]");
			if (button) this.onAction(button.dataset.action);
			setTimeout(() => this.focus(), 0);
		});
		this.input.addEventListener("blur", () => setTimeout(() => this.focus(), 150));
		window.addEventListener("offline", () => this.setOffline(true));
		window.addEventListener("online", () => {
			if (!this.manualOffline) {
				this.setOffline(false);
				this.handshake();
			}
		});
	}

	onAction(action) {
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

	// ---- mạng ----
	isOffline() {
		return this.manualOffline || !navigator.onLine;
	}

	setOffline(offline) {
		this.banner.hidden = !offline;
		this.root.dataset.offline = offline ? "1" : "0";
		if (offline) this.renderOffline();
	}

	async rpc(method, args, idempotencyKey) {
		const controller = new AbortController();
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
			if (!response.ok) {
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
		}
	}

	async handshake() {
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
			if (info.station_error) return this.renderError(info.station_error);
			this.applyStation(info.station);
			this.renderEmpty();
		} catch (error) {
			this.handleFailure(error);
		} finally {
			this.root.dataset.readyMs = String(Math.round(performance.now()));
		}
	}

	applyStation(station) {
		this.stationInfo = station;
		this.zonebar.className = `tc-zonebar tc-zone-${ZONE_CLASS[station.zone_type] || "web"}`;
		this.root.querySelector(".tc-station-name").textContent = station.label;
		this.root.querySelector(".tc-zone-label").textContent = __(
			ZONE_LABEL[station.zone_type] || "Station"
		);
		this.root.querySelector(".tc-station-code").textContent = station.name;
	}

	async scan(raw, retry = false) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.focus();
		if (!retry || !this.pending || this.pending.raw !== raw)
			this.pending = { raw, key: uuid4() };
		this.lastRaw = raw;
		if (this.isOffline()) return this.setOffline(true);

		this.renderLoading();
		const started = performance.now();
		try {
			const result = await this.rpc(
				"tracecore.v1.set_unit.get",
				{ set_id: raw, client_ts: clientTs() },
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
		if (error.offline) return this.setOffline(true);
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
		this.setState(
			"empty",
			`<p class="tc-empty">${esc(__("Scan the Set ID on the set tag."))}</p>`
		);
	}

	renderError(error) {
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
				<p class="tc-alert-title">${esc(__("Offline"))}</p>
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
					<span class="tc-badge${variant ? " tc-badge-" + variant : ""}">${esc(__(unit.status))}</span>
					${unit.is_loaner ? `<span class="tc-badge tc-badge-o">${esc(__("Loaner"))}</span>` : ""}
				</div>
				<dl class="tc-res-grid">
					<dt>${esc(__("Set Type"))}</dt>
					<dd>${esc(unit.set_type_name)} <span class="tc-tag">${esc(unit.set_type)}</span></dd>
					<dt>${esc(__("Sterilization Method"))}</dt>
					<dd>${esc(__(unit.method))}</dd>
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
	frappe.tc_station = new TraceCoreStation(wrapper);
};

frappe.pages["station"].on_page_show = function () {
	if (frappe.tc_station) frappe.tc_station.show();
};

frappe.pages["station"].on_page_hide = function () {
	if (frappe.tc_station) frappe.tc_station.hide();
};
