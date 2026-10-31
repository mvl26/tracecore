/* global uuid4, clientTs, esc */
// Chọn tay thiết bị và bộ/gói trên trạm (A-68): phương án dự phòng khi máy quét hỏng; quét mã vẫn là cách chính.
// Frappe nối file này sau station.js (hook page_js) nên dùng chung uuid4/clientTs/esc.
// Panel nằm ngay dưới ô quét: chọn lý do, tìm theo mã/tên (server tìm và phân trang), chạm một dòng để gửi mã đó đi
// qua đúng đường quét của màn (shell.scan), kèm entry_mode "Manual" ở RPC quét. Server kiểm lại mọi luật như khi quét.

const PICK_LOOKUP = "tracecore.v1.lookup.";
const PICK_PAGE = 20;
const PICK_DEBOUNCE_MS = 250;
// bước có thiết bị để chọn (khớp equipment.pick.STEP_TYPES ở server)
const PICK_EQUIPMENT_STEPS = ["T2", "T4", "T5", "LIN"];
// RPC quét nhận entry_mode / manual_reason (server bỏ qua tham số này ở RPC khác sẽ báo lỗi, nên chỉ gắn cho các RPC này)
const PICK_SCAN_METHODS = [
	"tracecore.v1.wash.start",
	"tracecore.v1.wash.add_set",
	"tracecore.v1.load.create",
	"tracecore.v1.load.add_pack",
	"tracecore.v1.pack.scan",
	"tracecore.v1.putaway.scan",
	"tracecore.v1.usage.scan",
	"tracecore.v1.receive.scan_set",
	"tracecore.v1.assembly.open",
	"tracecore.v1.issue.add_pack",
];

function pickReasons() {
	return [
		{ value: "Scanner broken", label: __("Scanner broken") },
		{ value: "Label unreadable or torn", label: __("Label unreadable or torn") },
		{ value: "Other", label: __("Other reason") },
	];
}

class TcPicker {
	constructor(shell) {
		this.shell = shell;
		this.isOpen = false;
		this.kind = "set";
		this.query = "";
		this.items = [];
		this.total = 0;
		this.state = "loading"; // loading | ready | empty | error | offline
		this.error = null;
		this.busy = false;
		this.generation = 0;
		this.timer = null;
		this.reason = null;
		this.el = null;
	}

	get step() {
		return this.shell.stationInfo && this.shell.stationInfo.step;
	}

	hasEquipment() {
		return PICK_EQUIPMENT_STEPS.includes(this.step);
	}

	open() {
		if (this.isOpen) return this.close();
		this.isOpen = true;
		this.kind = this.hasEquipment() ? "equipment" : "set";
		this.query = "";
		this.el = document.createElement("section");
		this.el.className = "tc-card tc-picker";
		this.el.setAttribute("aria-label", __("Choose by hand"));
		const result = this.shell.root.querySelector(".tc-work .tc-result");
		result.parentNode.insertBefore(this.el, result);
		this.render();
		this.load(true);
	}

	close() {
		this.isOpen = false;
		this.generation += 1;
		clearTimeout(this.timer);
		if (this.el) this.el.remove();
		this.el = null;
		this.shell.focus(true);
	}

	// phiên kết thúc / đổi người: bỏ panel và lý do đã chọn
	reset() {
		this.reason = null;
		if (this.isOpen) this.close();
	}

	onAction(action, button) {
		if (action === "manual-pick") {
			this.open();
			return true;
		}
		if (!this.isOpen) return false;
		if (action === "pick-close") this.close();
		else if (action === "pick-kind") this.setKind(button.dataset.kind);
		else if (action === "pick-reason") this.setReason(button.dataset.value);
		else if (action === "pick-more") this.load(false);
		else if (action === "pick-retry") this.load(true);
		else if (action === "pick-item") this.choose(button.dataset.raw);
		else return false;
		return true;
	}

	setKind(kind) {
		if (kind === this.kind) return;
		this.kind = kind;
		this.query = "";
		this.render();
		this.load(true);
	}

	setReason(value) {
		this.reason = value;
		this.render();
	}

	onInput(value) {
		this.query = value;
		clearTimeout(this.timer);
		this.timer = setTimeout(() => this.load(true), PICK_DEBOUNCE_MS);
	}

	async load(reset) {
		const generation = ++this.generation;
		if (this.shell.isOffline()) {
			this.state = "offline";
			return this.render();
		}
		if (reset) {
			this.items = [];
			this.total = 0;
			this.state = "loading";
			this.render();
		}
		this.busy = true;
		const method = PICK_LOOKUP + (this.kind === "equipment" ? "equipment" : "set_units");
		const args = {
			station: this.shell.station,
			q: this.query.trim() || null,
			start: this.items.length,
			page_length: PICK_PAGE,
			client_ts: clientTs(),
		};
		const department = this.kind === "set" ? this.shell.pickDepartment() : null;
		if (department) args.department = department;
		let response = null;
		let failure = null;
		try {
			response = await this.shell.rpc(method, args, uuid4());
		} catch (error) {
			failure = error;
		}
		if (generation !== this.generation || !this.isOpen) return;
		this.busy = false;
		if (failure && failure.sessionEnded) return;
		if (failure) {
			this.state = failure.offline && navigator.onLine === false ? "offline" : "error";
			this.error = {
				title: __("Could not load the list"),
				reason: __("The server did not answer."),
				action: __("Check the connection, then press Retry."),
			};
		} else if (response && response.ok === false) {
			this.state = "error";
			this.error = response.error;
		} else {
			this.items = this.items.concat(response.items || []);
			this.total = response.total || 0;
			this.state = this.items.length ? "ready" : "empty";
		}
		this.render();
	}

