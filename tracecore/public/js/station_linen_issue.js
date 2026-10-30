/* global LinenCollect, TcWeighLine, linenTabs, esc */
// Màn cấp phát đồ vải theo khoa (SCR-18, FEAT-035, UC-18) trên Page station, trạm bước LIN, tab "Cấp phát".
// Lớp con của LinenCollect: dùng lại request/failure/retry/alert. Hai bước: (1) chọn khoa và loại cấp (Trả sau giặt hoặc
// Cấp mới), thêm dòng loại – số chiếc – kg, xem chưa trả / tồn khoa / định mức và cảnh báo vượt tối đa (không chặn);
// (2) người nhận quét thẻ, ký bằng thẻ hoặc cảm ứng, rồi ghi sổ và in biên nhận. Hủy đồ vải làm trên Desk (cần ảnh).

const LIN_BALANCE = "tracecore.v1.linen.balance";
const LIN_ISSUE = "tracecore.v1.linen.issue";
const LIN_PAD_WIDTH = 480;
const LIN_PAD_HEIGHT = 160;
const LIN_SIGNATURE_MIN_STROKES = 1;

class LinenIssue extends LinenCollect {
	constructor(station) {
		super(station);
		this.balance = null; // chưa trả / tồn khoa / định mức theo loại của khoa đang chọn
		this.phase = "form";
		this.signMode = "Card";
		this.recipientCard = null;
		this.strokes = 0;
	}

	blankForm() {
		return { department: "", kind: "Return", note: "", lines: [this.blankLine()] };
	}

	clearSession() {
		this.balance = null;
		this.phase = "form";
		this.signMode = "Card";
		this.recipientCard = null;
		this.strokes = 0;
		super.clearSession();
	}

	updatePlaceholder() {
		const text =
			this.phase === "sign"
				? __("Recipient: scan the employee card...")
				: __("Type or scan a linen type name to add a line...");
		this.input.placeholder = text;
		this.input.setAttribute("aria-label", text);
	}

	// ---- quét: thẻ người nhận (bước ký) hoặc tên loại đồ vải (bước nhập) ----
	async scan(raw) {
		if (this.phase !== "sign") return super.scan(raw);
		raw = (raw || "").trim();
		this.input.value = "";
		if (!raw) return this.station.focus();
		this.notice = null;
		if (this.signMode === "Card") return this.submit(raw);
		this.recipientCard = raw;
		this.strokes = 0;
		this.show();
	}

	onInput(event) {
		const target = event.target;
		const field = target && target.dataset && target.dataset.field;
		if (!field || !this.station.session) return;
		const line = this.form.lines.find((row) => row.id === target.dataset.row);
		if (field === "department") {
			this.form.department = target.value;
			this.balance = null;
			if (target.value) this.loadBalance();
			else this.show();
		} else if (field === "kind") {
			this.form.kind = target.value;
			this.refreshWarning();
		} else if (field === "note") this.form.note = target.value;
		else if (line) this.onIssueLineInput(line, field, target.value);
	}

	onIssueLineInput(line, field, value) {
		if (field === "variance_note") line.variance_note = value;
		else if (field === "linen_type") line.linen_type = value;
		else if (field === "qty") line.qty = value;
		else if (field === "weight_kg") line.weight = value;
		else return;
		if (field === "weight_kg") delete (this.errors[line.id] || {}).weight;
		this.refreshHint(line);
		this.refreshWarning();
	}

	loadBalance() {
		this.request(
			LIN_BALANCE,
			{ station: this.station.station, department: this.form.department },
			(res) => {
				this.balance = res.balance || [];
				this.show();
			}
		);
	}

	balanceRow(type) {
		return (this.balance || []).find((row) => row.linen_type === type);
	}

	// Cảnh báo vượt định mức tối đa (FR-M3-05.2): tồn khoa hiện tại + số cấp > max; không chặn
	warnings() {
		if (!this.balance) return [];
		const issued = {};
		for (const line of this.form.lines) {
			const qty = Number(line.qty);
			if (line.linen_type && Number.isFinite(qty) && qty > 0)
				issued[line.linen_type] = (issued[line.linen_type] || 0) + qty;
		}
		return Object.entries(issued)
			.map(([type, qty]) => ({ type, qty, row: this.balanceRow(type) }))
			.filter(({ qty, row }) => row && row.max_qty && row.stock + qty > row.max_qty);
	}

	warningHtml() {
		const items = this.warnings().map(({ type, qty, row }) =>
			__("{0}: stock {1} + issued {2} exceeds the maximum {3}.", [
				type,
				row.stock,
				qty,
				row.max_qty,
			])
		);
		if (!items.length) return "";
		return this.alertHtml({
			variant: "warn",
			title: __("Over the department quota"),
			reason: __("The department would hold more than its maximum."),
			items,
			action: __("You can still record; the warning is kept on the issue."),
		});
	}

