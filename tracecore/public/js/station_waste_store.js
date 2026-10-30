/* global uuid4, clientTs, esc, TcWeighLine, WasteCollect, WasteHandoverScreen */
// Màn kho lưu giữ tạm chất thải (SCR-39, FEAT-048, UC-35, A-61) và thanh tab của trạm chất thải (bước WST).
// Frappe nối file này sau station_waste.js (hook page_js) nên dùng chung uuid4/clientTs/esc/WasteCollect.
// Ô quét luôn ở đầu: quét vị trí KE- rồi quét từng túi CT-; quét phiếu TG- để nhập cả phiếu vào vị trí mặc định.
// Lỗi chặn = alert-error inline (kết quả → lý do → hành động). Không offline: mất mạng thì báo và không ghi (A-60 W2).

const WSS_STOCK = "tracecore.v1.waste.stock";
const WSS_LOCATION = "tracecore.v1.waste.check_location";
const WSS_STORE = "tracecore.v1.waste.store";
const WSS_TEMPERATURE = "tracecore.v1.waste.record_temperature";

// Thanh chuyển giữa các màn của trạm chất thải, nằm đầu mỗi màn (xem WasteStation)
function wasteTabs(active) {
	const tab = (mode, label) =>
		`<button type="button" class="tc-btn ${
			active === mode ? "tc-btn-primary" : "tc-btn-secondary"
		}" data-action="waste-mode" data-mode="${mode}" aria-pressed="${active === mode}">${esc(
			label
		)}</button>`;
	return `<div class="tc-linen-tabs" role="group" aria-label="${esc(__("Waste station"))}">
		${tab("collect", __("Collection"))}${tab("store", __("Waste store"))}${tab(
		"handover",
		__("Handover")
	)}
	</div>`;
}

