/* global uuid4, clientTs, esc */
// Màn T7 cấp phát (SCR-12 kiosk, SCR-36 PDA, FEAT-026) trên Page station.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// TraceCoreStation giao cho T7Issue khi trạm là bước T7; một ô quét duy nhất: chọn khoa -> quét từng gói (Cycle ID)
// -> người nhận quét thẻ và ký (thẻ hoặc chữ ký cảm ứng) -> xác nhận và in. Vượt cơ số khoa cần R02 quét thẻ + PIN.
// Lỗi chặn = alert-error inline (kết quả -> lý do -> hành động). Cùng một file cho kiosk và PDA (khổ hẹp ở station.css).

const T7_API = "tracecore.v1.issue.";
// từ chối cần R02 nhập lại thẻ hoặc PIN: khối duyệt ở lại trên màn
const T7_APPROVAL_CODES = [
	"PAR_APPROVAL_REQUIRED",
	"R02_CONFIRM_REQUIRED",
	"PIN_INVALID",
	"PIN_LOCKED",
	"CARD_INVALID",
	"LOGIN_THROTTLED",
];
const T7_SIGNATURE_MIN_STROKES = 1;
const T7_PAD_WIDTH = 480;
const T7_PAD_HEIGHT = 160;

function t7Date(value) {
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || "");
	return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}

class T7Issue {
	constructor(station) {
		this.station = station;
		this.result = station.result;
		this.input = station.input;
		this.reset();
	}

	reset() {
		this.pending = null; // yêu cầu chưa có câu trả lời dứt khoát: Thử lại gửi lại y nguyên key + client_ts
		this.offline = false;
		this.busy = null;
		this.queuedScan = null; // mã quét đến khi đang chờ máy chủ: giữ lại, quét sau khi xong
		this.departments = null;
		this.context = null; // tồn khoa, cơ số, tồn kho vô khuẩn theo loại bộ của khoa đang chọn
		this.dept = null;
		this.issue = null; // phiếu nháp (issuing.view)
		this.notice = null;
		this.phase = "pack"; // pack: quét gói | sign: người nhận quét thẻ
		this.signMode = "Card";
		this.recipientCard = null; // thẻ đã quét, chờ vẽ chữ ký (chế độ Touch)
		this.mismatch = null; // thẻ người nhận lệch khoa chờ lý do
		this.fefo = null; // gói bị FEFO chặn chờ ghi chú
		this.move = null; // gói nằm ở phiếu nháp khác chờ xác nhận chuyển
		this.approval = false;
		this.done = null;
		this.strokes = 0;
		this.updatePlaceholder();
	}

	get dialogOpen() {
		return Boolean(this.mismatch || this.fefo || this.approval || this.recipientCard);
	}

	// Hết phiên trạm (rút thẻ, idle 10 phút, đổi người): xóa phiếu, khoa và yêu cầu dở của người trước
	clearSession() {
		this.reset();
	}

	// ---- quét ----
	async scan(raw) {
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		if (this.station.isOffline()) return this.station.setOffline(true);
		if (this.done) return this.station.focus();
		if (this.busy) {
			// tải tồn khoa chạy ngầm sau mỗi lần quét: không bỏ mất mã quét kế tiếp
			this.queuedScan = raw;
			return;
		}
		if (!this.issue) {
			this.notice = {
				variant: "error",
				title: __("Choose the department first"),
				reason: __("A pack was scanned before any department was chosen."),
				action: __("Tap the department that receives the packs."),
			};
			return this.show();
		}
		if (this.phase === "sign") return this.scanRecipient(raw);
		return this.addPack(raw);
	}

	addPack(raw, extra = {}) {
		this.fefo = null;
		this.move = null;
		return this.request(
			"add_pack",
			{ issue_note: this.issue.issue_note, raw, station: this.station.station, ...extra },
			(res) => {
				this.notice = null;
				this.issue = res.issue;
				this.show();
				this.loadContext();
			}
		);
	}

	scanRecipient(raw) {
		if (this.signMode === "Touch") {
			this.recipientCard = raw;
			this.strokes = 0;
			this.notice = null;
			return this.show();
		}
		return this.sign(raw, "Card");
	}

	sign(card, method, extra = {}) {
		return this.request(
			"sign",
			{
				issue_note: this.issue.issue_note,
				card,
				method,
				station: this.station.station,
				...extra,
			},
			(res) => {
				this.notice = null;
				this.issue = res.issue;
				this.mismatch = null;
				this.recipientCard = null;
				this.phase = "pack";
				this.show();
			}
		);
	}