	refreshWarning() {
		const box = this.result.querySelector('[data-region="warning"]');
		if (box) box.innerHTML = this.warningHtml();
	}

	// ---- thao tác ----
	onAction(action, button) {
		const handlers = {
			retry: () => this.retry(),
			"add-line": () => this.addLine(),
			"remove-line": () => this.removeLine(button.dataset.row),
			"to-sign": () => this.toSign(),
			"back-form": () => this.setPhase("form"),
			"sign-mode": () => this.setSignMode(button.dataset.mode),
			"sign-clear": () => this.clearPad(),
			"sign-confirm": () => this.confirmTouch(),
			print: () => this.print(),
			"new-issue": () => this.newIssue(),
		};
		if (!handlers[action]) return false;
		handlers[action]();
		return true;
	}

	setPhase(phase) {
		this.phase = phase;
		this.notice = null;
		this.recipientCard = null;
		this.show();
		this.station.focus();
	}

	setSignMode(mode) {
		this.signMode = mode === "Touch" ? "Touch" : "Card";
		this.recipientCard = null;
		this.show();
		this.station.focus();
	}

	newIssue() {
		this.done = null;
		this.notice = null;
		this.errors = {};
		this.phase = "form";
		this.recipientCard = null;
		this.form = { ...this.blankForm(), department: this.form.department };
		this.show();
	}

	print() {
		if (!this.done) return;
		const query = new URLSearchParams({
			doctype: "Linen Issue",
			name: this.done.issue,
			format: "TC Linen Issue Receipt",
			trigger_print: "1",
			no_letterhead: "1",
		});
		window.open(`/printview?${query}`, "_blank", "noopener");
	}

	// ---- kiểm tra và ghi sổ ----
	problems() {
		const items = [];
		const errors = {};
		if (!this.form.department) items.push(__("Choose the department."));
		const filled = this.form.lines.filter(
			(line) => line.linen_type || line.qty || line.weight
		);
		if (!filled.length) items.push(__("Add at least one linen type with pieces or weight."));
		for (const line of filled) {
			const { qty, weight } = this.numbers(line);
			if (!this.typeInfo(line.linen_type)) {
				items.push(
					__("Choose a linen type for {0}.", [__("a line without a linen type")])
				);
				continue;
			}
			if ((!qty || qty <= 0) && weight == null)
				items.push(__("Enter the pieces or the weight of {0}.", [line.linen_type]));
			if (this.overTolerance(line) && !line.variance_note.trim()) {
				errors[line.id] = { note: __("Required") };
				items.push(
					__("{0}: the weight differs by more than 15 %, enter a note.", [
						line.linen_type,
					])
				);
			}
		}
		this.errors = errors;
		return items;
	}

	toSign() {
		const items = this.problems();
		if (items.length) {
			this.notice = {
				variant: "error",
				title: __("The issue is not complete"),
				reason: __("Some required values are missing or need confirmation."),
				items,
				action: __("Fix the highlighted values, then continue."),
			};
			return this.show();
		}
		this.setPhase("sign");
	}

	payload(card, signature) {
		const lines = this.form.lines
			.filter((line) => line.linen_type || line.qty || line.weight)
			.map((line) => {
				const { qty, weight } = this.numbers(line);
				const row = { linen_type: line.linen_type };
				if (qty != null && qty > 0) row.qty = qty;
				if (weight != null) {
					row.weight_kg = weight;
					row.weight_source = "Manual";
				}
				if (line.variance_note.trim()) row.variance_note = line.variance_note.trim();
				return row;
			});
		const args = {
			station: this.station.station,
			department: this.form.department,
			kind: this.form.kind,
			recipient_card: card,
			sign_method: this.signMode,
			lines,
		};
		if (signature) args.signature = signature;
		if (this.form.note.trim()) args.note = this.form.note.trim();
		return args;
	}

	confirmTouch() {
		if (this.strokes < LIN_SIGNATURE_MIN_STROKES) {
			this.notice = {
				variant: "error",
				title: __("Signature is empty"),
				reason: __("Nothing was drawn in the signature box."),
				action: __("Ask the recipient to sign in the box, then confirm."),
			};
			return this.show();
		}
		const canvas = this.result.querySelector("#tc-lin-pad");
		this.submit(this.recipientCard, canvas.toDataURL("image/png"));
	}

	submit(card, signature) {
		this.request(LIN_ISSUE, this.payload(card, signature), (res) => {
			this.done = res.issue;
			this.balance = res.issue.balance;
			this.phase = "form";
			this.recipientCard = null;
			this.errors = {};
			this.show();
		});
	}