class WasteStore {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.offline = false;
		this.busy = null;
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.data = null;
		this.location = null;
		this.notice = null;
		this.temperatures = {};
		station.listen(this.result, "input", (event) => this.onInput(event));
	}

	get dialogOpen() {
		return false;
	}

	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.data = null;
		this.location = null;
		this.notice = null;
		this.temperatures = {};
	}

	updatePlaceholder() {
		const text = this.location
			? __("Scan a waste bag, or another location...")
			: __("Scan a KE- location or a TG- collection...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	onInput(event) {
		const target = event.target;
		if (target && target.dataset && target.dataset.field === "temperature")
			this.temperatures[target.dataset.room] = target.value;
	}

	// ---- quét: vị trí KE-, túi CT-, phiếu TG- ----
	async scan(raw) {
		const code = (raw || "").trim();
		this.input.value = "";
		if (!code) return this.station.focus();
		this.notice = null;
		const upper = code.toUpperCase();
		if (upper.startsWith("KE-")) return this.scanLocation(upper);
		if (upper.startsWith("TG-")) return this.storeCollection(upper);
		if (upper.startsWith("CT-")) return this.storeBag(upper);
		this.notice = {
			variant: "error",
			title: __("Code not recognised"),
			reason: __("{0} is not a location, a waste bag or a collection.", [code]),
			action: __("Scan a KE-, CT- or TG- code."),
		};
		return this.show();
	}

	scanLocation(code) {
		return this.request(
			WSS_LOCATION,
			{ station: this.station.station, location: code },
			(res) => {
				this.location = res.location;
				this.show();
			}
		);
	}

	storeBag(code) {
		if (!this.location) {
			this.notice = {
				variant: "error",
				title: __("Scan the location first"),
				reason: __("Bag {0} has no location yet.", [code]),
				action: __("Scan the KE- code of the location, then scan the bag again."),
			};
			return this.show();
		}
		return this.request(
			WSS_STORE,
			{ station: this.station.station, location: this.location.name, container: code },
			(res) => {
				this.notice = {
					variant: "ok",
					title: __("Bag {0} stored", [res.container.name]),
					reason: __("Location {0}.", [res.container.location]),
				};
				this.data = null;
				this.show();
			}
		);
	}

	storeCollection(code) {
		return this.request(
			WSS_STORE,
			{ station: this.station.station, collection: code },
			(res) => {
				this.notice = {
					variant: "ok",
					title: __("{0} bags stored", [res.stored]),
					reason: __("Location {0}.", [res.locations.join(", ")]),
				};
				this.data = null;
				this.show();
			}
		);
	}

	recordTemperature(room) {
		const temperature = (this.temperatures[room] || "").trim();
		if (!temperature) {
			this.notice = {
				variant: "error",
				title: __("Temperature is not valid"),
				reason: __("The temperature must be a number."),
				action: __("Type the temperature read on the thermometer."),
			};
			return this.show();
		}
		this.notice = null;
		return this.request(
			WSS_TEMPERATURE,
			{ station: this.station.station, location: room, temperature },
			() => {
				delete this.temperatures[room];
				this.notice = { variant: "ok", title: __("Temperature recorded") };
				this.data = null;
				this.show();
			}
		);
	}

	// ---- gọi RPC ----
	async request(method, args, onOk) {
		if (this.busy || !this.station.session) return;
		const version = this.station.sessionVersion;
		const sig = method + JSON.stringify(args);
		if (!this.pending || this.pending.sig !== sig) {
			this.pending = { sig, method, args, onOk, key: uuid4(), ts: clientTs() };
		}
		const pending = this.pending;
		this.busy = method;
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
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		if (!failure) {
			this.pending = null;
			this.result.dataset.ms = String(Math.round(performance.now() - started));
		}
		this.busy = null;
		if (failure) this.failure(failure);
		else if (response && response.ok === false) {
			this.notice = { variant: "error", ...response.error };
			this.show();
		} else onOk(response);
		this.station.focus();
	}

	retry() {
		this.station.manualOffline = false;
		if (!navigator.onLine) return this.station.setOffline(true);
		this.station.setOffline(false);
		const pending = this.pending;
		if (pending) return this.request(pending.method, pending.args, pending.onOk);
		this.notice = null;
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
				reason: __("This account cannot use the waste store at this station."),
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

	loadStock() {
		this.request(WSS_STOCK, { station: this.station.station }, (res) => {
			this.data = res;
			this.show();
		});
	}

	onAction(action, button) {
		const handlers = {
			retry: () => this.retry(),
			"clear-location": () => {
				this.location = null;
				this.notice = null;
				this.show();
			},
			"record-temperature": () => this.recordTemperature(button.dataset.room),
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		if (this.offline) return this.station.setState("offline", this.offlineHtml());
		const failed = this.notice && this.notice.variant === "error";
		if (!this.data && !this.busy && !failed) {
			this.loadStock();
			return this.station.renderLoading();
		}
		const empty = this.data && !this.data.containers.length && !this.data.cold_rooms.length;
		const state = failed ? "error" : empty ? "empty" : "result";
		this.station.setState(
			state,
			`<div class="tc-linen tc-waste">
				${wasteTabs("store")}
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.locationHtml()}
				${this.data ? this.stockHtml() : ""}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(notice.title)}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
			${buttons}
		</div>`;
	}

	standardButtons() {
		return `<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-primary" data-action="retry">${esc(
				__("Retry")
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
				reason: __("The waste store needs a network connection."),
				action: __("Retry when the connection returns."),
			},
			this.standardButtons()
		);
	}

	noticeHtml() {
		let html = "";
		if (this.busy) {
			html += `<p class="tc-loading" role="status" aria-busy="true">${esc(
				__("Loading...")
			)}</p>`;
		}
		if (this.notice)
			html += this.alertHtml(
				this.notice,
				this.notice.technical ? this.standardButtons() : ""
			);
		if (this.data && !this.data.containers.length && !this.data.cold_rooms.length) {
			html += this.alertHtml({
				variant: "info",
				title: __("The waste store is empty"),
				reason: __("No collected bag is waiting or stored."),
				action: __("Record a waste collection first."),
			});
		}
		return html;
	}

	locationHtml() {
		if (!this.location) {
			return `<section class="tc-t6-block">
				<p class="tc-t6-hint">${esc(__("Scan the location, then scan each bag."))}</p>
			</section>`;
		}
		return `<section class="tc-t6-block">
			<div class="tc-linen-head">
				<p><strong>${esc(__("Storage Location"))}:</strong> <span class="tc-mono">${esc(
			this.location.name
		)}</span> ${esc(this.location.location_name)}${
			this.location.is_cold ? ` (${esc(__("Cold Room"))})` : ""
		}</p>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="clear-location">${esc(
					__("Scan another location")
				)}</button>
			</div>
		</section>`;
	}

	remaining(minutes) {
		const late = minutes < 0;
		const total = Math.abs(minutes);
		const text = __("{0} h {1} min", [Math.floor(total / 60), total % 60]);
		return late ? __("Late by {0}", [text]) : text;
	}

	stateLabel(state) {
		if (state === "Overdue")
			return `<span class="tc-badge-danger">&#10005; ${esc(__("Past the limit"))}</span>`;
		if (state === "Due Soon")
			return `<span class="tc-badge-warn">! ${esc(__("Close to the limit"))}</span>`;
		return `<span>&#10003; ${esc(__("Within the limit"))}</span>`;
	}

	stockHtml() {
		return `${this.coldHtml()}${this.summaryHtml()}${this.containersHtml()}`;
	}

	coldHtml() {
		if (!this.data.cold_rooms.length) return "";
		const rows = this.data.cold_rooms
			.map((room) => {
				const id = esc(room.location);
				return `<div class="tc-linen-line">
					<p><strong>${esc(room.location_name)}</strong> <span class="tc-mono">${id}</span></p>
					<p>${esc(__("Last temperature"))}: ${
					room.temperature == null ? "-" : `${esc(room.temperature)} °C`
				}${
					room.in_breach
						? ` <span class="tc-badge-danger">&#10005; ${esc(
								__("Above the limit")
						  )}</span>`
						: ""
				}</p>
					<div class="tc-field">
						<label for="tc-wss-temp-${id}">${esc(__("Temperature (°C)"))}</label>
						<input id="tc-wss-temp-${id}" type="text" inputmode="decimal" autocomplete="off"
							data-field="temperature" data-room="${id}" value="${esc(this.temperatures[room.location] || "")}">
					</div>
					<div class="tc-actions">
						<button type="button" class="tc-btn tc-btn-secondary" data-action="record-temperature" data-room="${id}">${esc(
					__("Record temperature")
				)}</button>
					</div>
				</div>`;
			})
			.join("");
		return `<section class="tc-t6-block" aria-label="${esc(
			__("Cold rooms")
		)}">${rows}</section>`;
	}

	summaryHtml() {
		if (!this.data.summary.length) return "";
		const rows = this.data.summary
			.map(
				(row) => `<tr>
				<td>${esc(row.waste_type)}</td>
				<td>${
					row.location
						? `<span class="tc-mono">${esc(row.location)}</span>`
						: esc(__("Not stored yet"))
				}</td>
				<td>${esc(row.bags)}</td>
				<td>${esc(TcWeighLine.format(row.weight_kg))}</td>
				<td>${esc(this.remaining(row.remaining_minutes))}</td>
				<td>${this.stateLabel(row.state)}</td>
			</tr>`
			)
			.join("");
		return `<table class="tc-t6-table">
			<thead><tr>
				<th scope="col">${esc(__("Waste Type"))}</th>
				<th scope="col">${esc(__("Storage Location"))}</th>
				<th scope="col">${esc(__("Bags or Bins"))}</th>
				<th scope="col">${esc(__("Weight (kg)"))}</th>
				<th scope="col">${esc(__("Time Left"))}</th>
				<th scope="col">${esc(__("Status"))}</th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>`;
	}

	containersHtml() {
		const urgent = this.data.containers.filter((row) => row.state !== "OK");
		if (!urgent.length) return "";
		const rows = urgent
			.map(
				(row) => `<tr>
				<td class="tc-mono">${esc(row.name)}</td>
				<td>${esc(row.waste_type)}</td>
				<td>${esc(this.remaining(row.remaining_minutes))}</td>
				<td>${this.stateLabel(row.state)}</td>
			</tr>`
			)
			.join("");
		return `<table class="tc-t6-table" aria-label="${esc(__("Bags close to the limit"))}">
			<thead><tr>
				<th scope="col">${esc(__("Container Code"))}</th>
				<th scope="col">${esc(__("Waste Type"))}</th>
				<th scope="col">${esc(__("Time Left"))}</th>
				<th scope="col">${esc(__("Status"))}</th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>`;
	}
}

// Trạm chất thải: thu gom và kho chuyển bằng tab, cùng khuôn với LinenStation
class WasteStation {
	constructor(station) {
		this.station = station;
		this.collect = new WasteCollect(station);
		this.store = new WasteStore(station);
		this.handover = new WasteHandoverScreen(station); // FEAT-049, SCR-40
		this.active = this.collect;
	}

	get dialogOpen() {
		return this.active.dialogOpen;
	}

	get busy() {
		return this.active.busy;
	}

	clearSession() {
		this.collect.clearSession();
		this.store.clearSession();
		this.handover.clearSession();
		this.active = this.collect;
	}

	scan(raw) {
		return this.active.scan(raw);
	}

	setOffline(offline) {
		this.collect.offline = offline;
		this.store.offline = offline;
		this.handover.offline = offline;
		return this.active.show();
	}

	show() {
		return this.active.show();
	}

	onAction(action, button) {
		if (action === "waste-mode") {
			if (this.active.busy) return true;
			this.active = this[button.dataset.mode] || this.collect; // collect | store | handover
			this.active.notice = null;
			if (this.active === this.store) this.store.data = null;
			this.active.show();
			return true;
		}
		return this.active.onAction(action, button);
	}
}
