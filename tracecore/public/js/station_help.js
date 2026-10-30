// Trợ giúp theo trạm (FEAT-013, FR-M9-15, A-56 D6, D9, D10): nút Trợ giúp ở thanh tiêu đề trạm mở modal §4.13 gồm
// hướng dẫn 3-5 bước có ảnh của bước trạm (tracecore.v1.help.get, cache localStorage để xem khi offline) và form
// "Báo sự cố" gửi phản hồi/báo lỗi kèm ảnh chụp màn hình tới R10 (tracecore.v1.feedback.create, @idempotent).
// Ảnh chụp bằng html2canvas để trong app (public/js/lib/html2canvas), nạp lười; ô mã bệnh nhân / PIN bị che trước khi
// chụp. Nối sau station.js qua hook page_js; TraceCoreStation gọi open() và chuyển data-action "help-*" vào onAction().
/* global uuid4, clientTs, esc */

const TC_HELP_GET = "tracecore.v1.help.get";
const TC_FEEDBACK_CREATE = "tracecore.v1.feedback.create";
const TC_HTML2CANVAS = "/assets/tracecore/js/lib/html2canvas/html2canvas.min.js";
const TC_HELP_TIMEOUT_MS = 8000;
// ô không được lọt vào ảnh chụp: mã bệnh nhân (T8), PIN, và mọi phần tử đánh dấu data-tc-mask
const TC_HELP_MASK = 'input[type="password"], [name="patient_code"], [data-tc-mask]';
const TC_SHOT_MAX_CHARS = 1900000; // data URL ~1,4 MB, dưới giới hạn 1,5 MB của server
const TC_SHOT_MAX_WIDTH = 1280;
const TC_FEEDBACK_MIN = 10;
const TC_FEEDBACK_MAX = 2000;

function tcMaskClone(doc) {
	for (const el of doc.querySelectorAll(TC_HELP_MASK)) {
		if ("value" in el) {
			el.value = "";
			el.setAttribute("value", "");
		} else {
			el.textContent = "•••";
		}
	}
}

class TcStationHelp {
	constructor(station) {
		this.station = station;
		this.overlay = null;
		this.view = "guide";
		this.state = "loading"; // loading | ready | empty | error | offline
		this.article = null;
		this.shot = null;
		this.capturing = null;
		this.form = { kind: "Bug", text: "", attach: true };
		this.error = null;
		this.sent = null;
		this.busy = false;
		this.key = null;
	}

	get isOpen() {
		return Boolean(this.overlay);
	}

	cacheKey() {
		return `tc-station-help:${this.station.station}`;
	}

	cached(value) {
		try {
			if (value === undefined) {
				const raw = localStorage.getItem(this.cacheKey());
				return raw ? JSON.parse(raw) : null;
			}
			localStorage.setItem(this.cacheKey(), JSON.stringify(value));
		} catch (error) {
			/* bộ nhớ trình duyệt tắt hoặc đầy: vẫn xem được khi online */
		}
		return null;
	}

	open() {
		if (this.overlay) return;
		this.view = "guide";
		this.error = null;
		this.sent = null;
		this.shot = null;
		// chụp màn trạm trước khi modal hiện; modal bị loại khỏi ảnh bằng ignoreElements
		this.capturing = this.capture().then((shot) => {
			this.shot = shot;
			this.capturing = null;
			if (this.overlay && this.view === "report") this.render();
		});
		const overlay = document.createElement("div");
		overlay.className = "tc-modal tc-help-modal";
		overlay.addEventListener("keydown", (event) => this.onKey(event));
		overlay.addEventListener("submit", (event) => {
			event.preventDefault();
			this.send();
		});
		overlay.addEventListener("input", (event) => this.onInput(event.target));
		overlay.addEventListener("change", (event) => this.onInput(event.target));
		this.overlay = overlay;
		this.station.root.appendChild(overlay);
		this.render();
		this.load();
	}