	// ---- render ----
	show() {
		this.updatePlaceholder();
		if (this.offline) return this.station.setState("offline", this.offlineHtml());
		if (!this.catalog && !this.notice && !this.busy) {
			this.loadCatalog();
			return this.station.renderLoading();
		}
		const failed = this.notice && this.notice.variant === "error";
		const state = failed
			? "error"
			: this.catalog && !this.catalog.types.length
			? "empty"
			: "result";
		let body = "";
		if (this.done) body = this.doneHtml();
		else if (this.catalog) body = this.phase === "sign" ? this.signHtml() : this.formHtml();
		this.station.setState(
			state,
			`<div class="tc-linen">
				${linenTabs("issue")}
				<div data-region="notice">${this.noticeHtml()}</div>
				${body}
			</div>`
		);
		this.station.form.classList.toggle("is-error", state === "error");
		if (this.phase === "sign" && this.signMode === "Touch" && this.recipientCard)
			this.initPad();
	}

	formHtml() {
		if (!this.catalog.types.length) return "";
		const departments = this.catalog.departments
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						this.form.department === row.name ? " selected" : ""
					}>${esc(row.department_name || row.name)}</option>`
			)
			.join("");
		const kind = (value, label) =>
			`<option value="${value}"${this.form.kind === value ? " selected" : ""}>${esc(
				label
			)}</option>`;
		return `<section class="tc-t6-block" aria-label="${esc(__("Linen issue"))}">
			<div class="tc-linen-head">
				<div class="tc-field">
					<label for="tc-lin-department">${esc(__("Department"))} *</label>
					<select id="tc-lin-department" data-field="department">
						<option value="">${esc(__("Choose the department"))}</option>${departments}
					</select>
				</div>
				<div class="tc-field">
					<label for="tc-lin-kind">${esc(__("Kind"))}</label>
					<select id="tc-lin-kind" data-field="kind">
						${kind("Return", __("Return after laundry"))}${kind("New", __("New from stock"))}
					</select>
				</div>
			</div>
			${this.balanceHtml()}
			<div data-region="warning">${this.warningHtml()}</div>
			<div class="tc-linen-lines">${this.form.lines
				.map((line) => this.issueLineHtml(line))
				.join("")}</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-secondary" data-action="add-line">${esc(
					__("Add a line")
				)}</button>
			</div>
			<div class="tc-field">
				<label for="tc-lin-note">${esc(__("Note"))}</label>
				<textarea id="tc-lin-note" rows="2" data-field="note">${esc(this.form.note)}</textarea>
			</div>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="to-sign"${
					this.busy ? " disabled" : ""
				}>${esc(__("Next: recipient signs"))}</button>
			</div>
		</section>`;
	}

	// Chưa trả (thu − trả − hủy), tồn khoa và định mức của khoa đang chọn (UC-18 bước 2)
	balanceHtml() {
		if (!this.form.department) return "";
		if (!this.balance)
			return `<p class="tc-loading" role="status">${esc(__("Loading..."))}</p>`;
		const rows = this.balance
			.filter((row) => row.collected || row.stock || row.min_qty || row.max_qty)
			.map(
				(row) => `<tr>
					<td>${esc(row.linen_type)}</td>
					<td>${esc(row.unreturned)}</td>
					<td>${esc(TcWeighLine.format(row.unreturned_kg))}</td>
					<td>${esc(row.stock)}</td>
					<td>${esc(row.min_qty == null ? "-" : row.min_qty)}</td>
					<td>${esc(row.max_qty == null ? "-" : row.max_qty)}</td>
				</tr>`
			)
			.join("");
		if (!rows)
			return `<p class="tc-t6-hint">${esc(
				__("This department has no collection or quota yet.")
			)}</p>`;
		return `<table class="tc-t6-table">
			<caption>${esc(__("Not returned yet and department stock"))}</caption>
			<thead><tr>
				<th scope="col">${esc(__("Linen Type"))}</th>
				<th scope="col">${esc(__("Not returned"))}</th>
				<th scope="col">${esc(__("Not returned (kg)"))}</th>
				<th scope="col">${esc(__("Department stock"))}</th>
				<th scope="col">${esc(__("Min"))}</th>
				<th scope="col">${esc(__("Max"))}</th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>`;
	}

	issueLineHtml(line) {
		const errors = this.errors[line.id] || {};
		const options = this.catalog.types
			.map(
				(row) =>
					`<option value="${esc(row.name)}"${
						line.linen_type === row.name ? " selected" : ""
					}>${esc(row.name)}</option>`
			)
			.join("");
		return `<div class="tc-linen-line" data-line="${esc(line.id)}">
			<div class="tc-field">
				<label for="tc-lin-type-${esc(line.id)}">${esc(__("Linen Type"))}</label>
				<select id="tc-lin-type-${esc(line.id)}" data-field="linen_type" data-row="${esc(line.id)}">
					<option value="">${esc(__("Choose the linen type"))}</option>${options}
				</select>
			</div>
			<div class="tc-field">
				<label for="tc-lin-qty-${esc(line.id)}">${esc(__("Pieces"))}</label>
				<input id="tc-lin-qty-${esc(line.id)}" type="text" inputmode="numeric" autocomplete="off"
					data-field="qty" data-row="${esc(line.id)}" value="${esc(line.qty)}">
			</div>
			<div class="tc-field">
				<label for="tc-lin-kg-${esc(line.id)}">${esc(__("Weight (kg)"))}</label>
				<input id="tc-lin-kg-${esc(line.id)}" type="text" inputmode="decimal" autocomplete="off"
					data-field="weight_kg" data-row="${esc(line.id)}" value="${esc(line.weight)}">
			</div>
			<div class="tc-linen-hint" data-hint="${esc(line.id)}">${this.hintHtml(line, errors)}</div>
			<button type="button" class="tc-btn tc-btn-secondary" data-action="remove-line" data-row="${esc(
				line.id
			)}">${esc(__("Remove line"))}</button>
		</div>`;
	}

	// ---- người nhận ký (thẻ hoặc cảm ứng) ----
	signHtml() {
		const card = this.signMode === "Card";
		const mode = (value, label, on) =>
			`<button type="button" class="tc-btn tc-btn-${
				on ? "primary" : "secondary"
			}" data-action="sign-mode" data-mode="${value}">${esc(label)}</button>`;
		const hint = card
			? __("Recipient: scan the employee card. The card scan is the signature.")
			: __("Recipient: scan the employee card, then sign in the box.");
		return `<section class="tc-t6-block">
			<h3>${esc(__("Recipient signature"))}</h3>
			<div class="tc-actions" role="group" aria-label="${esc(__("Signature method"))}">
				${mode("Card", __("Sign with card"), card)}${mode("Touch", __("Sign on screen"), !card)}
			</div>
			<p class="tc-t6-hint">${esc(hint)}</p>
			${this.recipientCard ? this.padHtml() : ""}
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-secondary" data-action="back-form">${esc(
					__("Back to the issue")
				)}</button>
			</div>
		</section>`;
	}

	padHtml() {
		return `<div class="tc-t7-dialog" role="group" aria-label="${esc(__("Signature"))}">
			<canvas id="tc-lin-pad" class="tc-t7-pad" width="${LIN_PAD_WIDTH}" height="${LIN_PAD_HEIGHT}" aria-label="${esc(
			__("Signature box")
		)}"></canvas>
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="sign-confirm">${esc(
					__("Confirm signature")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="sign-clear">${esc(
					__("Clear")
				)}</button>
			</div>
		</div>`;
	}

	initPad() {
		const canvas = this.result.querySelector("#tc-lin-pad");
		if (!canvas) return;
		const ctx = canvas.getContext("2d");
		ctx.lineWidth = 3;
		ctx.lineCap = "round";
		ctx.strokeStyle = getComputedStyle(canvas).color;
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
		const canvas = this.result.querySelector("#tc-lin-pad");
		if (!canvas) return;
		canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
		this.strokes = 0;
	}

	doneHtml() {
		const done = this.done;
		const rows = done.lines
			.map(
				(row) => `<tr>
					<td>${esc(row.linen_type)}</td>
					<td>${esc(row.qty)}</td>
					<td>${esc(TcWeighLine.format(row.weight_kg))}</td>
				</tr>`
			)
			.join("");
		const warning = done.quota_warning
			? this.alertHtml({
					variant: "warn",
					title: __("Over the department quota"),
					reason: done.quota_warning,
					action: __("The warning is kept on the issue."),
			  })
			: "";
		return `<section class="tc-t6-block">
			${this.alertHtml({
				variant: "ok",
				title: __("Issue {0} recorded", [done.issue]),
				reason: __("{0} pieces, {1} kg to {2}, received by {3}.", [
					done.total_qty,
					TcWeighLine.format(done.total_weight_kg),
					done.department,
					done.recipient_name || done.recipient,
				]),
				action: __("Print the receipt for the recipient."),
			})}
			${warning}
			<table class="tc-t6-table">
				<thead><tr>
					<th scope="col">${esc(__("Linen Type"))}</th>
					<th scope="col">${esc(__("Pieces"))}</th>
					<th scope="col">${esc(__("Weight (kg)"))}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
			${this.balanceHtml()}
			<div class="tc-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="print">${esc(
					__("Print receipt")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="new-issue">${esc(
					__("New issue")
				)}</button>
			</div>
		</section>`;
	}
}
