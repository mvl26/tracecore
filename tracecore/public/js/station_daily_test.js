/* global uuid4, clientTs, esc, T5Load, T2Wash */
// Màn SCR-23 test hằng ngày và khóa máy (FEAT-040, UC-23) trên Page station: chế độ "Test hằng ngày" của màn T5 và T2.
// Frappe nối file này sau station_t5.js và station_t2.js (hook page_js). T5Load/T2Wash đổi `station.screen` sang
// DailyTestScreen; nút "Quay lại" trả màn về màn nạp mẻ/lô. Quét QR máy hoặc chọn máy trong danh sách, chọn loại test,
// kết quả Đạt/Không đạt, nhập lô test và hạn lô. Test Không đạt khóa máy. R02 mở khóa tạm ≤ 24 giờ kèm lý do.
// Lỗi chặn = alert-error inline (kết quả → lý do → hành động). Ảnh bản in/biểu đồ chưa đính ở màn này (gap).

const DT_OVERVIEW = "tracecore.v1.daily_test.overview";
const DT_RECORD = "tracecore.v1.daily_test.record";
const DT_UNLOCK = "tracecore.v1.daily_test.unlock_temp";
const DT_MAX_HOURS = 24;

function dtTestLabel(type) {
	return (
		{
			bowie_dick: __("Bowie-Dick test"),
			leak: __("Leak test"),
			washer_cleaning: __("Washer cleaning test"),
		}[type] || type
	);
}

class DailyTestScreen {
	constructor(station, back) {
		this.station = station;
		this.back = back;
		this.result = station.result;
		this.input = station.input;
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.reset();
		this.result.addEventListener("input", (event) => this.onInput(event));
	}

	get dialogOpen() {
		return false;
	}

	reset() {
		this.list = null;
		this.selected = null; // tên máy đang chọn
		this.notice = null;
		this.form = { test_type: "", result: "", lot: "", lot_expiry: "", reason: "", hours: "" };
	}

	clearSession() {
		this.pending = null;
		this.busy = null;
		this.offline = false;
		this.reset();
		this.back.clearSession();
		this.station.screen = this.back;
	}

