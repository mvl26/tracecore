/* global TcFlow */
// Page tc-flow (A-158): giao diện người dùng cho luồng xử lý dụng cụ — trang chọn vai trò, rail trạm, stepper T1–T8.
// Khung này không tự ghi nghiệp vụ: thân mỗi trạm là màn của Page station (lớp TraceCoreStation nạp qua TcFlow.kit),
// nên phiên thẻ, kiểm năng lực, offline, X-Idempotency-Key và client_ts chạy đúng mã hiện có. Khung chỉ đọc thêm
// navigation.context (danh sách trạm), flow.departments / flow.department_stock (khoa, gói tại khoa) và trace.query.

const TCF_PANES = ["stock", "work", "trace"];

function tcfEsc(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

class TcFlowPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		$(wrapper).html(frappe.render_template("tc_flow", {}));
		this.root = wrapper.querySelector(".tcf");
		this.catalog = []; // trạm theo tài khoản đang đăng nhập
		this.catalogState = "loading";
		this.cardStations = null; // trạm theo thẻ đã quét
		this.host = null;
		this.Host = null;
		this.foreign = undefined; // instance của Page station đã mở trong cùng phiên: trả lại khi rời trang
		this.kitPromise = null;
		this.pane = "work";
		this.modeHint = null; // vai trò chọn ở trang đầu; mở thẳng bằng URL thì theo chức năng của trạm
		this.dept = null; // khoa đang mở ở cổng khoa: {name, label}
		this.departments = [];
		this.visible = false;
		this.entering = 0;
		this.root.addEventListener("click", (event) => this.onClick(event));
		this.root.addEventListener("submit", (event) => this.onSubmit(event));
		this.loadCatalog();
	}

	el(selector) {
		return this.root.querySelector(selector);
	}

	// ---- vòng đời Page ----
	show() {
		this.visible = true;
		document.body.classList.add("tcf-body");
		let code = TcFlow.stationParam(window.location.search);
		const department = TcFlow.departmentParam(window.location.search);
		// Page station mở sau trang này sẽ hủy instance trạm đang giữ (on_page_load của nó): quay lại thì mở lại trạm đó
		if (this.host && this.host.disposed) {
			code = code || this.host.station;
			this.host = null;
			this.cardStations = null;
			this.el(".tcf-host").innerHTML = "";
		}
		if (this.host) {
			this.adopt();
			this.view("app");
			this.setAddress(this.host.station);
			this.host.show();
			this.render();
		} else if (this.dept) {
			this.view("app");
			this.setAddress(null);
			this.render();
			if (this.pane === "stock") this.loadStock();
			else if (this.pane === "work") this.openUsage();
		} else if (department) this.enterDept({ name: department });
		else if (code) this.enter(code);
		else this.showLanding();
	}

	hide() {
		this.visible = false;
		document.body.classList.remove("tcf-body");
		if (!this.host) return;
		this.host.hide();
		if (frappe.tc_station === this.host) frappe.tc_station = this.foreign;
	}

	adopt() {
		if (frappe.tc_station === this.host) return;
		this.foreign = frappe.tc_station;
		frappe.tc_station = this.host;
	}

	view(name) {
		this.root.dataset.view = name;
		this.el(".tcf-landing").hidden = name !== "landing";
		this.el(".tcf-app").hidden = name !== "app";
	}

	setAddress(station) {
		const address = TcFlow.path(station, this.dept && this.dept.name);
		if (window.location.pathname + window.location.search !== address)
			window.history.replaceState(window.history.state, "", address);
	}

	async get(method, args) {
		const query = new URLSearchParams(args || {}).toString();
		const response = await fetch(`/api/method/${method}${query ? `?${query}` : ""}`, {
			headers: { Accept: "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token },
			credentials: "same-origin",
		});
		const body = await response.json().catch(() => ({}));
		if (!response.ok) {
			const error = new Error(method);
			error.status = response.status;
			throw error;
		}
		return body.message;
	}

	// lỗi chặn: alert inline theo thứ tự kết quả → lý do → hành động
	alertHtml(title, reason, action, retry) {
		const button = retry
			? `<button type="button" class="tcf-btn tcf-btn-secondary" data-action="${tcfEsc(
					retry
			  )}">${tcfEsc(__("Retry"))}</button>`
			: "";
		return `<div class="tcf-alert" role="alert">
			<p class="tcf-alert-title">${tcfEsc(title)}</p>
			<p class="tcf-alert-reason">${tcfEsc(reason)}</p>
			<p class="tcf-alert-action">${tcfEsc(action)}</p>
			${button}</div>`;
	}

	loadingHtml() {
		return `<p class="tcf-loading" aria-busy="true">${tcfEsc(__("Loading..."))}</p>`;
	}

	connectionReason(error) {
		if (!navigator.onLine)
			return (
				__("Offline", null, "TraceCore Launcher") +
				": " +
				__("No connection to the server.")
			);
		if (error && error.status === 403) return __("Your account is not allowed to open this.");
		return __("No connection to the server.");
	}

	// ---- trang chọn vai trò ----
	async loadCatalog() {
		this.catalogState = "loading";
		this.renderLanding();
		try {
			// khoa: tài khoản không có quyền cổng khoa thì thẻ khoa không có lựa chọn, trạm vẫn dùng được
			const [context, wards] = await Promise.all([
				this.get("tracecore.v1.navigation.context"),
				this.get("tracecore.v1.flow.departments").catch(() => null),
			]);
			this.catalog = (context && context.stations) || [];
			this.departments = (wards && wards.departments) || [];
			const known = this.dept && this.departments.find((row) => row.name === this.dept.name);
			if (known && !this.dept.label) this.dept.label = known.label;
			this.catalogState = "ready";
		} catch (error) {
			this.catalogState = "error";
			this.catalogError = this.connectionReason(error);
		}
		this.renderLanding();
		this.render();
	}

	showLanding() {
		this.view("landing");
		this.setAddress(null);
		document.title = `${__("Instrument reprocessing")} – TraceCore`;
		this.renderLanding();
	}

	renderLanding() {
		const status = this.el(".tcf-landing-status");
		if (this.catalogState === "loading") status.innerHTML = this.loadingHtml();
		else if (this.catalogState === "error")
			status.innerHTML = this.alertHtml(
				__("Could not load the station list"),
				this.catalogError,
				__("Check the connection and try again."),
				"tcf-catalog-retry"
			);
		else status.innerHTML = "";
		this.fillSelect(
			"ktv",
			TcFlow.ktvStations(this.catalog),
			__("No station for your account")
		);
		this.fillSelect("dept", this.departments, __("No department for your account"));
	}

	// ô chọn của thẻ vai trò: trạm (kỹ thuật viên) hoặc khoa (cổng khoa)
	fillSelect(mode, stations, none) {
		const select = this.el(`#tcf-${mode}-station`);
		const button = this.el(`[data-action="tcf-enter"][data-mode="${mode}"]`);
		const ready = this.catalogState === "ready";
		const empty = ready && !stations.length;
		select.innerHTML = empty
			? `<option value="">${tcfEsc(none)}</option>`
			: stations
					.map(
						(station) =>
							`<option value="${tcfEsc(station.name)}">${tcfEsc(
								TcFlow.stationLabel(station)
							)}</option>`
					)
					.join("");
		select.disabled = !ready || empty;
		button.disabled = !ready || empty;
	}

	// ---- mở trạm ----
	stationClass() {
		if (!this.kitPromise)
			this.kitPromise = (async () => {
				const loaded = TcFlow.globalStation();
				if (loaded) return loaded;
				await new Promise((resolve, reject) => {
					const request = frappe.views.pageview.with_page("station", resolve);
					if (request && typeof request.fail === "function")
						request.fail(() => reject(new Error("station")));
				});
				const doc = locals.Page && locals.Page.station;
				if (!doc) throw new Error("station");
				frappe.dom.set_style(doc.style || "", "tcf-station-style");
				return TcFlow.kit(doc.__script || doc.script || "").TraceCoreStation;
			})().catch((error) => {
				this.kitPromise = null;
				throw error;
			});
		return this.kitPromise;
	}

	shell() {
		const mine = (host) => !this.host || host === this.host;
		return {
			address: (station) => this.setAddress(station),
			applied: (host) => mine(host) && this.render(),
			replaced: (host) => {
				this.host = host;
				this.cardStations = null;
				this.decorate(host);
				this.render();
			},
			stations: (host, stations) => {
				if (!mine(host)) return;
				this.cardStations = host.session ? stations : null;
				this.render();
			},
			net: (host) => mine(host) && this.renderNet(host),
			session: (host) => {
				if (!mine(host)) return;
				if (!host.session) this.cardStations = null;
				// sử dụng ghi cho khoa của người quét thẻ: cổng khoa theo khoa của thẻ
				else if (
					this.dept &&
					host.session.department &&
					host.session.department !== this.dept.name
				) {
					this.dept = {
						name: host.session.department,
						label: host.session.department_name || host.session.department,
					};
					this.setAddress(host.station);
				}
				this.render();
				if (this.pane === "stock") this.loadStock();
			},
			covered: () => this.pane !== "work",
		};
	}

	async enter(code, mode) {
		if (mode) this.modeHint = mode;
		if (mode === "ktv") this.dept = null;
		const turn = ++this.entering;
		this.pane = "work";
		this.setAddress(code);
		this.view("app");
		this.el(".tcf-status").innerHTML = this.host ? "" : this.loadingHtml();
		this.render();
		let Base;
		try {
			Base = await this.stationClass();
		} catch (error) {
			if (turn !== this.entering) return;
			this.el(".tcf-status").innerHTML = this.alertHtml(
				__("Could not open the station"),
				this.connectionReason(error),
				__("Check the connection and try again."),
				"tcf-enter-retry"
			);
			return;
		}
		if (turn !== this.entering || !this.visible) return;
		this.el(".tcf-status").innerHTML = "";
		const barrier = this.host ? this.host.dispose() : Promise.resolve();
		if (!this.Host) this.Host = TcFlow.hostClass(Base, this.shell());
		if (frappe.tc_station !== this.host) this.foreign = frappe.tc_station;
		this.host = null;
		const host = new this.Host(this.el(".tcf-host"), barrier);
		this.host = host;
		frappe.tc_station = host;
		this.decorate(host);
		host.show();
		this.render();
	}

	// cổng khoa: chọn khoa là vào thẳng Gói tại khoa; màn T8 chỉ mở khi sang Quét sử dụng
	enterDept(department) {
		this.dept = this.departments.find((row) => row.name === department.name) || department;
		this.modeHint = "dept";
		this.entering += 1;
		this.pane = "stock";
		this.view("app");
		this.setAddress(this.host ? this.host.station : null);
		this.el(".tcf-status").innerHTML = "";
		document.title = `${__("Department portal")} – TraceCore`;
		this.render();
		this.loadStock();
	}

	openUsage() {
		const station = TcFlow.deptStations(this.catalog)[0];
		if (station) return this.enter(station.name, "dept");
		this.el(".tcf-status").innerHTML = this.alertHtml(
			__("Could not open the station"),
			__("No usage station for your account"),
			__("Ask the administrator to give your account a usage station."),
			this.catalogState === "ready" ? null : "tcf-catalog-retry"
		);
	}

	// breadcrumb và stepper nằm trong khung của trạm, đúng thứ tự: vạch khu → breadcrumb → tên trạm → stepper
	decorate(host) {
		const title = host.root.querySelector(".tc-title");
		if (!title || host.root.querySelector(".tcf-crumb")) return;
		const crumb = document.createElement("p");
		crumb.className = "tcf-crumb";
		title.before(crumb);
		const stepper = document.createElement("ol");
		stepper.className = "tcf-stepper";
		title.after(stepper);
	}

	async leave() {
		const host = this.host;
		this.entering += 1;
		this.host = null;
		this.dept = null;
		this.cardStations = null;
		this.pane = "work";
		if (host) {
			try {
				await host.endSession();
			} catch (error) {
				// khóa tại máy có hiệu lực ngay; máy chủ tự hết hạn phiên
			}
			host.dispose();
			if (frappe.tc_station === host) frappe.tc_station = this.foreign;
			this.el(".tcf-host").innerHTML = "";
		}
		this.showLanding();
	}

	// ---- khung: rail, breadcrumb, stepper ----
	stationInfo() {
		const host = this.host;
		const code = host ? host.station : TcFlow.stationParam(window.location.search);
		if (host && host.stationInfo) return host.stationInfo;
		return (
			this.catalog.find((station) => station.name === code) || (code ? { name: code } : null)
		);
	}

	mode() {
		if (this.dept) return "dept";
		// vào bằng thẻ kỹ thuật viên thì rail giữ đủ T1–T8 kể cả khi đang ở trạm sử dụng
		if (this.modeHint === "ktv") return "ktv";
		const info = this.stationInfo();
		return info && info.functions ? TcFlow.mode(info) : this.modeHint || "ktv";
	}

	railStations() {
		const flow = TcFlow.flowStations(this.catalog);
		if (!this.cardStations) return flow;
		const allowed = this.cardStations.map((station) => station.name);
		const byCard = flow.filter((station) => allowed.includes(station.name));
		if (byCard.length || flow.length) return byCard;
		return TcFlow.sorted(this.cardStations);
	}

	render() {
		if (this.root.dataset.view !== "app") return;
		const host = this.host;
		const info = this.stationInfo();
		const mode = this.mode();
		if (mode !== "dept") this.pane = "work";
		const session = host && host.session;
		const label = info ? TcFlow.stationLabel(info) : "";
		const name = this.el(".tcf-who-name");
		const role = this.el(".tcf-who-role");
		if (mode === "dept") {
			name.textContent =
				(this.dept && (this.dept.label || this.dept.name)) ||
				(session && session.department_name) ||
				label;
			role.textContent = [__("Department portal"), session && session.employee_name]
				.filter(Boolean)
				.join(" · ");
		} else {
			name.textContent = session
				? [session.employee_name, session.employee].filter(Boolean).join(" · ")
				: label;
			role.textContent = session ? label : __("Scan employee card");
		}
		this.renderNav(mode, info);
		this.renderCrumbs(mode, label);
		this.renderStepper(mode, info);
		if (host) this.renderNet(host);
		this.el(".tcf-host").hidden = this.pane !== "work";
		this.el(".tcf-stock").hidden = this.pane !== "stock";
		this.el(".tcf-trace").hidden = this.pane !== "trace";
	}

	paneLabel(pane) {
		if (pane === "stock") return __("Packs at the department");
		if (pane === "trace") return __("Trace a pack");
		return __("Scan usage");
	}

	renderNav(mode, info) {
		const nav = this.el(".tcf-nav");
		if (mode === "dept") {
			nav.innerHTML = TCF_PANES.map((pane) => {
				const current = pane === this.pane ? ' aria-current="page"' : "";
				return `<button type="button" class="tcf-nav-item" data-action="tcf-pane"
					data-pane="${pane}"${current}>${tcfEsc(this.paneLabel(pane))}</button>`;
			}).join("");
			return;
		}
		const stations = this.railStations();
		if (info && !stations.some((station) => station.name === info.name)) stations.push(info);
		nav.innerHTML = stations
			.map((station) => {
				const current = info && station.name === info.name ? ' aria-current="page"' : "";
				const text = TcFlow.stationLabel(station);
				return `<button type="button" class="tcf-nav-item" data-action="tcf-station"
					data-station="${tcfEsc(station.name)}" data-label="${tcfEsc(
					station.label || ""
				)}"${current}>${tcfEsc(text)}</button>`;
			})
			.join("");
	}

	renderCrumbs(mode, label) {
		const parts = [__("Home")];
		if (mode === "dept") parts.push(__("Department portal"), this.paneLabel(this.pane));
		else if (label) parts.push(label);
		const text = parts.join(" › ");
		for (const crumb of this.root.querySelectorAll(".tcf-crumb")) crumb.textContent = text;
	}

	// bước đã qua có dấu ✓ và chữ, bước hiện tại có aria-current: trạng thái không chỉ bằng màu
	renderStepper(mode, info) {
		const stepper = this.root.querySelector(".tcf-stepper");
		if (!stepper) return;
		const steps = mode === "dept" || !info ? [] : TcFlow.stepper(this.catalog, info.name);
		stepper.hidden = !steps.length;
		stepper.innerHTML = steps
			.map((step) => {
				const current = step.state === "current" ? ' aria-current="step"' : "";
				const mark =
					step.state === "done"
						? `<span class="tcf-step-mark" aria-hidden="true">✓</span><span class="tcf-sr">${tcfEsc(
								__("Done")
						  )}: </span>`
						: "";
				return `<li class="tcf-step" data-state="${step.state}"${current}>${mark}${tcfEsc(
					step.label
				)}</li>`;
			})
			.join("");
	}

	renderNet(host) {
		const source = host.root && host.root.querySelector(".tc-net-status");
		this.el(".tcf-net").textContent = source ? source.textContent : "";
	}

	// ---- cổng khoa ----
	setPane(pane) {
		if (!TCF_PANES.includes(pane) || this.mode() !== "dept") return;
		this.pane = pane;
		this.el(".tcf-status").innerHTML = "";
		this.render();
		if (pane === "stock") this.loadStock();
		else if (pane === "trace") this.el("#tcf-trace-input").focus();
		else if (this.host) this.host.focus(true);
		else this.openUsage();
	}

	async loadStock() {
		const box = this.el(".tcf-stock-body");
		const dept = this.dept;
		if (!dept) {
			box.innerHTML = `<p class="tcf-empty">${tcfEsc(
				__("Scan your employee card in Scan usage to see the packs at your department.")
			)}</p>
			<button type="button" class="tcf-btn" data-action="tcf-pane" data-pane="work">${tcfEsc(
				this.paneLabel("work")
			)}</button>`;
			return;
		}
		if (!navigator.onLine) {
			box.innerHTML = `<p class="tcf-empty tcf-offline">${tcfEsc(
				__("Offline: the list of packs at the department needs a connection.")
			)}</p>`;
			return;
		}
		const stale = () => dept.name !== (this.dept && this.dept.name) || this.pane !== "stock";
		box.innerHTML = this.loadingHtml();
		try {
			const result = await this.get("tracecore.v1.flow.department_stock", {
				department: dept.name,
			});
			if (stale()) return;
			if (this.dept && result.department_name) this.dept.label = result.department_name;
			box.innerHTML = this.stockHtml(result);
			this.render();
		} catch (error) {
			if (stale()) return;
			box.innerHTML = this.alertHtml(
				__("Could not load the packs at the department"),
				this.connectionReason(error),
				__("Check the connection and try again."),
				"tcf-stock-refresh"
			);
		}
	}

	stockHtml(overview) {
		const counts = TcFlow.stockCounts(overview);
		const day = (value) => (value ? frappe.datetime.str_to_user(value) : "");
		const kpi = (value, text, tone) =>
			`<div class="tcf-kpi" data-tone="${tone}"><b>${value}</b><small>${tcfEsc(
				text
			)}</small></div>`;
		const held = (overview.at_department || [])
			.map(
				(row) => `<tr>
					<td class="tcf-code">${tcfEsc(row.cycle_id)}</td>
					<td>${tcfEsc(row.set_name)}</td>
					<td>${tcfEsc(day(row.expiry))}</td>
					<td><span class="tcf-badge" data-tone="${row.expiring ? "warn" : "info"}">${tcfEsc(
					row.expiring ? __("Expiring soon") : __("Within shelf life")
				)}</span></td>
				</tr>`
			)
			.join("");
		const waiting = (overview.waiting_return || [])
			.map(
				(row) => `<tr>
					<td class="tcf-code">${tcfEsc(row.cycle_id)}</td>
					<td>${tcfEsc(row.set_name)}</td>
					<td>${tcfEsc(day(row.used_at))}</td>
				</tr>`
			)
			.join("");
		const table = (heading, columns, rows, empty) => `<section class="tcf-card">
			<h3>${tcfEsc(heading)}</h3>
			${
				rows
					? `<table class="tcf-table"><thead><tr>${columns
							.map((column) => `<th scope="col">${tcfEsc(column)}</th>`)
							.join("")}</tr></thead><tbody>${rows}</tbody></table>`
					: `<p class="tcf-empty">${tcfEsc(empty)}</p>`
			}
		</section>`;
		return `<div class="tcf-kpis">
				${kpi(counts.held, __("Packs at the department"), "pass")}
				${kpi(counts.expiring, __("Packs expiring soon"), "warn")}
				${kpi(counts.waiting, __("Used packs waiting to return to receiving"), "info")}
			</div>
			${table(
				overview.department_name
					? __("Packs at {0}", [overview.department_name])
					: __("Packs at the department"),
				[__("Cycle ID"), __("Set name"), __("Expiry"), __("Pack status")],
				held,
				__("No packs at the department.")
			)}
			${table(
				__("Used packs waiting to return to receiving"),
				[__("Cycle ID"), __("Set name"), __("Used at")],
				waiting,
				__("No used packs are waiting.")
			)}`;
	}

	async runTrace(raw) {
		const box = this.el(".tcf-trace-body");
		const code = String(raw || "").trim();
		if (!code) return;
		this.traceCode = code;
		box.innerHTML = this.loadingHtml();
		let result;
		try {
			result = await this.get("tracecore.v1.trace.query", TcFlow.traceArgs(code));
		} catch (error) {
			if (this.traceCode !== code) return;
			box.innerHTML = this.alertHtml(
				__("Could not trace this code"),
				this.connectionReason(error),
				__("Check the code and the connection, then scan again."),
				"tcf-trace-retry"
			);
			return;
		}
		if (this.traceCode !== code) return;
		const chains = (result && result.chains) || [];
		box.innerHTML = chains.length
			? chains.map((chain) => this.chainHtml(chain)).join("")
			: `<p class="tcf-empty">${tcfEsc(__("No pack found for this code."))}</p>`;
	}

	chainHtml(chain) {
		const when = (value) => (value ? frappe.datetime.str_to_user(value) : "");
		const rows = TcFlow.traceRows(chain)
			.map(
				(row) => `<tr>
					<td>${tcfEsc(when(row.at))}</td>
					<td>${tcfEsc(row.step)}</td>
					<td>${tcfEsc(row.detail)}</td>
					<td>${tcfEsc(row.who)}</td>
				</tr>`
			)
			.join("");
		const heading = [chain.cycle_id, chain.set_type].filter(Boolean).join(" — ");
		return `<section class="tcf-card">
			<h3><span class="tcf-code">${tcfEsc(heading)}</span> (<span class="tcf-code">${tcfEsc(
			chain.set_id
		)}</span>)</h3>
			<table class="tcf-table"><thead><tr>
				<th scope="col">${tcfEsc(__("Time"))}</th>
				<th scope="col">${tcfEsc(__("Station"))}</th>
				<th scope="col">${tcfEsc(__("Event"))}</th>
				<th scope="col">${tcfEsc(__("Person / machine"))}</th>
			</tr></thead><tbody>${rows}</tbody></table>
		</section>`;
	}

	// ---- thao tác ----
	onSubmit(event) {
		const form = event.target.closest(".tcf-trace .tcf-scan");
		if (!form) return;
		event.preventDefault();
		const input = this.el("#tcf-trace-input");
		this.runTrace(input.value);
		input.value = "";
		input.focus();
	}

	onClick(event) {
		const button = event.target.closest("[data-action^='tcf-']");
		if (!button || button.disabled) return;
		const action = button.dataset.action;
		if (action === "tcf-manage") window.location.assign("/app/tracecore");
		else if (action === "tcf-catalog-retry") this.loadCatalog();
		else if (action === "tcf-enter") {
			const code = this.el(`#tcf-${button.dataset.mode}-station`).value;
			if (code && button.dataset.mode === "dept") this.enterDept({ name: code });
			else if (code) this.enter(code, "ktv");
		} else if (action === "tcf-enter-retry") {
			const code = TcFlow.stationParam(window.location.search);
			if (code) this.enter(code);
			else if (this.dept) this.openUsage();
			else this.showLanding();
		} else if (action === "tcf-station") {
			if (this.host) this.host.switchStation(button.dataset.station, button.dataset.label);
		} else if (action === "tcf-pane") this.setPane(button.dataset.pane);
		else if (action === "tcf-stock-refresh") this.loadStock();
		else if (action === "tcf-trace-retry") this.runTrace(this.traceCode);
		else if (action === "tcf-logout") this.leave();
	}
}

frappe.pages["tc-flow"].on_page_load = function (wrapper) {
	frappe.tc_flow = new TcFlowPage(wrapper);
	// Frappe v15 không gọi on_page_hide của Page, chỉ phát sự kiện "hide" trên wrapper
	$(wrapper).on("hide", () => frappe.tc_flow.hide());
};

frappe.pages["tc-flow"].on_page_show = function () {
	if (frappe.tc_flow) frappe.tc_flow.show();
};
