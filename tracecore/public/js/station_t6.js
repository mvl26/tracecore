/* global uuid4, clientTs, esc */
// Màn T6 kho vô khuẩn (SCR-11, FEAT-025) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// TraceCoreStation giao cho T6Storage khi trạm là bước T6: một ô quét duy nhất; quét Cycle ID mở thẻ gói (kèm năm
// cổng), quét mã kệ KE- thì nhập kho hoặc chuyển vị trí. Lỗi chặn = alert-error inline (kết quả → lý do → hành động).

const T6_SCAN = "tracecore.v1.putaway.scan";
const T6_OVERVIEW = "tracecore.v1.putaway.overview";
const T6_DAMAGED = "tracecore.v1.pack.mark_damaged";
// từ chối của lần quét kệ không làm gói đang mở hết ý nghĩa: giữ thẻ gói để quét lại kệ khác
const T6_KEEP_PACK_CODES = [
	"LOCATION_NOT_FOUND",
	"LOCATION_INACTIVE",
	"PACK_ALREADY_ON_LOCATION",
	"SCAN_INVALID",
];
const T6_PACK_BADGE = {
	Released: "g",
	"In Sterile Stock": "g",
	Packed: "",
	"In Load": "",
	Quarantine: "o",
	Void: "x",
	Recalled: "r",
};