	// ---- RPC ----
	async request(name, args, onOk) {
		if (this.busy || !this.station.session) return;
		const method = T7_API + name;
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
		this.station.focus();
		this.runQueuedScan();
	}

	runQueuedScan() {
		if (this.busy || !this.queuedScan) return;
		const raw = this.queuedScan;
		this.queuedScan = null;
		this.scan(raw);
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
			return this.request(pending.method.slice(T7_API.length), pending.args, pending.onOk);
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
				reason: __("This account cannot issue packs at this station."),
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

	// Từ chối nghiệp vụ: một số mã cần người dùng bổ sung (ghi chú FEFO, lý do khác khoa, R02 duyệt, chuyển phiếu)
	reject(error, pending) {
		this.notice = {
			variant: error.code === "FEFO_NOTE_REQUIRED" ? "warn" : "error",
			...error,
		};
		const args = pending ? pending.args : {};
		if (error.code === "FEFO_NOTE_REQUIRED") this.fefo = { raw: args.raw };
		else if (error.code === "PACK_IN_OTHER_ISSUE") this.move = { raw: args.raw };
		else if (error.code === "RECIPIENT_DEPT_MISMATCH") {
			this.mismatch = { card: args.card, method: args.method, signature: args.signature };
		} else if (T7_APPROVAL_CODES.includes(error.code))
			this.approval = true; // giữ khối duyệt để nhập lại
		else if (error.code === "ISSUE_NOT_DRAFT") this.issue = null;
		this.show();
	}

	// ---- thao tác trên màn ----
	onAction(action, button) {
		const handlers = {
			retry: () => this.retry(),
			"pick-dept": () => this.pickDepartment(button.dataset.dept),
			"change-dept": () => this.changeDepartment(),
			"remove-pack": () => this.removePack(button.dataset.pack),
			"to-sign": () => this.setPhase("sign"),
			"back-packs": () => this.setPhase("pack"),
			"sign-mode": () => this.setSignMode(button.dataset.mode),
			"sign-clear": () => this.clearPad(),
			"sign-confirm": () => this.confirmTouch(),
			"fefo-submit": () => this.submitFefo(),
			"move-submit": () => this.submitMove(),
			"mismatch-submit": () => this.submitMismatch(),
			"mismatch-cancel": () => this.cancelDialog("mismatch"),
			"fefo-cancel": () => this.cancelDialog("fefo"),
			"move-cancel": () => this.cancelDialog("move"),
			"touch-cancel": () => this.cancelDialog("recipientCard"),
			submit: () => this.submit(),
			"open-approval": () => this.openApproval(),
			"approve-submit": () => this.approve(),
			"approve-cancel": () => this.cancelDialog("approval"),
			print: () => this.print(),
			"new-issue": () => this.newIssue(),
		};
		if (!handlers[action]) return false; // offline, call-r02: TraceCoreStation xử lý
		handlers[action]();
		return true;
	}

	cancelDialog(name) {
		this[name] = name === "approval" ? false : null;
		this.notice = null;
		this.show();
		this.station.focus();
	}

	openApproval() {
		this.approval = true;
		this.notice = {
			variant: "warn",
			title: __("Department par level exceeded"),
			reason: __("R02 must approve before the packs are issued."),
			action: __("Ask R02 to scan the card and enter the PIN here."),
		};
		this.show();
	}

	setPhase(phase) {
		this.phase = phase;
		this.notice = null;
		this.recipientCard = null;
		this.mismatch = null;
		this.show();
		this.station.focus();
	}

	setSignMode(mode) {
		this.signMode = mode === "Touch" ? "Touch" : "Card";
		this.recipientCard = null;
		this.show();
		this.station.focus();
	}

	field(id) {
		const box = this.result.querySelector(`#${id}`);
		return box ? box.value.trim() : "";
	}

	markInvalid(id, message) {
		this.fieldError = { id, message };
		this.show();
		const box = this.result.querySelector(`#${id}`);
		if (box) box.focus();
	}

	submitFefo() {
		const note = this.field("tc-t7-fefo-note");
		if (!note) return this.markInvalid("tc-t7-fefo-note", __("Required"));
		this.addPack(this.fefo.raw, { note });
	}

	submitMove() {
		this.addPack(this.move.raw, { move: 1 });
	}

	submitMismatch() {
		const reason = this.field("tc-t7-mismatch-reason");
		if (!reason) return this.markInvalid("tc-t7-mismatch-reason", __("Required"));
		const { card, method, signature } = this.mismatch;
		this.sign(card, method, { reason, ...(signature ? { signature } : {}) });
	}

	confirmTouch() {
		if (this.strokes < T7_SIGNATURE_MIN_STROKES) {
			this.notice = {
				variant: "error",
				title: __("Signature is empty"),
				reason: __("Nothing was drawn in the signature box."),
				action: __("Ask the recipient to sign in the box, then confirm."),
			};
			return this.show();
		}
		const canvas = this.result.querySelector("#tc-t7-pad");
		this.sign(this.recipientCard, "Touch", { signature: canvas.toDataURL("image/png") });
	}

	// R02 quét thẻ + nhập PIN ngay trên kiosk này: proof dùng một lần gắn với phiên đang cấp phát (v1.station.verify_approver)
	async approve() {
		const card = this.field("tc-t7-approver-card");
		const pin = this.field("tc-t7-approver-pin");
		if (!card) return this.markInvalid("tc-t7-approver-card", __("Required"));
		if (!pin) return this.markInvalid("tc-t7-approver-pin", __("Required"));
		if (this.busy || !this.station.session) return;
		const version = this.station.sessionVersion;
		this.busy = "verify_approver";
		let res = null;
		let failure = null;
		try {
			res = await this.station.rpc("tracecore.v1.station.verify_approver", {
				token: this.station.session.token,
				card_id: card,
				pin,
				role: "TC R02",
				client_ts: clientTs(),
			});
		} catch (error) {
			failure = error;
		}
		if (version !== this.station.sessionVersion || (failure && failure.sessionEnded)) return;
		this.busy = null;
		if (failure) return this.failure(failure);
		if (!res || !res.ok || !res.proof) {
			return this.reject((res && res.error) || { code: "PIN_INVALID" }, null);
		}
		this.submit(res.proof);
	}

	submit(approverProof = null) {
		const extra = approverProof ? { approver_proof: approverProof } : {};
		this.approval = false;
		this.request(
			"submit",
			{ issue_note: this.issue.issue_note, station: this.station.station, ...extra },
			(res) => {
				this.done = { issue: res.issue, printUrl: res.print_url };
				this.notice = null;
				this.approval = false;
				this.show();
				this.print();
			}
		);
	}

	print() {
		if (this.done && this.done.printUrl) window.open(this.done.printUrl, "_blank", "noopener");
	}

	newIssue() {
		this.reset();
		this.show();
	}

	removePack(cycleId) {
		if (!cycleId) return;
		this.request(
			"remove_pack",
			{
				issue_note: this.issue.issue_note,
				cycle_id: cycleId,
				station: this.station.station,
			},
			(res) => {
				this.issue = res.issue;
				this.show();
				this.loadContext();
			}
		);
	}

	changeDepartment() {
		this.dept = null;
		this.issue = null;
		this.context = null;
		this.phase = "pack";
		this.notice = null;
		this.show();
	}

	pickDepartment(dept) {
		if (!dept) return;
		this.dept = dept;
		this.request("create", { department: dept, station: this.station.station }, (res) => {
			this.notice = null;
			this.issue = res.issue;
			this.phase = "pack";
			this.show();
			this.loadContext();
		});
	}

	loadDepartments() {
		if (this.busy) return;
		this.request("departments", { station: this.station.station }, (res) => {
			this.departments = res.departments;
			this.show();
		});
	}

	loadContext() {
		if (this.busy || !this.dept) return;
		const args = { department: this.dept, station: this.station.station };
		if (this.issue) args.issue_note = this.issue.issue_note;
		this.request("context", args, (res) => {
			this.context = res;
			this.show();
		});
	}

	// ---- trạng thái mạng ----
	setOffline(offline) {
		this.offline = offline;
		this.show();
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		if (this.offline && !this.issue) {
			return this.station.setState("offline", this.offlineHtml());
		}
		if (!this.departments && !this.issue && !this.busy) {
			this.loadDepartments();
			return this.station.renderLoading();
		}
		const state = this.notice && this.notice.variant === "error" ? "error" : "result";
		this.station.setState(
			state,
			`<div class="tc-t7">
				<div data-region="notice">${this.noticeHtml()}</div>
				${this.bodyHtml()}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
		this.fieldError = null;
		this.focusDialog();
		this.initPad();
	}

	focusDialog() {
		const first = this.result.querySelector("[data-dialog-focus]");
		if (first) first.focus();
	}

	updatePlaceholder() {
		let text = __("Scan the Cycle ID of the pack...");
		if (!this.issue) text = __("Choose the department, then scan the packs...");
		else if (this.done) text = __("Issue note confirmed.");
		else if (this.phase === "sign") text = __("Recipient: scan the employee card...");
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

	button(action, label, kind = "secondary", attrs = "") {
		return `<button type="button" class="tc-btn tc-btn-${kind}" data-action="${action}"${attrs}>${esc(
			label
		)}</button>`;
	}

	standardButtons() {
		return `<div class="tc-actions">
			${this.button("retry", __("Retry"), "primary")}
			${this.button("offline", __("Switch to offline"))}
			${this.button("call-r02", __("Call R02"))}
		</div>`;
	}

	offlineHtml() {
		return this.alertHtml(
			{
				variant: "info",
				title: __("Station offline"),
				reason: __("Issuing packs needs a network connection."),
				action: __("Retry when the connection returns."),
			},
			`<div class="tc-actions">
				${this.button("retry", __("Retry"), "primary")}
				${this.button("call-r02", __("Call R02"))}
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
				this.notice.technical ? this.standardButtons() : ""
			);
		}
		return html;
	}