	// ---- quét và gọi RPC ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline()) return this.station.setOffline(true);
		const match = /TB-\d{4}/.exec(raw.toUpperCase());
		if (!match) {
			return this.blocked({
				title: __("Invalid code"),
				reason: __("Code {0} is not a machine code.", [raw]),
				action: __("Scan the QR code on the machine."),
			});
		}
		this.selected = match[0];
		this.notice = null;
		if (!this.list) return this.load();
		this.show();
	}

	load() {
		this.request(DT_OVERVIEW, { station: this.station.station }, (res) => {
			this.list = res.equipment;
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
		// phiên đã kết thúc hoặc đổi người trong lúc chờ: clearSession đã xóa màn, bỏ câu trả lời cũ
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		if (!failure) this.pending = null;
		this.busy = null;
		if (failure) this.failure(failure);
		else if (response && response.ok === false) this.blocked(response.error);
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
		this.load();
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
				reason: __("This account cannot record daily tests or unlock machines."),
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

	blocked(notice) {
		this.notice = { variant: "error", ...notice };
		this.show();
	}

	// ---- thao tác ----
	machine() {
		return (this.list || []).find((row) => row.name === this.selected) || null;
	}

	backToLoad() {
		if (this.busy) return;
		this.station.screen = this.back;
		this.back.notice = null;
		this.back.show();
		this.station.focus(true);
	}

	recordTest() {
		const form = this.form;
		if (!this.selected || !form.test_type || !form.result) {
			return this.blocked({
				title: __("Test is not complete"),
				reason: __("Choose the machine, the test and its result."),
				action: __("Choose the missing items, then record the test."),
			});
		}
		this.request(
			DT_RECORD,
			{
				equipment: this.selected,
				test_type: form.test_type,
				result: form.result,
				lot: form.lot,
				lot_expiry: form.lot_expiry,
				station: this.station.station,
			},
			(res) => {
				this.notice = {
					variant: res.locked ? "warn" : "ok",
					title: res.locked
						? __("Test failed: machine {0} is locked", [this.selected])
						: __("Test recorded for machine {0}", [this.selected]),
					reason: res.locked
						? __("A non-conformity is needed. Call R02.")
						: res.unlocked
						? __("The machine is open again for today.")
						: (res.warnings || []).includes("photo_missing")
						? __("The Bowie-Dick printout photo is missing.")
						: "",
					action: res.locked
						? __("Do not load this machine.")
						: __("Scan the next machine."),
				};
				this.form = { ...this.form, result: "", test_type: "" };
				this.load();
			}
		);
	}

	unlock() {
		const form = this.form;
		const hours = parseInt(form.hours, 10);
		if (!this.selected || !form.reason.trim() || !(hours >= 1 && hours <= DT_MAX_HOURS)) {
			return this.blocked({
				title: __("Unlock request is not valid"),
				reason: __(
					"Choose the machine, enter a reason and a duration from 1 to {0} hours.",
					[DT_MAX_HOURS]
				),
				action: __("Complete the request, then unlock."),
			});
		}
		this.request(
			DT_UNLOCK,
			{
				equipment: this.selected,
				reason: form.reason,
				hours,
				station: this.station.station,
			},
			() => {
				this.notice = {
					variant: "ok",
					title: __("Machine {0} is unlocked temporarily", [this.selected]),
					reason: __("The unlock ends after {0} hour(s).", [hours]),
					action: __("Record the daily test as soon as possible."),
				};
				this.form = { ...this.form, reason: "", hours: "" };
				this.load();
			}
		);
	}

	onAction(action, button) {
		const data = (button && button.dataset) || {};
		const handlers = {
			retry: () => this.retry(),
			"dt-back": () => this.backToLoad(),
			"dt-select": () => {
				this.selected = data.machine;
				this.notice = null;
				this.show();
			},
			"dt-type": () => {
				this.form.test_type = data.value;
				this.show();
			},
			"dt-result": () => {
				this.form.result = data.value;
				this.show();
			},
			"dt-record": () => this.recordTest(),
			"dt-unlock": () => this.unlock(),
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	onInput(event) {
		if (this.station.screen !== this) return;
		const field = event.target.dataset.dtField;
		if (field) this.form[field] = event.target.value;
	}

	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	show() {
		const text = __("Scan the QR code on the machine...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
		if (!this.list && !this.busy && !this.notice) return this.load();
		if (this.offline && !this.list)
			return this.station.setState("offline", this.offlineHtml());
		const state = this.notice && this.notice.variant === "error" ? "error" : "result";
		this.station.setState(
			state,
			`<div class="tc-t2 tc-t5 tc-dt">
				<div class="tc-chips" role="group" aria-label="${esc(__("Daily test"))}">
					<button type="button" class="tc-chip" data-action="dt-back" aria-pressed="false">${esc(
						__("Back to loading")
					)}</button>
				</div>
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.listHtml()}
				${this.formHtml()}
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
				reason: __("Recording daily tests needs a network connection."),
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
		if (this.notice) {
			html += this.alertHtml(
				this.notice,
				this.notice.technical ? this.standardButtons() : ""
			);
		}
		return html;
	}

	statusBadge(row) {
		const ok = row.ready_to_load;
		const label = ok
			? __("Ready to load")
			: row.status !== "Ready"
			? __(row.status, null, "Equipment")
			: row.inspection_expired
			? __("Inspection expired")
			: __("Daily test missing");
		return `<span class="tc-badge${ok ? " tc-badge-g" : " tc-badge-r"}">${esc(label)}</span>`;
	}

	listHtml() {
		if (!this.list)
			return `<p class="tc-empty">${esc(__("Scan the QR code on the machine."))}</p>`;
		if (!this.list.length)
			return `<p class="tc-empty">${esc(__("No machine needs a daily test."))}</p>`;
		const rows = this.list
			.map((row) => {
				const tests = row.required
					.map((type) => {
						const missing = row.missing.includes(type);
						return `<span class="tc-tag">${esc(dtTestLabel(type))}: ${esc(
							missing ? __("Not passed today") : __("Pass", null, "Step Gate Result")
						)}</span>`;
					})
					.join(" ");
				return `<tr>
					<td><button type="button" class="tc-btn tc-btn-secondary" data-action="dt-select" data-machine="${esc(
						row.name
					)}" aria-pressed="${
					row.name === this.selected ? "true" : "false"
				}"><span class="tc-mono">${esc(row.name)}</span> ${esc(
					row.equipment_name || ""
				)}</button></td>
					<td>${this.statusBadge(row)}${
					row.unlocked
						? ` <span class="tc-badge tc-badge-o">${esc(
								__("Unlocked temporarily")
						  )}</span>`
						: ""
				}</td>
					<td>${tests}</td>
				</tr>`;
			})
			.join("");
		return `<section class="tc-t4-block">
			<h3>${esc(__("Machines and today's daily tests"))}</h3>
			<table class="tc-t6-table"><thead><tr><th scope="col">${esc(
				__("Machine", null, "Equipment")
			)}</th><th scope="col">${esc(__("Status"))}</th><th scope="col">${esc(
			__("Daily tests")
		)}</th></tr></thead><tbody>${rows}</tbody></table>
		</section>`;
	}

	chip(action, value, label, active) {
		return `<button type="button" class="tc-chip" data-action="${action}" data-value="${esc(
			value
		)}"
			aria-pressed="${active ? "true" : "false"}">${esc(label)}</button>`;
	}

	formHtml() {
		const machine = this.machine();
		if (!machine) return "";
		const form = this.form;
		const types = machine.required
			.map((type) => this.chip("dt-type", type, dtTestLabel(type), form.test_type === type))
			.join("");
		const field = (name, label, type, extra = "") =>
			`<div class="tc-field"><label for="tc-dt-${name}">${esc(label)}</label>
				<input id="tc-dt-${name}" type="${type}" autocomplete="off" data-dt-field="${name}" value="${esc(
				form[name]
			)}" ${extra}></div>`;
		return `<section class="tc-t4-block">
			<h3>${esc(__("Daily test of {0}", [machine.name]))}</h3>
			${
				machine.required.length
					? `<div class="tc-chips" role="group" aria-label="${esc(
							__("Test type")
					  )}">${types}</div>
				<div class="tc-chips" role="group" aria-label="${esc(__("Result"))}">
					${this.chip("dt-result", "Pass", __("Pass", null, "Step Gate Result"), form.result === "Pass")}
					${this.chip("dt-result", "Fail", __("Fail", null, "Step Gate Result"), form.result === "Fail")}
				</div>
				${field("lot", __("Test pack lot"), "text")}
				${field("lot_expiry", __("Lot expiry date"), "date")}
				<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="dt-record">${esc(
					__("Record the daily test")
				)}</button></div>`
					: `<p class="tc-t6-hint">${esc(__("This machine needs no daily test."))}</p>`
			}
		</section>
		<section class="tc-t4-block">
			<h3>${esc(__("Temporary unlock (R02)"))}</h3>
			${field("reason", __("Reason for the temporary unlock"), "text")}
			${field("hours", __("Hours (1 to 24)"), "number", 'inputmode="numeric" min="1" max="24"')}
			<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="dt-unlock">${esc(
				__("Unlock temporarily")
			)}</button></div>
		</section>`;
	}
}

// T5Load và T2Wash mở màn test hằng ngày qua nút "Test hằng ngày"
function openDailyTest(screen) {
	if (screen.busy || typeof DailyTestScreen === "undefined") return;
	screen.dailyTestScreen = screen.dailyTestScreen || new DailyTestScreen(screen.station, screen);
	const target = screen.dailyTestScreen;
	target.reset();
	screen.station.screen = target;
	target.show();
	screen.station.focus(true);
}
T5Load.prototype.openDailyTest = function () {
	openDailyTest(this);
};
T2Wash.prototype.openDailyTest = function () {
	openDailyTest(this);
};