	close() {
		if (!this.overlay) return;
		this.overlay.remove();
		this.overlay = null;
		this.busy = false;
		this.station.focus(true);
	}

	// phiên thẻ đổi (đăng xuất, quét thẻ khác): bỏ nội dung đang soạn
	sessionChanged() {
		this.form = { kind: "Bug", text: "", attach: true };
		this.key = null;
		if (this.overlay && this.view === "report") this.render();
	}

	onAction(action) {
		if (!action.startsWith("help-")) return false;
		if (action === "help-close") this.close();
		else if (action === "help-report") this.show("report");
		else if (action === "help-back") this.show("guide");
		else if (action === "help-retry") this.load();
		return true;
	}

	show(view) {
		this.view = view;
		this.error = null;
		this.sent = null;
		this.render();
	}

	onKey(event) {
		if (event.key === "Escape") {
			event.preventDefault();
			return this.close();
		}
		if (event.key !== "Tab") return;
		const items = [
			...this.overlay.querySelectorAll("input, textarea, button:not([disabled])"),
		];
		if (!items.length) return;
		const edge = event.shiftKey ? items[0] : items[items.length - 1];
		if (document.activeElement === edge) {
			event.preventDefault();
			(event.shiftKey ? items[items.length - 1] : items[0]).focus();
		}
	}

	onInput(target) {
		if (target.name === "tc_help_kind") this.form.kind = target.value;
		else if (target.name === "tc_help_text") {
			this.form.text = target.value;
			const counter = this.overlay.querySelector(".tc-help-count");
			if (counter) counter.textContent = `${target.value.trim().length}/${TC_FEEDBACK_MAX}`;
		} else if (target.name === "tc_help_attach") this.form.attach = target.checked;
	}