function t6Date(value) {
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
	return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

function t6GateLabel(step) {
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

class T6Storage {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.offline = false;
		this.busy = null;
		this.overview = null;
		this.pack = null; // thẻ gói đang mở (pack.scan kind=pack)
		this.notice = null;
		this.damaging = false; // đang nhập lý do báo rách/ướt
		this.reasonError = false;
	}

	get dialogOpen() {
		return this.damaging; // ô lý do giữ focus, ô quét không giành lại
	}

	openPack() {
		return this.pack ? this.pack.cycle_id : null;
	}

	// ---- quét và gọi RPC ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline()) return this.station.setOffline(true);
		this.damaging = false;
		await this.request(
			T6_SCAN,
			{ raw, station: this.station.station, open_pack: this.openPack() },
			(res) => this.onScan(res)
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
		let response = null;
		let failure = null;
		const started = performance.now();
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
		else if (response && response.ok === false) this.reject(response.error);
		else onOk(response);
		this.station.focus();
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
				reason: __("This account cannot store packs at this station."),
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
		if (!T6_KEEP_PACK_CODES.includes(error.code)) this.pack = null;
		this.notice = { variant: "error", ...error };
		this.show();
	}

	onScan(res) {
		this.notice = null;
		if (res.kind === "pack") {
			this.pack = res.pack;
		} else if (res.kind === "stored") {
			const done = res.stored;
			this.notice = {
				variant: "ok",
				title:
					done.action === "Move"
						? __("Pack {0} moved to {1}", [done.cycle_id, done.location])
						: __("Pack {0} stored on {1}", [done.cycle_id, done.location]),
				reason: __("Use-by date {0}", [t6Date(done.expiry)]),
				action: __("Scan the next pack."),
			};
			this.pack = null;
		}
		this.show();
		if (res.kind === "stored") this.loadOverview(); // tồn và danh sách hết hạn đã đổi
	}

	// ---- thao tác trên màn ----
	onAction(action) {
		const handlers = {
			retry: () => this.retry(),
			damaged: () => this.startDamaged(),
			"damaged-cancel": () => this.cancelDamaged(),
			"damaged-submit": () => this.submitDamaged(),
			"close-pack": () => {
				this.pack = null;
				this.notice = null;
				this.show();
			},
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	startDamaged() {
		if (!this.pack || this.pack.status !== "In Sterile Stock") return;
		this.damaging = true;
		this.reasonError = false;
		this.show();
		const box = this.result.querySelector("#tc-t6-reason");
		if (box) box.focus();
	}

	cancelDamaged() {
		this.damaging = false;
		this.show();
		this.station.focus();
	}

	submitDamaged() {
		const box = this.result.querySelector("#tc-t6-reason");
		const reason = box ? box.value.trim() : "";
		if (!reason) {
			this.reasonError = true;
			this.show();
			const again = this.result.querySelector("#tc-t6-reason");
			if (again) again.focus();
			return;
		}
		const cycleId = this.openPack();
		this.damaging = false;
		this.request(
			T6_DAMAGED,
			{ cycle_id: cycleId, reason, station: this.station.station },
			() => {
				this.notice = {
					variant: "ok",
					title: __("Pack {0} is no longer valid", [cycleId]),
					reason: __("The set is waiting to go back to the dirty zone."),
					action: __("Take the pack to the dirty zone."),
				};
				this.pack = null;
				this.show();
				this.loadOverview();
			}
		);
	}

	// ---- trạng thái mạng ----
	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		if (this.offline && !this.pack) {
			return this.station.setState("offline", this.offlineHtml());
		}
		if (!this.pack && !this.overview && !this.notice && !this.busy) {
			this.loadOverview();
			return this.station.renderLoading();
		}
		const state = this.notice && this.notice.variant === "error" ? "error" : "result";
		this.station.setState(
			state,
			`<div class="tc-t6">
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.pack ? this.packHtml() : this.overviewHtml()}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
		if (this.damaging) {
			const box = this.result.querySelector("#tc-t6-reason");
			if (box) box.focus();
		}
	}

	loadOverview() {
		if (this.busy) return;
		this.request(T6_OVERVIEW, { station: this.station.station }, (res) => {
			this.overview = res;
			this.show();
		});
	}

	updatePlaceholder() {
		const text = this.pack
			? __("Scan the shelf code (KE-)...")
			: __("Scan the Cycle ID of the pack...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	alertHtml(notice, buttons = "") {
		const variant = notice.variant || "error";
		const icon = { error: "&#10005;", warn: "!", ok: "&#10003;", info: "i" }[variant];
		const items = (notice.items || []).map((item) => `<li>${esc(item)}</li>`).join("");
		return `<div class="tc-alert tc-alert-${variant}" role="${
			variant === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(notice.title)}</p>
			${notice.reason ? `<p class="tc-alert-reason">${esc(notice.reason)}</p>` : ""}
			${items ? `<ul class="tc-alert-items">${items}</ul>` : ""}
			${notice.action ? `<p class="tc-alert-action">${esc(notice.action)}</p>` : ""}
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
				reason: __("Storing packs needs a network connection."),
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
			const standalone = !this.pack && this.notice.variant === "error";
			html += this.alertHtml(
				this.notice,
				this.notice.technical || standalone ? this.standardButtons() : ""
			);
		}
		return html;
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
		return `<div class="tc-gate${cls ? " tc-gate-" + cls : ""}">
			<small>${esc(t6GateLabel(gate.step))}</small>
			<b><span aria-hidden="true">${mark}</span>${esc(text)}</b>
		</div>`;
	}

	packHtml() {
		const pack = this.pack;
		const variant = T6_PACK_BADGE[pack.status] || "";
		const stored = pack.status === "In Sterile Stock";
		const hint = stored
			? __("Pack is on {0}. Scan another shelf to move it.", [pack.location])
			: __("Scan the shelf code (KE-) to store the pack.");
		return `<section class="tc-t6-block" aria-label="${esc(__("Pack"))}">
			<div class="tc-res-head">
				<b class="tc-code">${esc(pack.cycle_id)}</b>
				<span class="tc-badge${variant ? " tc-badge-" + variant : ""}">${esc(
			__(pack.status, null, "Pack")
		)}</span>
			</div>
			<dl class="tc-res-grid">
				<dt>${esc(__("Set ID"))}</dt><dd class="tc-mono">${esc(pack.set_id)}</dd>
				<dt>${esc(__("Set Name"))}</dt><dd>${esc(pack.set_name)}</dd>
				<dt>${esc(__("Use-by date"))}</dt><dd><b>${esc(t6Date(pack.expiry))}</b></dd>
				<dt>${esc(__("Storage Location"))}</dt><dd class="tc-mono">${esc(pack.location || "-")}</dd>
			</dl>
			<div class="tc-gates" aria-label="${esc(__("Step gates"))}">${(pack.gates || [])
			.map((gate) => this.gateHtml(gate))
			.join("")}</div>
			<p class="tc-t6-hint">${esc(hint)}</p>
			${this.damaging ? this.damagedFormHtml() : this.packActionsHtml(stored)}
		</section>`;
	}

	packActionsHtml(stored) {
		return `<div class="tc-actions">
			${
				stored
					? `<button type="button" class="tc-btn tc-btn-danger" data-action="damaged">${esc(
							__("Report torn / wet pack")
					  )}</button>`
					: ""
			}
			<button type="button" class="tc-btn tc-btn-secondary" data-action="close-pack">${esc(
				__("Close")
			)}</button>
		</div>`;
	}

	damagedFormHtml() {
		return `<div class="tc-field">
			<label for="tc-t6-reason">${esc(__("What is wrong with the pack?"))} *</label>
			<textarea id="tc-t6-reason" rows="3" aria-describedby="tc-t6-reason-err"${
				this.reasonError ? ' class="is-error"' : ""
			}></textarea>
			<p class="tc-field-error" id="tc-t6-reason-err"${this.reasonError ? "" : " hidden"}>${esc(
			__("Required")
		)}</p>
		</div>
		<div class="tc-actions">
			<button type="button" class="tc-btn tc-btn-danger" data-action="damaged-submit">${esc(
				__("Confirm: pack is no longer valid")
			)}</button>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="damaged-cancel">${esc(
				__("Cancel")
			)}</button>
		</div>`;
	}

	overviewHtml() {
		const data = this.overview;
		if (!data) {
			return `<p class="tc-empty">${esc(__("Scan the Cycle ID of the pack to store."))}</p>`;
		}
		const empty = !data.by_set_type.length;
		return `<p class="tc-empty">${esc(__("Scan the Cycle ID of the pack to store."))}</p>
			<section class="tc-t6-block">
				<h3>${esc(__("Sterile stock by set type"))}</h3>
				${
					empty
						? `<p class="tc-t6-hint">${esc(__("No packs in the sterile store."))}</p>`
						: this.tableHtml(
								[__("Set Type"), __("Packs"), __("Earliest use-by")],
								data.by_set_type.map((row) => [
									`${row.set_name || ""} <span class="tc-tag">${esc(
										row.set_type
									)}</span>`,
									String(row.count),
									t6Date(row.nearest_expiry),
								])
						  )
				}
			</section>
			<section class="tc-t6-block">
				<h3>${esc(__("Stock by location"))}</h3>
				${this.tableHtml(
					[__("Location"), __("Packs")],
					data.by_location.map((row) => [
						`<span class="tc-mono">${esc(row.location)}</span> ${esc(
							row.location_name || ""
						)}`,
						String(row.count),
					])
				)}
			</section>
			<section class="tc-t6-block">
				<h3>${esc(__("Packs expiring within 7 days"))}</h3>
				${
					data.expiring.length
						? this.tableHtml(
								[
									__("Cycle ID"),
									__("Use-by date"),
									__("Days left"),
									__("Location"),
								],
								data.expiring.map((row) => [
									`<span class="tc-mono">${esc(row.cycle_id)}</span>`,
									t6Date(row.expiry),
									String(row.days_left),
									`<span class="tc-mono">${esc(row.location || "-")}</span>`,
								])
						  )
						: `<p class="tc-t6-hint">${esc(
								__("No packs expire in the next 7 days.")
						  )}</p>`
				}
			</section>
			<section class="tc-t6-block">
				<h3>${esc(__("Packs to return to the dirty zone"))}</h3>
				${
					data.return_list.length
						? this.tableHtml(
								[
									__("Cycle ID"),
									__("Set Name"),
									__("Void Reason"),
									__("Location"),
								],
								data.return_list.map((row) => [
									`<span class="tc-mono">${esc(row.cycle_id)}</span>`,
									esc(row.set_name || ""),
									esc(__(row.void_reason, null, "Pack")),
									`<span class="tc-mono">${esc(row.location || "-")}</span>`,
								])
						  )
						: `<p class="tc-t6-hint">${esc(__("No packs are waiting to return."))}</p>`
				}
			</section>`;
	}

	// ô bảng nhận HTML đã escape ở nơi gọi; tiêu đề cột là chuỗi thường
	tableHtml(headers, rows) {
		return `<table class="tc-t6-table">
			<thead><tr>${headers.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead>
			<tbody>${rows
				.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
				.join("")}</tbody>
		</table>`;
	}
}