	bodyHtml() {
		if (this.done) return this.doneHtml();
		if (!this.issue) return this.departmentsHtml();
		return `${this.headHtml()}
			${this.contextHtml()}
			${this.packsHtml()}
			${this.phase === "sign" ? this.signHtml() : this.nextHtml()}`;
	}

	// ---- chọn khoa ----
	departmentsHtml() {
		const list = this.departments || [];
		if (!list.length) {
			return `<p class="tc-empty">${esc(__("No department is available to issue to."))}</p>`;
		}
		return `<section class="tc-t6-block" aria-label="${esc(__("Department"))}">
			<h3>${esc(__("Choose the department that receives the packs"))}</h3>
			<div class="tc-t7-depts">${list
				.map((d) =>
					this.button(
						"pick-dept",
						d.department_name || d.name,
						"secondary",
						` data-dept="${esc(d.name)}"`
					)
				)
				.join("")}</div>
		</section>`;
	}

	headHtml() {
		return `<div class="tc-res-head">
			<b>${esc(this.issue.department_name || this.issue.department)}</b>
			<span class="tc-tag tc-mono">${esc(this.issue.issue_note)}</span>
			${this.button("change-dept", __("Change department"), "secondary")}
		</div>`;
	}

	// ---- tồn khoa và cơ số (UC-12 bước 1; FR-M2-16) ----
	stateBadge(row) {
		const map = {
			ok: ["g", __("Within par level")],
			over: ["r", __("Over maximum")],
			over_allowed: ["o", __("Over maximum, allowed")],
			unconfigured: ["o", __("No par level set")],
		};
		const [variant, text] = map[row.state] || ["", row.state];
		return `<span class="tc-badge${variant ? " tc-badge-" + variant : ""}">${esc(
			text
		)}</span>`;
	}

