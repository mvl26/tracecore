/* global TcFlow, TcFlowLead */
// Page tc-flow (A-158): giao diện người dùng cho luồng xử lý dụng cụ — trang chọn vai trò, rail trạm, stepper T1–T8.
// Khung này không tự ghi nghiệp vụ: thân mỗi trạm là màn của Page station (lớp TraceCoreStation nạp qua TcFlow.kit),
// nên phiên thẻ, kiểm năng lực, offline, X-Idempotency-Key và client_ts chạy đúng mã hiện có. Khung chỉ đọc thêm
// navigation.context (danh sách trạm), flow.departments / flow.department_stock (khoa, gói tại khoa) và trace.query.

const TCF_PANES = ["stock", "work", "return", "issue", "recall", "linen", "trace"];
// mục chỉ đọc/gửi của cổng khoa nạp dữ liệu khi mở: tên mục → hàm nạp
const TCF_PANE_LOADERS = {
	stock: "loadStock",
	return: "loadReturn",
	issue: "loadIssue",
	recall: "loadRecall",
	linen: "loadLinen",
};

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
		this.modules = []; // phân hệ quản lý của tài khoản (navigation.context)
		this.manage = null; // key phân hệ đang mở ở không gian quản lý
		this.manageLink = null;
		this.lead = null; // mục đang mở của khu Trưởng khoa KSNK (FEAT-102)
		this.visible = false;
		this.entering = 0;
		this.root.addEventListener("click", (event) => this.onClick(event));
		this.root.addEventListener("submit", (event) => this.onSubmit(event));
		this.root.addEventListener("change", (event) => this.onChange(event));
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
		const manage = TcFlow.manageParam(window.location.search);
		if (this.manage || manage) return this.enterManage(this.manage || manage, this.manageLink);
		const lead = TcFlow.leadParam(window.location.search);
		if (this.lead || lead) return this.enterLead(this.lead || lead);
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
			if (TCF_PANE_LOADERS[this.pane]) this[TCF_PANE_LOADERS[this.pane]]();
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
		const address = TcFlow.path(station, this.dept && this.dept.name, this.manage, this.lead);
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

	// RPC ghi của cổng khoa: X-Idempotency-Key do người gọi giữ để gửi lại đúng khóa cũ
	async post(method, args, key) {
		const response = await fetch(`/api/method/${method}`, {
			method: "POST",
			headers: {
				Accept: "application/json",
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": frappe.csrf_token,
				"X-Idempotency-Key": key,
			},
			credentials: "same-origin",
			body: JSON.stringify(args),
		});
		const body = await response.json().catch(() => ({}));
		if (!response.ok) {
			const error = new Error(method);
			error.status = response.status;
			error.body = body.message || null; // RPC cũ trả từ chối nghiệp vụ kèm mã HTTP 4xx
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
			const admin = (context && context.admin_modules) || [];
			this.modules = admin.length ? admin : (context && context.role_modules) || [];
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
		this.lead = null;
		this.manage = null;
		this.manageLink = null;
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
		this.manage = null;
		this.lead = null;
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
		this.manage = null;
		this.lead = null;
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
		if (this.manage) return "manage";
		if (this.lead) return "lead";
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
		if (this.manage) return this.renderManage();
		if (this.lead) return this.renderLead();
		this.el(".tcf-manage").hidden = true;
		this.el(".tcf-lead").hidden = true;
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
		this.el(".tcf-return").hidden = this.pane !== "return";
		this.el(".tcf-issue").hidden = this.pane !== "issue";
		this.el(".tcf-recall").hidden = this.pane !== "recall";
		this.el(".tcf-linen").hidden = this.pane !== "linen";
		this.el(".tcf-trace").hidden = this.pane !== "trace";
	}

	paneLabel(pane) {
		if (pane === "stock") return __("Sets at department & par level");
		if (pane === "trace") return __("Trace a pack");
		if (pane === "return") return __("Return dirty sets");
		if (pane === "issue") return __("Request sets");
		if (pane === "recall") return __("Confirm recall");
		if (pane === "linen") return __("Linen received");
		return __("Scan usage");
	}

	renderNav(mode, info) {
		const nav = this.el(".tcf-nav");
		if (mode === "dept") {
			nav.innerHTML = TCF_PANES.map((pane) => {
				const current = pane === this.pane ? ' aria-current="page"' : "";
				return `<button type="button" class="tcf-nav-item" data-action="tcf-pane"
					data-pane="${pane}"${current}>${tcfEsc(this.paneLabel(pane))}${this.paneBadge(pane)}</button>`;
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
		if (TCF_PANE_LOADERS[pane]) this[TCF_PANE_LOADERS[pane]]();
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
			this.recallPending = TcFlow.stockCounts(result).recall;
			this.render();
			this.countUp(box);
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

	// Mở màn: các số chạy từ 0 tới giá trị thật trong TcFlow.COUNT_MS; người dùng tắt chuyển động thì giữ nguyên số thật
	countUp(box) {
		cancelAnimationFrame(this.countFrame);
		const items = Array.from(box.querySelectorAll("[data-count]"));
		const reduced =
			window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
		if (!items.length || reduced) return;
		const targets = items.map((item) => Number(item.dataset.count));
		// ô tiền (data-format="vnd") chạy số rồi mới định dạng VND
		const paint = (progress) =>
			items.forEach((item, index) => {
				const value = TcFlow.countAt(targets[index], progress);
				item.textContent = item.dataset.format === "vnd" ? TcFlow.vnd(value) : value;
			});
		const started = performance.now();
		const tick = (now) => {
			const progress = (now - started) / TcFlow.COUNT_MS;
			paint(progress);
			if (progress < 1) this.countFrame = requestAnimationFrame(tick);
		};
		paint(0);
		this.countFrame = requestAnimationFrame(tick);
	}

	// Bộ tại khoa và cơ số: 4 ô số liệu rồi danh sách bộ đang ở khoa (Cycle ID, Set ID, loại bộ, hạn dùng, trạng thái)
	stockHtml(overview) {
		const counts = TcFlow.stockCounts(overview);
		const day = (value) => (value ? frappe.datetime.str_to_user(value) : "");
		const kpi = (value, text, tone) =>
			`<div class="tcf-kpi" data-tone="${tone}"><b data-count="${value}">${value}</b><small>${tcfEsc(
				text
			)}</small></div>`;
		const heldLabel = counts.par
			? __("Sets at the department · par level {0}–{1}", counts.par)
			: __("Sets at the department · no par level set");
		const held = (overview.at_department || [])
			.map((row, index) => {
				const expiring = row.expiring
					? ` <span class="tcf-badge" data-tone="warn">${tcfEsc(
							__("Expiring soon")
					  )}</span>`
					: "";
				return `<tr style="--tcf-i: ${Math.min(index, 12)}">
					<td class="tcf-code">${tcfEsc(row.cycle_id)}</td>
					<td class="tcf-code">${tcfEsc(row.set_id)}</td>
					<td>${tcfEsc(row.set_name || row.set_type)}</td>
					<td>${tcfEsc(day(row.expiry))}</td>
					<td><span class="tcf-badge">${tcfEsc(__("Issued", null, "Pack"))}</span>${expiring}</td>
				</tr>`;
			})
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
				${kpi(counts.held, heldLabel, "pass")}
				${kpi(counts.reprocessing, __("Sets of the department being reprocessed at CSSD"), "info")}
				${kpi(counts.recall, __("Packs to confirm for recall"), "warn")}
				${kpi(counts.waiting, __("Dirty returns waiting for CSSD pickup"), "info")}
			</div>
			${table(
				__("Sets currently at the department"),
				[__("Cycle ID"), __("Set ID"), __("Set type"), __("Expiry"), __("Pack status")],
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

	// ---- Gửi trả đồ bẩn về KSNK (FEAT-100, A-160): bộ có thể trả, gửi yêu cầu, yêu cầu đã gửi hôm nay ----
	async loadReturn() {
		const box = this.el(".tcf-return-body");
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
				__("Offline: sending a pickup request needs a connection.")
			)}</p>`;
			return;
		}
		const stale = () => dept.name !== (this.dept && this.dept.name) || this.pane !== "return";
		box.innerHTML = this.loadingHtml();
		try {
			const result = await this.get("tracecore.v1.flow.return_overview", {
				department: dept.name,
			});
			if (stale()) return;
			box.innerHTML = this.returnHtml(result);
		} catch (error) {
			if (stale()) return;
			box.innerHTML = this.alertHtml(
				__("Could not load the sets that can be returned"),
				this.connectionReason(error),
				__("Check the connection and try again."),
				"tcf-return-refresh"
			);
		}
	}

	returnHtml(data, notice) {
		const conditions = data.conditions || [];
		const options = conditions
			.map(
				(value) =>
					`<option value="${tcfEsc(value)}">${tcfEsc(
						__(value, null, "Dirty Return")
					)}</option>`
			)
			.join("");
		const rows = (data.candidates || [])
			.map((row) => {
				const state = row.used
					? `<span class="tcf-badge">${tcfEsc(__("Used", null, "Pack"))}</span> ${tcfEsc(
							__("waiting to be returned")
					  )}`
					: `<span class="tcf-badge">${tcfEsc(
							__("At department", null, "Dirty Return")
					  )}</span> ${tcfEsc(__("not used: it will count as returned unused"))}`;
				return `<tr data-set="${tcfEsc(row.set_id)}">
					<td class="tcf-check-cell"><input type="checkbox" class="tcf-check" aria-label="${tcfEsc(
						__("Choose set {0}", [row.set_id])
					)}" /></td>
					<td class="tcf-code">${tcfEsc(row.set_id)}</td>
					<td>${tcfEsc(row.set_name || row.set_type)}</td>
					<td>${state}</td>
					<td><select class="tcf-select tcf-return-condition" aria-label="${tcfEsc(
						__("Condition on return of set {0}", [row.set_id])
					)}">${options}</select></td>
				</tr>`;
			})
			.join("");
		const time = (value) => (value ? frappe.datetime.str_to_user(value) : "");
		// mỗi bộ đã gửi một dòng (theo Set ID), mới gửi trước; trạng thái theo từng bộ
		const sent = (data.sent_sets || [])
			.map((row) => {
				const status = row.received ? "Received" : "Waiting";
				return `<tr>
					<td class="tcf-code">${tcfEsc(row.set_id)}</td>
					<td>${tcfEsc(row.set_name || row.set_type)}</td>
					<td>${tcfEsc(__(row.condition, null, "Dirty Return"))}</td>
					<td>${tcfEsc(time(row.requested_at))}</td>
					<td>${tcfEsc(row.requested_by_name)}</td>
					<td><span class="tcf-badge" data-tone="${TcFlow.returnTone(status)}">${tcfEsc(
					row.received ? __("Received at T1") : __("Waiting for CSSD pickup")
				)}</span></td>
				</tr>`;
			})
			.join("");
		const head = (columns) =>
			`<thead><tr>${columns
				.map((column) => `<th scope="col">${tcfEsc(column)}</th>`)
				.join("")}</tr></thead>`;
		const done = notice ? `<p class="tcf-done" role="status">${tcfEsc(notice)}</p>` : "";
		return `<section class="tcf-card">
				<h3>${tcfEsc(__("Sets that can be returned"))}</h3>
				${done}
				<div class="tcf-return-alert"></div>
				${
					rows
						? `<table class="tcf-table">${head([
								__("Choose"),
								__("Set ID"),
								__("Set type"),
								__("Status"),
								__("Condition on return"),
						  ])}<tbody>${rows}</tbody></table>
						<button type="button" class="tcf-btn tcf-return-send" data-action="tcf-return-send">${tcfEsc(
							__("Send pickup request")
						)}</button>`
						: `<p class="tcf-empty">${tcfEsc(
								__("No set of the department is waiting to be returned.")
						  )}</p>`
				}
				<p class="tcf-note">${tcfEsc(
					__(
						"The request is only a notice; the set status changes only when the technician scans it at receiving T1 (BRU-FLOW-003)."
					)
				)}</p>
			</section>
			<section class="tcf-card">
				<h3>${tcfEsc(__("Requests sent today"))}</h3>
				${
					sent
						? `<table class="tcf-table">${head([
								__("Set ID"),
								__("Set type"),
								__("Condition on return"),
								__("Sent at"),
								__("Sent by"),
								__("Status"),
						  ])}<tbody>${sent}</tbody></table>`
						: `<p class="tcf-empty">${tcfEsc(__("No request was sent today."))}</p>`
				}
			</section>`;
	}

	returnAlert(title, reason, action) {
		const slot = this.el(".tcf-return-alert");
		if (slot) slot.innerHTML = title ? this.alertHtml(title, reason, action) : "";
	}

	async sendReturn() {
		const box = this.el(".tcf-return-body");
		const dept = this.dept;
		if (!dept || this.returnSending) return;
		const failed = __("The pickup request was not sent");
		const items = Array.from(box.querySelectorAll("tr[data-set]"))
			.filter((row) => row.querySelector(".tcf-check").checked)
			.map((row) => ({
				set_id: row.dataset.set,
				condition: row.querySelector(".tcf-return-condition").value,
			}));
		if (!items.length) {
			this.returnAlert(
				failed,
				__("No set was chosen."),
				__("Tick at least one set, then send the request again.")
			);
			return;
		}
		if (!navigator.onLine) {
			this.returnAlert(
				failed,
				__("Offline", null, "TraceCore Launcher") +
					": " +
					__("No connection to the server."),
				__("Check the connection and try again.")
			);
			return;
		}
		// gửi lại cùng lựa chọn sau lỗi mạng: dùng lại khóa và nội dung cũ để máy chủ không tạo yêu cầu thứ hai
		const fingerprint = JSON.stringify([dept.name, items]);
		if (!this.returnAttempt || this.returnAttempt.fingerprint !== fingerprint)
			this.returnAttempt = {
				fingerprint,
				key: TcFlow.uuid(),
				body: {
					department: dept.name,
					items: JSON.stringify(items),
					client_ts: TcFlow.clientTs(),
				},
			};
		const attempt = this.returnAttempt;
		const button = box.querySelector(".tcf-return-send");
		this.returnSending = true;
		if (button) button.disabled = true;
		this.returnAlert();
		try {
			const result = await this.post(
				"tracecore.v1.flow.request_return",
				attempt.body,
				attempt.key
			);
			this.returnAttempt = null;
			if (dept.name !== (this.dept && this.dept.name)) return;
			if (!result || !result.ok) {
				const error = (result && result.error) || {};
				this.returnAlert(
					error.title || failed,
					error.reason || "",
					error.action || __("Refresh the list and choose again.")
				);
				return;
			}
			box.innerHTML = this.returnHtml(
				result,
				__("Request {0} was sent for {1} sets.", [result.request, result.set_count])
			);
		} catch (error) {
			this.returnAlert(
				failed,
				this.connectionReason(error),
				__("Check the connection and send the request again.")
			);
		} finally {
			this.returnSending = false;
			const again = box.querySelector(".tcf-return-send");
			if (again) again.disabled = false;
		}
	}

	// ---- FEAT-101 (A-161): Đề nghị cấp, Xác nhận thu hồi, Đồ vải đã nhận ----
	// nạp một mục chỉ đọc của cổng khoa: đủ empty (chưa có khoa) / offline / loading / error; trả dữ liệu hoặc null
	async loadDeptPane(pane, method, render, failTitle) {
		const box = this.el(`.tcf-${pane}-body`);
		const dept = this.dept;
		if (!dept) {
			box.innerHTML = `<p class="tcf-empty">${tcfEsc(
				__("Scan your employee card in Scan usage to see the packs at your department.")
			)}</p>
			<button type="button" class="tcf-btn" data-action="tcf-pane" data-pane="work">${tcfEsc(
				this.paneLabel("work")
			)}</button>`;
			return null;
		}
		if (!navigator.onLine) {
			box.innerHTML = `<p class="tcf-empty tcf-offline">${tcfEsc(
				__("Offline: this page needs a connection.")
			)}</p>`;
			return null;
		}
		const stale = () => dept.name !== (this.dept && this.dept.name) || this.pane !== pane;
		box.innerHTML = this.loadingHtml();
		try {
			const result = await this.get(method, { department: dept.name });
			if (stale()) return null;
			box.innerHTML = render(result);
			return result;
		} catch (error) {
			if (stale()) return null;
			box.innerHTML = this.alertHtml(
				failTitle,
				this.connectionReason(error),
				__("Check the connection and try again."),
				`tcf-${pane}-refresh`
			);
			return null;
		}
	}

	paneAlert(pane, title, reason, action) {
		const slot = this.el(`.tcf-${pane}-alert`);
		if (slot) slot.innerHTML = title ? this.alertHtml(title, reason, action) : "";
	}

	tableHead(columns) {
		return `<thead><tr>${columns
			.map((column) => `<th scope="col">${tcfEsc(column)}</th>`)
			.join("")}</tr></thead>`;
	}

	// số gói chờ xác nhận thu hồi ở thanh bên: có số và chữ cho trình đọc màn hình
	paneBadge(pane) {
		if (pane !== "recall" || !this.recallPending) return "";
		return ` <span class="tcf-nav-badge">${tcfEsc(
			this.recallPending
		)}<span class="tcf-sr"> ${tcfEsc(__("packs waiting for confirmation"))}</span></span>`;
	}

	// ---- Xác nhận thu hồi ----
	async loadRecall() {
		const result = await this.loadDeptPane(
			"recall",
			"tracecore.v1.flow.recall_overview",
			(data) => this.recallHtml(data),
			__("Could not load the recall orders")
		);
		if (result) {
			this.recallPending = result.pending || 0;
			this.renderNav("dept");
		}
	}

	recallHtml(data) {
		const time = (value) => (value ? frappe.datetime.str_to_user(value) : "");
		const orders = (data.orders || [])
			.map((order) => {
				const rows = order.lines
					.map((line) => {
						const state = [
							__(line.status_at_recall || "", null, "Pack"),
							line.patient_code_masked,
						]
							.filter(Boolean)
							.join(" · ");
						const label =
							line.action === "Notify Physician"
								? __("Confirm the physician was informed")
								: __("Confirm the pack was found");
						const cell = line.confirmed
							? `<span class="tcf-badge" data-tone="pass">${tcfEsc(
									__("Confirmed", null, "Recall")
							  )}</span> ${tcfEsc(
									[line.confirmed_by, time(line.confirmed_at)]
										.filter(Boolean)
										.join(" · ")
							  )}`
							: `<button type="button" class="tcf-btn" data-action="tcf-recall-confirm"
								data-recall="${tcfEsc(order.recall)}" data-pack="${tcfEsc(line.cycle_id)}">${tcfEsc(
									label
							  )}</button>`;
						return `<tr>
							<td class="tcf-code">${tcfEsc(line.cycle_id)}</td>
							<td>${tcfEsc(state)}</td>
							<td>${cell}</td>
						</tr>`;
					})
					.join("");
				return `<div class="tcf-recall-note" role="note"><b>${tcfEsc(
					__("Recall order {0}", [order.recall])
				)}</b> — ${tcfEsc(
					order.reason || __(order.trigger || "", null, "Recall")
				)}. ${tcfEsc(
					__("Find and return the packs below, or report the packs already used.")
				)}</div>
				<section class="tcf-card"><table class="tcf-table">${this.tableHead([
					__("Cycle ID"),
					__("Status"),
					__("Confirmation"),
				])}<tbody>${rows}</tbody></table></section>`;
			})
			.join("");
		return `<div class="tcf-recall-alert"></div>${
			orders ||
			`<section class="tcf-card"><p class="tcf-empty">${tcfEsc(
				__("No pack of the department is in an open recall order.")
			)}</p></section>`
		}`;
	}

	async confirmRecall(button) {
		const failed = __("The pack was not confirmed");
		if (!navigator.onLine) {
			this.paneAlert(
				"recall",
				failed,
				__("Offline", null, "TraceCore Launcher") +
					": " +
					__("No connection to the server."),
				__("Check the connection and try again.")
			);
			return;
		}
		button.disabled = true;
		this.paneAlert("recall");
		const blocked = (body) => {
			const error = (body && body.error) || {};
			this.paneAlert(
				"recall",
				error.title || failed,
				error.reason || "",
				error.action || __("Ask the head nurse of CSSD to confirm this pack.")
			);
			button.disabled = false;
		};
		try {
			const result = await this.post(
				"tracecore.v1.recall.confirm_pack",
				{ recall: button.dataset.recall, pack: button.dataset.pack },
				TcFlow.uuid()
			);
			if (result && result.ok) this.loadRecall();
			else blocked(result);
		} catch (error) {
			// từ chối nghiệp vụ của RPC thu hồi mang mã HTTP 4xx kèm body ok: false
			if (error.body && error.body.ok === false) blocked(error.body);
			else {
				this.paneAlert(
					"recall",
					failed,
					this.connectionReason(error),
					__("Check the connection and try again.")
				);
				button.disabled = false;
			}
		}
	}

	// ---- Đề nghị cấp bộ dụng cụ ----
	async loadIssue() {
		const result = await this.loadDeptPane(
			"issue",
			"tracecore.v1.flow.issue_overview",
			(data) => this.issueHtml(data),
			__("Could not load the set types")
		);
		if (result) this.syncIssuePar();
	}

	issueHtml(data, notice) {
		const options = (data.options || [])
			.map(
				(row) =>
					`<option value="${tcfEsc(row.set_type)}" data-min="${tcfEsc(
						row.min == null ? "" : row.min
					)}" data-max="${tcfEsc(row.max == null ? "" : row.max)}" data-stock="${tcfEsc(
						row.stock
					)}" data-available="${tcfEsc(row.available)}">${tcfEsc(
						`${row.set_name} · ${row.set_type}`
					)}</option>`
			)
			.join("");
		const time = (value) => (value ? frappe.datetime.str_to_user(value) : "");
		const statusText = (row) => {
			if (row.status === "Issued") return __("Issued", null, "Issue Request");
			if (row.status === "Partly issued")
				return __("Partly issued ({0}/{1})", [row.issued_count, row.qty]);
			return __("Waiting for issue");
		};
		const sent = (data.requests || [])
			.map(
				(row) => `<tr>
					<td>${tcfEsc(row.set_name || row.set_type)}</td>
					<td>${tcfEsc(row.qty)}</td>
					<td>${tcfEsc(time(row.needed_by))}</td>
					<td>${tcfEsc(time(row.requested_at))}</td>
					<td>${tcfEsc(row.requested_by_name)}</td>
					<td><span class="tcf-badge" data-tone="${TcFlow.returnTone(row.status)}">${tcfEsc(
					statusText(row)
				)}</span></td>
				</tr>`
			)
			.join("");
		const done = notice ? `<p class="tcf-done" role="status">${tcfEsc(notice)}</p>` : "";
		const soon = TcFlow.clientTs(new Date(Date.now() + 2 * 3600 * 1000)).slice(0, 16);
		const form = options
			? `<div class="tcf-form">
					<label class="tcf-field"><span>${tcfEsc(__("Set type"))}</span>
						<select class="tcf-select tcf-issue-type">${options}</select></label>
					<label class="tcf-field"><span>${tcfEsc(__("Quantity"))}</span>
						<input class="tcf-input tcf-issue-qty" type="number" inputmode="numeric" min="1"
							max="${tcfEsc(data.max_qty || 99)}" step="1" value="1" /></label>
					<label class="tcf-field"><span>${tcfEsc(__("Needed before"))}</span>
						<input class="tcf-input tcf-issue-needed" type="datetime-local" value="${soon}" /></label>
					<label class="tcf-field"><span>${tcfEsc(__("Department par level"))}</span>
						<output class="tcf-input tcf-issue-par" aria-live="polite"></output></label>
				</div>
				<button type="button" class="tcf-btn tcf-issue-send" data-action="tcf-issue-send">${tcfEsc(
					__("Send issue request")
				)}</button>`
			: `<p class="tcf-empty">${tcfEsc(__("No set type is set up yet."))}</p>`;
		return `<section class="tcf-card">
				${done}
				<div class="tcf-issue-alert"></div>
				${form}
				<p class="tcf-note">${tcfEsc(
					__(
						"The request is only a notice; CSSD still issues the packs at the issue station T7."
					)
				)}</p>
			</section>
			<section class="tcf-card">
				<h3>${tcfEsc(__("Issue requests sent today"))}</h3>
				${
					sent
						? `<table class="tcf-table">${this.tableHead([
								__("Set type"),
								__("Quantity"),
								__("Needed before"),
								__("Sent at"),
								__("Sent by"),
								__("Status"),
						  ])}<tbody>${sent}</tbody></table>`
						: `<p class="tcf-empty">${tcfEsc(
								__("No issue request was sent today.")
						  )}</p>`
				}
			</section>`;
	}

	// cơ số khoa của loại bộ đang chọn, kèm số bộ khoa đang giữ và số gói kho vô khuẩn đang có
	syncIssuePar() {
		const select = this.el(".tcf-issue-type");
		const out = this.el(".tcf-issue-par");
		if (!select || !out) return;
		const option = select.options[select.selectedIndex];
		if (!option) return;
		const data = option.dataset;
		const par =
			data.min === "" && data.max === ""
				? __("No par level set")
				: `${data.min === "" ? "–" : data.min}–${data.max === "" ? "–" : data.max}`;
		out.textContent = [
			par,
			__("at department: {0}", [data.stock]),
			__("in sterile store: {0}", [data.available]),
		].join(" · ");
	}

	onChange(event) {
		if (event.target.closest(".tcf-issue-type")) this.syncIssuePar();
		// Sổ tiệt khuẩn điện tử: đổi máy hoặc ngày thì nạp lại
		else if (event.target.closest(".tcf-log-machine, .tcf-log-date") && this.lead === "log") {
			this.logMachine = this.el(".tcf-log-machine").value || null;
			this.logDate = this.el(".tcf-log-date").value || null;
			this.loadLead();
		}
	}

	async sendIssue() {
		const box = this.el(".tcf-issue-body");
		const dept = this.dept;
		if (!dept || this.issueSending) return;
		const failed = __("The issue request was not sent");
		if (!navigator.onLine) {
			this.paneAlert(
				"issue",
				failed,
				__("Offline", null, "TraceCore Launcher") +
					": " +
					__("No connection to the server."),
				__("Check the connection and try again.")
			);
			return;
		}
		const needed = box.querySelector(".tcf-issue-needed").value;
		const fields = {
			department: dept.name,
			set_type: box.querySelector(".tcf-issue-type").value,
			qty: box.querySelector(".tcf-issue-qty").value.trim(),
			needed_by: needed ? `${needed.replace("T", " ")}:00` : "",
		};
		// gửi lại cùng nội dung sau lỗi mạng: dùng lại khóa và client_ts cũ để máy chủ không tạo đề nghị thứ hai
		const fingerprint = JSON.stringify(fields);
		if (!this.issueAttempt || this.issueAttempt.fingerprint !== fingerprint)
			this.issueAttempt = {
				fingerprint,
				key: TcFlow.uuid(),
				body: { ...fields, client_ts: TcFlow.clientTs() },
			};
		const attempt = this.issueAttempt;
		const button = box.querySelector(".tcf-issue-send");
		this.issueSending = true;
		if (button) button.disabled = true;
		this.paneAlert("issue");
		try {
			const result = await this.post(
				"tracecore.v1.flow.request_issue",
				attempt.body,
				attempt.key
			);
			this.issueAttempt = null;
			if (dept.name !== (this.dept && this.dept.name)) return;
			if (!result || !result.ok) {
				const error = (result && result.error) || {};
				this.paneAlert(
					"issue",
					error.title || failed,
					error.reason || "",
					error.action || __("Check the request, then send it again.")
				);
				return;
			}
			box.innerHTML = this.issueHtml(result, __("Request {0} was sent.", [result.request]));
			this.syncIssuePar();
		} catch (error) {
			this.paneAlert(
				"issue",
				failed,
				this.connectionReason(error),
				__("Check the connection and send the request again.")
			);
		} finally {
			this.issueSending = false;
			const again = box.querySelector(".tcf-issue-send");
			if (again) again.disabled = false;
		}
	}

	// ---- Đồ vải đã nhận ----
	async loadLinen() {
		const result = await this.loadDeptPane(
			"linen",
			"tracecore.v1.flow.linen_received",
			(data) => this.linenHtml(data),
			__("Could not load the linen of the department")
		);
		if (result && result.month) {
			const [year, month] = result.month.split("-");
			this.el(".tcf-linen h2").textContent = __("Linen received — month {0}", [
				`${Number(month)}/${year}`,
			]);
		}
	}

	linenHtml(data) {
		const kg = (value) =>
			Number(value || 0)
				.toFixed(1)
				.replace(".", ",");
		const day = (value) => (value ? frappe.datetime.str_to_user(value) : "");
		const difference = (row) => {
			if (!row.difference && !row.disposed) return "0";
			const sign = row.difference > 0 ? "+" : row.difference < 0 ? "−" : "";
			const note = row.disposed ? ` (${__("disposed {0}", [row.disposed])})` : "";
			return `${sign}${Math.abs(row.difference)}${note}`;
		};
		const rows = (data.rows || [])
			.map(
				(row) => `<tr>
					<td>${tcfEsc(day(row.date))}</td>
					<td>${tcfEsc(row.type_name || row.linen_type)}</td>
					<td>${tcfEsc(`${row.collected} / ${kg(row.collected_kg)}`)}</td>
					<td>${tcfEsc(`${row.returned} / ${kg(row.returned_kg)}`)}</td>
					<td>${tcfEsc(difference(row))}</td>
				</tr>`
			)
			.join("");
		const quotas = data.quotas || [];
		const range = (row) =>
			`${row.type_name} ${row.min == null ? "–" : row.min}–${
				row.max == null ? "–" : row.max
			}`;
		const outside = quotas.filter((row) => row.state !== "within");
		const quotaText = quotas.length
			? `${__("Department quota")}: ${quotas.map(range).join(", ")}. ${
					outside.length
						? __("Stock outside quota: {0}.", [
								outside.map((row) => `${row.type_name} (${row.stock})`).join(", "),
						  ])
						: __("Current stock is within quota.")
			  }`
			: __("No linen quota is set for the department.");
		const variance = __("Variance this month: {0}% (alert threshold {1}%).", [
			kg(data.variance_pct),
			kg(data.variance_limit_pct),
		]);
		const over = data.over_variance
			? ` <span class="tcf-badge" data-tone="warn">${tcfEsc(
					__("Over the threshold")
			  )}</span>`
			: "";
		return `<section class="tcf-card">
				${
					rows
						? `<table class="tcf-table">${this.tableHead([
								__("Date"),
								__("Linen type"),
								__("Collected (pieces / kg)"),
								__("Returned (pieces / kg)"),
								__("Difference", null, "Linen Flow"),
						  ])}<tbody>${rows}</tbody></table>`
						: `<p class="tcf-empty">${tcfEsc(
								__("No linen was collected or returned this month.")
						  )}</p>`
				}
				<p class="tcf-note">${tcfEsc(quotaText)} ${tcfEsc(variance)}${over}</p>
			</section>`;
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

	// ---- khu Trưởng khoa KSNK (FEAT-102, A-162): 7 mục chỉ đọc; HTML dựng ở TcFlowLead (tc_flow_lead.js) ----
	enterLead(pane) {
		this.lead = TcFlow.LEAD_PANES.includes(pane) ? pane : TcFlow.LEAD_PANES[0];
		this.manage = null;
		this.manageLink = null;
		this.dept = null;
		this.modeHint = null;
		this.entering += 1;
		this.pane = "work";
		this.view("app");
		this.setAddress(null);
		this.el(".tcf-status").innerHTML = "";
		document.title = `${__("Head of infection control")} – TraceCore`;
		this.render();
		this.loadLead();
	}

	leadHelpers() {
		return {
			esc: tcfEsc,
			day: (value) => (value ? frappe.datetime.str_to_user(String(value).slice(0, 10)) : ""),
			time: (value) => (value ? frappe.datetime.str_to_user(value) : ""),
			hour: (value) => (value ? String(value).slice(11, 16) : ""),
		};
	}

	renderLead() {
		for (const pane of [
			"host",
			"stock",
			"return",
			"issue",
			"recall",
			"linen",
			"trace",
			"manage",
		])
			this.el(`.tcf-${pane}`).hidden = true;
		this.el(".tcf-lead").hidden = false;
		this.el(".tcf-who-name").textContent = frappe.session.user_fullname || "";
		this.el(".tcf-who-role").textContent = __("Head of infection control");
		this.el(".tcf-net").textContent = "";
		const badges = this.leadBadges || {};
		this.el(".tcf-nav").innerHTML = TcFlow.LEAD_PANES.map((pane) => {
			const current = pane === this.lead ? ' aria-current="page"' : "";
			const badge = badges[pane]
				? ` <span class="tcf-nav-badge">${tcfEsc(
						badges[pane]
				  )}<span class="tcf-sr"> ${tcfEsc(__("items waiting"))}</span></span>`
				: "";
			return `<button type="button" class="tcf-nav-item" data-action="tcf-lead-pane"
				data-pane="${pane}"${current}>${tcfEsc(TcFlowLead.label(pane))}${badge}</button>`;
		}).join("");
		this.el(".tcf-lead .tcf-crumb").textContent = [
			__("Home"),
			__("Head of infection control"),
			TcFlowLead.label(this.lead),
		].join(" › ");
		this.el(".tcf-lead h2").textContent = this.leadTitle || TcFlowLead.label(this.lead);
	}

	setLeadPane(pane) {
		if (!TcFlow.LEAD_PANES.includes(pane)) return;
		this.lead = pane;
		this.leadTitle = null;
		this.setAddress(null);
		this.render();
		this.loadLead();
	}

	// tham số của mục: tháng của Giá thành, máy và ngày của Sổ tiệt khuẩn
	leadArgs(pane) {
		if (pane === "costs" && this.leadMonth) return { month: this.leadMonth };
		if (pane === "log") {
			const args = {};
			if (this.logMachine) args.equipment = this.logMachine;
			if (this.logDate) args.date = this.logDate;
			return args;
		}
		return {};
	}

	leadTitleFor(pane, data, h) {
		if (pane === "overview") return __("Today's overview — {0}", [h.day(data.date)]);
		if (pane === "costs")
			return __("Reprocessing cost — month {0}", [TcFlowLead.monthText(data.month)]);
		if (pane === "log") return __("Electronic sterilization log — {0}", [h.day(data.date)]);
		return TcFlowLead.label(pane);
	}

	// nạp một mục: đủ offline / loading / error / empty (empty do từng bảng tự hiện)
	async loadLead() {
		const pane = this.lead;
		if (!pane) return;
		const box = this.el(".tcf-lead-body");
		const tools = this.el(".tcf-lead-tools");
		const h = this.leadHelpers();
		const stale = () => this.lead !== pane;
		if (!navigator.onLine) {
			box.innerHTML = `<p class="tcf-empty tcf-offline">${tcfEsc(
				__("Offline: this page needs a connection.")
			)}</p>`;
			return;
		}
		box.innerHTML = this.loadingHtml();
		if (pane !== "costs" && pane !== "log") tools.innerHTML = "";
		try {
			const data = await this.get(TcFlowLead.PANES[pane].method, this.leadArgs(pane));
			if (stale()) return;
			this.leadData = data;
			box.innerHTML = TcFlowLead[`${pane}Html`](h, data);
			if (pane === "costs") {
				this.leadMonth = data.month;
				tools.innerHTML = TcFlowLead.costsToolsHtml(h, data.month);
			} else if (pane === "log") {
				this.logDate = data.date;
				tools.innerHTML = TcFlowLead.logToolsHtml(h, data);
			}
			if (pane === "overview") this.leadBadges = TcFlowLead.badges(data);
			this.leadTitle = this.leadTitleFor(pane, data, h);
			this.render();
			this.countUp(box);
		} catch (error) {
			if (stale()) return;
			box.innerHTML = this.alertHtml(
				__("Could not load this page"),
				this.connectionReason(error),
				__("Check the connection and try again."),
				"tcf-lead-refresh"
			);
		}
	}

	// duyệt / từ chối ghi đè cơ số: RPC hiện có của UC-31 (PIN), không viết RPC ghi mới
	openOverride(button) {
		const slot = this.el(".tcf-override-form");
		if (!slot) return;
		slot.innerHTML = TcFlowLead.overrideFormHtml(
			this.leadHelpers(),
			button.dataset.kind,
			button.dataset.override,
			TcFlow.clientTs().slice(0, 10)
		);
		this.paneAlert("override");
		const first = slot.querySelector(".tcf-input");
		if (first) first.focus();
	}

	async sendOverride() {
		const form = this.el(".tcf-override-box");
		if (!form || this.overrideSending) return;
		const approve = form.dataset.kind === "approve";
		const failed = approve
			? __("The override was not approved")
			: __("The override was not rejected");
		const value = (name) => {
			const input = form.querySelector(`.tcf-override-${name}`);
			return input ? input.value.trim() : "";
		};
		if (!navigator.onLine) {
			this.paneAlert(
				"override",
				failed,
				__("Offline", null, "TraceCore Launcher") +
					": " +
					__("No connection to the server."),
				__("Check the connection and try again.")
			);
			return;
		}
		const args = {
			override: form.dataset.override,
			reason: value("reason"),
			pin: value("pin"),
		};
		if (approve) {
			args.extra_cycles = value("cycles");
			args.valid_until = value("until");
		}
		const button = form.querySelector('[data-action="tcf-override-send"]');
		this.overrideSending = true;
		button.disabled = true;
		this.paneAlert("override");
		const blocked = (body) => {
			const error = (body && body.error) || {};
			this.paneAlert(
				"override",
				error.title || failed,
				error.reason || "",
				error.action || __("Check the decision, then send it again.")
			);
		};
		try {
			const result = await this.post(
				`tracecore.v1.par.override.${approve ? "approve" : "reject"}`,
				args,
				TcFlow.uuid()
			);
			if (result && result.ok) {
				this.leadBadges = null;
				this.loadLead();
			} else blocked(result);
		} catch (error) {
			if (error.body && error.body.ok === false) blocked(error.body);
			else
				this.paneAlert(
					"override",
					failed,
					this.connectionReason(error),
					__("Check the connection and try again.")
				);
		} finally {
			this.overrideSending = false;
			button.disabled = false;
			const pin = form.querySelector(".tcf-override-pin");
			if (pin) pin.value = "";
		}
	}

	onLeadClick(action, button) {
		if (action === "tcf-lead") this.enterLead(TcFlow.LEAD_PANES[0]);
		else if (action === "tcf-lead-pane") this.setLeadPane(button.dataset.pane);
		else if (action === "tcf-lead-refresh") this.loadLead();
		else if (action === "tcf-lead-month") {
			this.leadMonth = button.dataset.month;
			this.loadLead();
		} else if (action === "tcf-override-open") this.openOverride(button);
		else if (action === "tcf-override-cancel") {
			this.el(".tcf-override-form").innerHTML = "";
			this.paneAlert("override");
		} else if (action === "tcf-override-send") this.sendOverride();
		else if (action === "tcf-log-report")
			window.open(TcFlowLead.logReportUrl(this.leadData || {}), "_blank", "noopener");
		else return false;
		return true;
	}

	// ---- quản lý: các phân hệ của trang quản lý (Dụng cụ và bộ, ...) trong khung mới ----
	// Danh sách phân hệ và link lấy từ navigation.context (đúng quyền của tài khoản). Danh sách, form, báo cáo là màn
	// Desk hiện có, mở ngay trong khung này (iframe cùng origin, ẩn thanh trên của Desk) nên đủ chức năng thêm/sửa/in.
	enterManage(key, link) {
		this.manage = key || "instruments";
		this.manageLink = link || null;
		this.lead = null;
		this.dept = null;
		this.modeHint = null;
		this.entering += 1;
		this.pane = "work";
		this.view("app");
		this.setAddress(null);
		this.el(".tcf-status").innerHTML = "";
		document.title = `${__("Management")} – TraceCore`;
		this.render();
	}

	// nhãn phân hệ, nhóm và link dịch theo đúng ngữ cảnh của trang quản lý Desk
	launcherText(text) {
		return text ? __(text, null, "TraceCore Launcher") : "";
	}

	manageModule() {
		return this.modules.find((row) => row.key === this.manage) || this.modules[0] || null;
	}

	renderManage() {
		const module = this.manageModule();
		const link = module ? this.manageLink : null;
		this.el(".tcf-host").hidden = true;
		this.el(".tcf-stock").hidden = true;
		this.el(".tcf-return").hidden = true;
		this.el(".tcf-issue").hidden = true;
		this.el(".tcf-recall").hidden = true;
		this.el(".tcf-linen").hidden = true;
		this.el(".tcf-trace").hidden = true;
		this.el(".tcf-lead").hidden = true;
		this.el(".tcf-manage").hidden = false;
		this.el(".tcf-who-name").textContent = __("Management");
		this.el(".tcf-who-role").textContent = frappe.session.user_fullname || "";
		this.el(".tcf-net").textContent = "";
		this.el(".tcf-nav").innerHTML = this.modules
			.map((row) => {
				const current = module && row.key === module.key ? ' aria-current="page"' : "";
				return `<button type="button" class="tcf-nav-item" data-action="tcf-module"
					data-key="${tcfEsc(row.key)}"${current}>${tcfEsc(this.launcherText(row.label))}</button>`;
			})
			.join("");
		const parts = [__("Home"), __("Management")];
		if (module) parts.push(this.launcherText(module.label));
		if (link) parts.push(this.launcherText(link.label));
		this.el(".tcf-manage .tcf-crumb").textContent = parts.join(" › ");
		this.el(".tcf-manage h2").textContent = link
			? this.launcherText(link.label)
			: module
			? this.launcherText(module.label)
			: __("Management");
		this.el('[data-action="tcf-manage-back"]').hidden = !link;
		const body = this.el(".tcf-manage-body");
		const state = [this.catalogState, module && module.key, link && link.route].join("|");
		if (body.dataset.state === state) return;
		body.dataset.state = state;
		body.classList.toggle("tcf-manage-framed", Boolean(link));
		if (this.catalogState === "loading") body.innerHTML = this.loadingHtml();
		else if (this.catalogState === "error")
			body.innerHTML = this.alertHtml(
				__("Could not load the management pages"),
				this.catalogError,
				__("Check the connection and try again."),
				"tcf-catalog-retry"
			);
		else if (!module)
			body.innerHTML = `<p class="tcf-empty">${tcfEsc(
				__("No management pages for your account")
			)}</p>`;
		else if (link) this.embed(body, link);
		else body.innerHTML = this.moduleHtml(module);
	}

	moduleHtml(module) {
		const sections = module.sections
			.map((section) => {
				const links = section.links
					.map(
						(link) => `<button type="button" class="tcf-link" data-action="tcf-link"
							data-route="${tcfEsc(link.route)}">${tcfEsc(this.launcherText(link.label))}</button>`
					)
					.join("");
				return `<section class="tcf-card">
					<h3>${tcfEsc(this.launcherText(section.label))} <span class="tcf-count">${
					section.links.length
				}</span></h3>
					<div class="tcf-links">${links}</div>
				</section>`;
			})
			.join("");
		return `<p class="tcf-sub-line">${tcfEsc(
			this.launcherText(module.description || "")
		)}</p>${sections}`;
	}

	// màn Desk hiện có trong khung: chỉ nhận đường dẫn /app/... do máy chủ trả về; ẩn thanh trên của Desk
	embed(body, link) {
		if (!/^\/app\//.test(link.route || "")) {
			body.innerHTML = `<p class="tcf-empty">${tcfEsc(
				__("No management pages for your account")
			)}</p>`;
			return;
		}
		body.innerHTML = "";
		const frame = document.createElement("iframe");
		frame.className = "tcf-frame";
		frame.title = this.launcherText(link.label);
		frame.addEventListener("load", () => {
			try {
				const style = frame.contentDocument.createElement("style");
				style.textContent = ".navbar{display:none!important}:root{--navbar-height:0rem}";
				frame.contentDocument.head.appendChild(style);
			} catch (error) {
				// không chèn được kiểu thì màn vẫn dùng được, chỉ còn thanh trên của Desk
			}
		});
		frame.src = link.route;
		body.appendChild(frame);
	}

	onManageClick(action, button) {
		// thẻ Trưởng khoa KSNK mở khu Trưởng khoa trong khung (A-162), không chuyển sang trang quản lý của Desk;
		// không gian quản lý trong khung vẫn mở được bằng địa chỉ ?manage=<phân hệ>
		if (action === "tcf-module") {
			this.manage = button.dataset.key;
			this.manageLink = null;
			this.setAddress(null);
			this.render();
		} else if (action === "tcf-link") {
			const module = this.manageModule();
			const links = module ? module.sections.flatMap((section) => section.links) : [];
			this.manageLink = links.find((link) => link.route === button.dataset.route) || null;
			this.render();
		} else if (action === "tcf-manage-back") {
			this.manageLink = null;
			this.render();
		} else return false;
		return true;
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
		if (this.onManageClick(action, button)) return;
		if (this.onLeadClick(action, button)) return;
		if (action === "tcf-catalog-retry") this.loadCatalog();
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
		else if (action === "tcf-return-refresh") this.loadReturn();
		else if (action === "tcf-return-send") this.sendReturn();
		else if (action === "tcf-issue-refresh") this.loadIssue();
		else if (action === "tcf-issue-send") this.sendIssue();
		else if (action === "tcf-recall-refresh") this.loadRecall();
		else if (action === "tcf-recall-confirm") this.confirmRecall(button);
		else if (action === "tcf-linen-refresh") this.loadLinen();
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
	// địa chỉ cũ /app/tc-flow: thay bằng /app/tracecore/home (giữ ?station / ?department / ?manage) rồi để router
	// mở lại; trang chủ /app/tracecore giao đường dẫn con "home" cho Page này
	if ((frappe.get_route() || [])[0] === TcFlow.OLD_ROUTE) {
		window.history.replaceState(null, "", TcFlow.BASE + window.location.search);
		frappe.router.route();
		return;
	}
	if (frappe.tc_flow) frappe.tc_flow.show();
};