	async load() {
		const saved = this.cached();
		if (this.station.isOffline()) {
			this.article = saved;
			this.state = "offline";
			return this.render();
		}
		this.state = "loading";
		this.render();
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), TC_HELP_TIMEOUT_MS);
		try {
			const query = new URLSearchParams({ station: this.station.station || "" });
			const response = await fetch(`/api/method/${TC_HELP_GET}?${query}`, {
				headers: { Accept: "application/json" },
				credentials: "same-origin",
				signal: controller.signal,
			});
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			const data = (await response.json()).message || {};
			this.article = data.article || null;
			this.state = this.article && this.article.steps.length ? "ready" : "empty";
			if (this.article) this.cached(this.article);
		} catch (error) {
			const offline = error.name === "AbortError" || error instanceof TypeError;
			this.article = saved;
			this.state = offline ? "offline" : "error";
		} finally {
			clearTimeout(timer);
		}
		if (this.overlay) this.render();
	}

	async capture() {
		try {
			if (!window.html2canvas) await frappe.require(TC_HTML2CANVAS);
			const root = this.station.root;
			const canvas = await window.html2canvas(root, {
				logging: false,
				scale: Math.min(1, TC_SHOT_MAX_WIDTH / Math.max(root.offsetWidth, 1)),
				ignoreElements: (el) => el.classList && el.classList.contains("tc-help-modal"),
				onclone: tcMaskClone,
			});
			let url = canvas.toDataURL("image/jpeg", 0.7);
			if (url.length > TC_SHOT_MAX_CHARS) url = canvas.toDataURL("image/jpeg", 0.4);
			return url.length > TC_SHOT_MAX_CHARS ? null : url;
		} catch (error) {
			return null; // không chụp được (thư viện chưa tải khi offline…): vẫn gửi phản hồi không ảnh
		}
	}

	context() {
		const info = this.station.stationInfo || {};
		const alert = this.station.result && this.station.result.querySelector(".tc-alert-title");
		return {
			screen: info.step || info.zone_type || "",
			step: this.station.result ? this.station.result.dataset.state || "" : "",
			online: !this.station.isOffline(),
			last_error: alert ? alert.textContent.trim() : "",
			app_version:
				(frappe.boot && frappe.boot.versions && frappe.boot.versions.tracecore) || "",
			user_agent: navigator.userAgent,
			viewport: `${window.innerWidth}x${window.innerHeight}`,
		};
	}

	async send() {
		if (this.busy || !this.station.session || this.station.isOffline()) return;
		const text = this.form.text.trim();
		if (text.length < TC_FEEDBACK_MIN || text.length > TC_FEEDBACK_MAX) {
			this.error = {
				title: __("Feedback not sent"),
				reason: __("The description must have {0} to {1} characters.", [
					TC_FEEDBACK_MIN,
					TC_FEEDBACK_MAX,
				]),
				action: __("Describe what you did and what went wrong."),
			};
			return this.render();
		}
		this.busy = true;
		this.error = null;
		this.render();
		// cùng khóa cho lần gửi lại sau lỗi mạng: server không tạo Issue thứ hai (ADR-003)
		this.key = this.key || uuid4();
		try {
			const result = await this.station.rpc(
				TC_FEEDBACK_CREATE,
				{
					station: this.station.station,
					kind: this.form.kind,
					description: text,
					screenshot: this.form.attach ? this.shot : null,
					context: this.context(),
					client_ts: clientTs(),
				},
				this.key
			);
			if (result && result.ok) {
				this.sent = result.issue;
				this.form = { kind: "Bug", text: "", attach: true };
				this.key = null;
			} else {
				this.error = result && result.error;
				this.key = null;
			}
		} catch (error) {
			if (error.sessionEnded) return this.close();
			this.error = error.offline
				? {
						title: __("Feedback not sent"),
						reason: __("The station lost the network connection."),
						action: __("Reconnect, then press Send again."),
				  }
				: {
						title: __("Feedback not sent"),
						reason: __("The server could not save the report."),
						action: __("Press Send again or tell R10 directly."),
				  };
		} finally {
			this.busy = false;
		}
		if (this.overlay) this.render();
	}

	alertHtml(kind, block) {
		const icon = kind === "error" ? "&#10005;" : kind === "ok" ? "&#10003;" : "!";
		return `<div class="tc-alert tc-alert-${kind}" role="${
			kind === "error" ? "alert" : "status"
		}">
			<p class="tc-alert-title"><span aria-hidden="true">${icon}</span> ${esc(block.title)}</p>
			${block.reason ? `<p class="tc-alert-reason">${esc(block.reason)}</p>` : ""}
			${block.action ? `<p class="tc-alert-action">${esc(block.action)}</p>` : ""}
		</div>`;
	}

	stepsHtml() {
		const steps = (this.article && this.article.steps) || [];
		return `<ol class="tc-help-steps">${steps
			.map(
				(step, index) => `<li class="tc-help-step">
					<span class="tc-help-num" aria-hidden="true">${index + 1}</span>
					<div class="tc-help-body">
						<p>${esc(step.text)}</p>
						${
							step.image
								? `<img src="${esc(step.image)}" alt="${esc(
										__("Step {0}", [index + 1])
								  )}" loading="lazy">`
								: ""
						}
					</div>
				</li>`
			)
			.join("")}</ol>`;
	}

	guideHtml() {
		const title = this.article ? this.article.title : __("Station guide");
		let notice = "";
		if (this.state === "loading")
			notice = `<p class="tc-help-state" role="status">${esc(__("Loading the guide…"))}</p>`;
		else if (this.state === "empty")
			notice = this.alertHtml("info", {
				title: __("No guide for this station yet"),
				action: __("Ask R10 to add the steps for this station."),
			});
		else if (this.state === "error")
			notice = this.alertHtml("error", {
				title: __("Cannot load the guide"),
				reason: __("The server did not answer as expected."),
				action: __("Press Try again or ask R02 at this station."),
			});
		else if (this.state === "offline")
			notice = this.alertHtml("warn", {
				title: this.article
					? __("Offline - showing the saved guide")
					: __("Offline - no saved guide"),
				action: this.article ? "" : __("Reconnect to load the guide."),
			});
		const retry =
			this.state === "error" || (this.state === "offline" && !this.article)
				? `<button type="button" class="tc-btn tc-btn-secondary" data-action="help-retry">${esc(
						__("Try again")
				  )}</button>`
				: "";
		return `<h3 id="tc-help-title">${esc(title)}</h3>
			${notice}
			${this.state === "loading" ? "" : this.stepsHtml()}
			<div class="tc-modal-actions">
				<button type="button" class="tc-btn tc-btn-primary" data-action="help-close">${esc(
					__("Close")
				)}</button>
				<button type="button" class="tc-btn tc-btn-secondary" data-action="help-report">${esc(
					__("Report a problem")
				)}</button>
				${retry}
			</div>`;
	}

	reportHtml() {
		const offline = this.station.isOffline();
		const session = Boolean(this.station.session);
		let notice = "";
		if (this.sent)
			notice = this.alertHtml("ok", {
				title: __("Feedback sent"),
				reason: __("R10 received report {0}.", [this.sent]),
			});
		else if (!session)
			notice = this.alertHtml("warn", {
				title: __("Scan your employee card first"),
				reason: __("Feedback is sent under your name."),
				action: __("Close Help and scan your card."),
			});
		else if (offline)
			notice = this.alertHtml("warn", {
				title: __("Feedback needs the network"),
				action: __("Reconnect, then send the report."),
			});
		if (this.error) notice += this.alertHtml("error", this.error);
		const disabled = this.busy || offline || !session ? " disabled" : "";
		const kind = (value, label) => `<label class="tc-help-kind">
				<input type="radio" name="tc_help_kind" value="${value}"${
			this.form.kind === value ? " checked" : ""
		}> ${esc(label)}</label>`;
		let shot = `<p class="tc-help-state">${esc(__("Taking the screenshot…"))}</p>`;
		if (!this.capturing)
			shot = this.shot
				? `<label class="tc-help-attach"><input type="checkbox" name="tc_help_attach"${
						this.form.attach ? " checked" : ""
				  }> ${esc(__("Attach screenshot"))}</label>
				<img class="tc-help-shot" src="${esc(this.shot)}" alt="${esc(__("Screenshot preview"))}">`
				: `<p class="tc-help-state">${esc(__("Screenshot not available"))}</p>`;
		return `<h3 id="tc-help-title">${esc(__("Report a problem"))}</h3>
			${notice}
			<form class="tc-modal-form" novalidate>
				<fieldset class="tc-help-kinds">
					<legend>${esc(__("Type"))}</legend>
					${kind("Bug", __("Something does not work"))}
					${kind("Suggestion", __("Suggestion"))}
				</fieldset>
				<div class="tc-field">
					<label for="tc-help-text">${esc(__("What happened?"))}</label>
					<textarea id="tc-help-text" name="tc_help_text" rows="4" maxlength="${TC_FEEDBACK_MAX}">${esc(
			this.form.text
		)}</textarea>
					<p class="tc-help-count">${this.form.text.trim().length}/${TC_FEEDBACK_MAX}</p>
				</div>
				${shot}
				<div class="tc-modal-actions">
					<button type="submit" class="tc-btn tc-btn-primary"${disabled}>${esc(
			this.busy ? __("Sending…") : __("Send to R10")
		)}</button>
					<button type="button" class="tc-btn tc-btn-secondary" data-action="help-back">${esc(
						__("Back to the guide")
					)}</button>
				</div>
			</form>`;
	}

	render() {
		if (!this.overlay) return;
		this.overlay.innerHTML = `<div class="tc-modal-box tc-help-box" role="dialog" aria-modal="true"
			aria-labelledby="tc-help-title" data-state="${this.state}" data-view="${this.view}">
			${this.view === "report" ? this.reportHtml() : this.guideHtml()}
		</div>`;
		const first =
			this.view === "report"
				? this.overlay.querySelector("textarea")
				: this.overlay.querySelector(".tc-modal-actions .tc-btn");
		if (first) first.focus({ preventScroll: true });
	}
}