	contextHtml() {
		const rows = (this.issue.par && this.issue.par.length ? this.issue.par : []).slice();
		const base = this.context ? this.context.rows : [];
		const extra = base.filter((row) => !rows.some((r) => r.set_type === row.set_type));
		const merged = [...rows, ...extra];
		if (!merged.length) return "";
		const lowStock = merged.filter((row) => row.suggest > 0);
		const suggest = lowStock.length
			? this.alertHtml({
					variant: "info",
					title: __("Suggest issuing more"),
					reason: lowStock
						.map((row) =>
							__("{0}: {1} more pack(s) to reach the minimum", [
								row.set_name || row.set_type,
								row.suggest,
							])
						)
						.join("; "),
			  })
			: "";
		return `${suggest}<section class="tc-t6-block">
			<h3>${esc(__("Department stock and par level"))}</h3>
			${this.tableHtml(
				[
					__("Set Type"),
					__("In department"),
					__("This note"),
					__("Min"),
					__("Max"),
					__("In sterile store"),
					__("Status"),
				],
				merged.map((row) => [
					`${esc(row.set_name || "")} <span class="tc-tag">${esc(row.set_type)}</span>`,
					String(row.stock),
					String(row.adding),
					row.min === null || row.min === undefined ? "-" : String(row.min),
					row.max === null || row.max === undefined ? "-" : String(row.max),
					String(row.available === undefined ? "-" : row.available),
					this.stateBadge(row),
				])
			)}
		</section>`;
	}