	async choose(raw) {
		if (!raw || this.busy || this.shell.busyForPick()) return;
		if (!this.reason) return this.render();
		const reason = this.reason;
		// một màn quét có thể gọi nhiều RPC; mọi RPC quét trong lúc này gắn entry_mode Manual (shell.rpc)
		this.shell.manualEntry = { reason };
		this.close();
		try {
			await this.shell.scan(raw);
			await this.shell.waitIdle();
		} finally {
			this.shell.manualEntry = null;
		}
	}

	render() {
		if (!this.el) return;
		const keep = this.el.querySelector("#tc-pick-search");
		const hadFocus = keep && document.activeElement === keep;
		this.el.innerHTML = `<div class="tc-picker-head">
				<h3>${esc(__("Choose by hand"))}</h3>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="pick-close">${esc(
					__("Close")
				)}</button>
			</div>
			<p class="tc-picker-hint">${esc(
				__(
					"Use this only when the scanner does not work. The server checks the code exactly as if it were scanned."
				)
			)}</p>
			${this.reasonHtml()}
			${this.kindHtml()}
			<label class="tc-sr-only" for="tc-pick-search">${esc(__("Search by code or name"))}</label>
			<input id="tc-pick-search" class="tc-pick-search" type="text" inputmode="text" autocomplete="off"
				autocapitalize="off" spellcheck="false" value="${esc(this.query)}"
				placeholder="${esc(__("Search by code or name..."))}" />
			${this.listHtml()}`;
		const search = this.el.querySelector("#tc-pick-search");
		search.addEventListener("input", () => this.onInput(search.value));
		if (hadFocus) {
			search.focus({ preventScroll: true });
			search.setSelectionRange(search.value.length, search.value.length);
		}
	}

	reasonHtml() {
		const chips = pickReasons()
			.map(
				(item) =>
					`<button type="button" class="tc-btn tc-pick-chip${
						this.reason === item.value ? " is-active" : ""
					}" data-action="pick-reason" data-value="${esc(item.value)}" aria-pressed="${
						this.reason === item.value
					}">${this.reason === item.value ? "&#10003; " : ""}${esc(item.label)}</button>`
			)
			.join("");
		const missing = this.reason
			? ""
			: `<p class="tc-picker-need">${esc(__("Choose a reason before selecting."))}</p>`;
		return `<div class="tc-picker-reasons" role="group" aria-label="${esc(
			__("Reason")
		)}">${chips}</div>${missing}`;
	}

	kindHtml() {
		if (!this.hasEquipment()) return "";
		const tab = (kind, label) =>
			`<button type="button" class="tc-btn tc-pick-chip${
				this.kind === kind ? " is-active" : ""
			}" data-action="pick-kind" data-kind="${kind}" aria-pressed="${
				this.kind === kind
			}">${esc(label)}</button>`;
		return `<div class="tc-picker-kinds" role="group" aria-label="${esc(
			__("What to choose")
		)}">${tab("equipment", __("Equipment"))}${tab("set", __("Sets and packs"))}</div>`;
	}

	listHtml() {
		if (this.state === "loading")
			return `<p class="tc-empty" role="status">${esc(__("Loading..."))}</p>`;
		if (this.state === "offline")
			return `<div class="tc-alert tc-alert-info" role="status"><p>${esc(
				__("Offline - the list cannot be loaded.")
			)}</p><button type="button" class="tc-btn tc-btn-secondary" data-action="pick-retry">${esc(
				__("Retry")
			)}</button></div>`;
		if (this.state === "error") {
			const error = this.error || {};
			return `<div class="tc-alert tc-alert-error" role="alert"><p class="tc-alert-title">${esc(
				error.title || ""
			)}</p><p>${esc(error.reason || "")}</p><p>${esc(
				error.action || ""
			)}</p><button type="button" class="tc-btn tc-btn-secondary" data-action="pick-retry">${esc(
				__("Retry")
			)}</button></div>`;
		}
		if (this.state === "empty")
			return `<p class="tc-empty" role="status">${esc(
				__("Nothing matches. Try another code or name.")
			)}</p>`;
		const rows = this.items
			.map(
				(
					item
				) => `<li><button type="button" class="tc-btn tc-pick-item" data-action="pick-item"
					data-raw="${esc(item.raw || item.id)}"${this.reason ? "" : " disabled"}>
					<span class="tc-mono">${esc(item.id)}</span>
					<span>${esc(this.itemText(item))}</span></button></li>`
			)
			.join("");
		const more =
			this.items.length < this.total
				? `<button type="button" class="tc-btn tc-btn-secondary tc-pick-more" data-action="pick-more"${
						this.busy ? " disabled" : ""
				  }>${esc(__("Show more"))} (${this.items.length}/${this.total})</button>`
				: "";
		return `<ul class="tc-pick-list">${rows}</ul>${more}`;
	}

	// phần sau mã trong nhãn "Mã – Tên – Khoa – thời điểm"
	itemText(item) {
		const label = item.label || "";
		const prefix = `${item.id} – `;
		return label.startsWith(prefix) ? label.slice(prefix.length) : label;
	}
}