	// ---- gói trong phiếu ----
	packsHtml() {
		const packs = this.issue.packs;
		const body = packs.length
			? this.tableHtml(
					[__("Cycle ID"), __("Set ID"), __("Set Name"), __("Use-by date"), ""],
					packs.map((p) => [
						`<span class="tc-mono">${esc(p.cycle_id)}</span>`,
						`<span class="tc-mono">${esc(p.set_id)}</span>`,
						esc(p.set_name || ""),
						`<b>${esc(t7Date(p.expiry))}</b>${
							p.fefo_note ? ` <span class="tc-tag">${esc(p.fefo_note)}</span>` : ""
						}`,
						this.issue.docstatus === 0
							? this.button(
									"remove-pack",
									__("Remove"),
									"secondary",
									` data-pack="${esc(p.cycle_id)}" aria-label="${esc(
										__("Remove {0}", [p.cycle_id])
									)}"`
							  )
							: "",
					])
			  )
			: `<p class="tc-t6-hint">${esc(__("Scan the Cycle ID of the first pack."))}</p>`;
		return `<section class="tc-t6-block" aria-label="${esc(__("Packs"))}">
			<h3>${esc(__("Packs on this issue note ({0})", [packs.length]))}</h3>
			${body}
		</section>${this.dialogsHtml()}`;
	}

	nextHtml() {
		if (!this.issue.packs.length) return "";
		const signed = this.issue.signed;
		const recipient = this.issue.recipient;
		const who = signed
			? `<p class="tc-t4-ok"><span aria-hidden="true">&#10003;</span> ${esc(
					__("Signed by {0}", [recipient.name || recipient.employee])
			  )}</p>`
			: `<p class="tc-t6-hint">${esc(
					__("Next: the recipient scans the employee card and signs.")
			  )}</p>`;
		let confirm = "";
		if (signed) {
			confirm = this.issue.needs_approval
				? this.button("open-approval", __("R02 approves"), "warn")
				: this.button("submit", __("Confirm and print"), "primary");
		}
		return `<section class="tc-t6-block">
			${who}
			<div class="tc-actions">
				${this.button(
					"to-sign",
					signed ? __("Sign again") : __("Recipient signs"),
					signed ? "secondary" : "primary"
				)}
				${confirm}
			</div>
			${this.approval ? this.approvalFormHtml() : ""}
		</section>`;
	}

	approvalFormHtml() {
		const err = this.fieldError;
		return `<div class="tc-t7-dialog" role="group" aria-label="${esc(__("R02 approval"))}">
			<h3>${esc(__("R02 approval"))}</h3>
			<div class="tc-field">
				<label for="tc-t7-approver-card">${esc(__("R02 employee card"))} *</label>
				<input id="tc-t7-approver-card" type="text" autocomplete="off" data-dialog-focus${
					err && err.id === "tc-t7-approver-card" ? ' class="is-error"' : ""
				}>
			</div>
			<div class="tc-field">
				<label for="tc-t7-approver-pin">${esc(__("R02 PIN"))} *</label>
				<input id="tc-t7-approver-pin" type="password" inputmode="numeric" autocomplete="off"${
					err && err.id === "tc-t7-approver-pin" ? ' class="is-error"' : ""
				}>
			</div>
			<div class="tc-actions">
				${this.button("approve-submit", __("Approve and issue"), "danger")}
				${this.button("approve-cancel", __("Cancel"))}
			</div>
		</div>`;
	}

	// ---- người nhận ký ----
	signHtml() {
		const card = this.signMode === "Card";
		const modes = `<div class="tc-actions" role="group" aria-label="${esc(
			__("Signature method")
		)}">
			${this.button(
				"sign-mode",
				__("Sign with card"),
				card ? "primary" : "secondary",
				' data-mode="Card"'
			)}
			${this.button(
				"sign-mode",
				__("Sign on screen"),
				card ? "secondary" : "primary",
				' data-mode="Touch"'
			)}
		</div>`;
		const hint = card
			? __("Recipient: scan the employee card. The card scan is the signature.")
			: __("Recipient: scan the employee card, then sign in the box.");
		return `<section class="tc-t6-block">
			<h3>${esc(__("Recipient signature"))}</h3>
			${modes}
			<p class="tc-t6-hint">${esc(hint)}</p>
			${this.recipientCard ? this.padHtml() : ""}
			<div class="tc-actions">${this.button("back-packs", __("Back to packs"))}</div>
		</section>`;
	}

	padHtml() {
		return `<div class="tc-t7-dialog" role="group" aria-label="${esc(__("Signature"))}">
			<canvas id="tc-t7-pad" class="tc-t7-pad" width="${T7_PAD_WIDTH}" height="${T7_PAD_HEIGHT}" aria-label="${esc(
			__("Signature box")
		)}"></canvas>
			<div class="tc-actions">
				${this.button("sign-confirm", __("Confirm signature"), "primary")}
				${this.button("sign-clear", __("Clear"))}
				${this.button("touch-cancel", __("Cancel"))}
			</div>
		</div>`;
	}

	initPad() {
		const canvas = this.result.querySelector("#tc-t7-pad");
		if (!canvas) return;
		const ctx = canvas.getContext("2d");
		ctx.lineWidth = 3;
		ctx.lineCap = "round";
		ctx.strokeStyle = "#000";
		let drawing = false;
		const point = (event) => {
			const box = canvas.getBoundingClientRect();
			return {
				x: ((event.clientX - box.left) * canvas.width) / box.width,
				y: ((event.clientY - box.top) * canvas.height) / box.height,
			};
		};
		canvas.addEventListener("pointerdown", (event) => {
			drawing = true;
			canvas.setPointerCapture(event.pointerId);
			const p = point(event);
			ctx.beginPath();
			ctx.moveTo(p.x, p.y);
			this.strokes += 1;
		});
		canvas.addEventListener("pointermove", (event) => {
			if (!drawing) return;
			const p = point(event);
			ctx.lineTo(p.x, p.y);
			ctx.stroke();
		});
		for (const name of ["pointerup", "pointercancel", "pointerleave"]) {
			canvas.addEventListener(name, () => {
				drawing = false;
			});
		}
	}

	clearPad() {
		const canvas = this.result.querySelector("#tc-t7-pad");
		if (!canvas) return;
		canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
		this.strokes = 0;
	}

	// ---- hộp thoại bổ sung (FEFO, khác khoa, chuyển phiếu) ----
	dialogsHtml() {
		const err = this.fieldError;
		const invalid = (id) => (err && err.id === id ? ' class="is-error"' : "");
		const errText = (id) =>
			err && err.id === id ? `<p class="tc-field-error">${esc(err.message)}</p>` : "";
		let html = "";
		if (this.fefo) {
			html += `<div class="tc-t7-dialog" role="group" aria-label="${esc(__("FEFO note"))}">
				<div class="tc-field">
					<label for="tc-t7-fefo-note">${esc(
						__("Why issue this pack and not the one that expires first?")
					)} *</label>
					<textarea id="tc-t7-fefo-note" rows="2" data-dialog-focus${invalid("tc-t7-fefo-note")}></textarea>
					${errText("tc-t7-fefo-note")}
				</div>
				<div class="tc-actions">
					${this.button("fefo-submit", __("Issue this pack with note"), "warn")}
					${this.button("fefo-cancel", __("Cancel"))}
				</div>
			</div>`;
		}
		if (this.move) {
			html += `<div class="tc-actions">
				${this.button("move-submit", __("Move the pack to this issue note"), "warn")}
				${this.button("move-cancel", __("Cancel"))}
			</div>`;
		}
		if (this.mismatch) {
			html += `<div class="tc-t7-dialog" role="group" aria-label="${esc(
				__("Recipient of another department")
			)}">
				<div class="tc-field">
					<label for="tc-t7-mismatch-reason">${esc(
						__("Reason the recipient is not from this department")
					)} *</label>
					<textarea id="tc-t7-mismatch-reason" rows="2" data-dialog-focus${invalid(
						"tc-t7-mismatch-reason"
					)}></textarea>
					${errText("tc-t7-mismatch-reason")}
				</div>
				<div class="tc-actions">
					${this.button("mismatch-submit", __("Continue with this recipient"), "warn")}
					${this.button("mismatch-cancel", __("Cancel"))}
				</div>
			</div>`;
		}
		return html;
	}

	// ---- xong ----
	doneHtml() {
		const issue = this.done.issue;
		return `<section class="tc-t6-block">
			${this.alertHtml({
				variant: "ok",
				title: __("Issue note {0} confirmed", [issue.issue_note]),
				reason: __("{0} pack(s) issued to {1}.", [
					issue.packs.length,
					issue.department_name || issue.department,
				]),
				action: __("Print the issue note, then start the next one."),
			})}
			<div class="tc-actions">
				${this.button("print", __("Print issue note"), "primary")}
				${this.button("new-issue", __("New issue note"))}
			</div>
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
