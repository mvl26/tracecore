/* global tracecore */
// Màn quản lý KSNK toàn viện — Page tc-ksnk (FEAT-056; A-131 a–c, e; ux-foundations B1; design.md §4).
// Rail chia nhóm theo bản giao diện v1.12, router /app/tc-ksnk/<màn>, bộ lọc năm/kỳ/khoa dùng chung giữ trong URL,
// trạng thái màn: đang tải, rỗng, lỗi (có Thử lại), không có quyền, mất mạng. Màn từng SCR là file riêng nạp khi mở,
// tự đăng ký vào window.TcKsnkScreens[slug] = { render(el, ctx) }. Chữ hiển thị qua __(); mã định danh dùng font mono.

const TC_KSNK_NAV = "tracecore.v1.ksnk.nav";
// `tab`: tab trong màn (FEAT-058 SCR-48, A-131 a — tab giữ trong query string)
const TC_KSNK_FILTERS = ["period", "department", "year", "tab"];

window.TcKsnkScreens = window.TcKsnkScreens || {};

const TcKsnk = {
	esc(value) {
		return String(value === null || value === undefined ? "" : value).replace(
			/[&<>"']/g,
			(char) =>
				({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])
		);
	},

	// Hàng thao tác dùng chung cho khối hiển thị một bản ghi/chứng từ (A-131): luôn đủ thao tác hợp lệ theo
	// trạng thái và quyền, không bao giờ chỉ còn chữ. Quyền thật vẫn kiểm ở RPC/DocPerm; cờ chỉ quyết định hiện nút.
	// opts: doctype, name, docstatus (0/1/2, bỏ trống nếu không ghi sổ), can_write, can_create, create_label,
	// create_query, print_format, can_print (mặc định true), extra (mảng HTML bổ sung đặt trước nút In).
	recordActions(opts, wrap) {
		const esc = TcKsnk.esc;
		const slug = String(opts.doctype || "")
			.toLowerCase()
			.replace(/ /g, "-");
		const link = (cls, href, label, attrs) =>
			`<a class="btn ${cls}" href="${esc(href)}"${attrs || ""}>${esc(label)}</a>`;
		const out = [];
		if (opts.name) {
			const ds = opts.docstatus;
			let label = opts.can_write ? __("Open form") : __("View form");
			if (opts.can_write && ds === 1) label = __("Open form to cancel or amend");
			else if (opts.can_write && ds === 2) label = __("Open form to amend");
			out.push(
				link("btn-default btn-sm", `/app/${slug}/${encodeURIComponent(opts.name)}`, label)
			);
		}
		if (opts.can_create) {
			const query = opts.create_query ? `?${opts.create_query}` : "";
			out.push(
				link(
					"btn-default btn-sm",
					`/app/${slug}/new${query}`,
					opts.create_label || __("Create new")
				)
			);
		}
		(opts.extra || []).forEach((html) => out.push(html));
		if (opts.name && opts.can_print !== false && opts.docstatus !== 2) {
			const format = opts.print_format
				? `&format=${encodeURIComponent(opts.print_format)}`
				: "";
			out.push(
				link(
					"btn-default btn-sm",
					`/printview?doctype=${encodeURIComponent(
						opts.doctype
					)}&name=${encodeURIComponent(opts.name)}${format}`,
					__("Print"),
					' target="_blank"'
				)
			);
		}
		const html = out.join(" ");
		return wrap === false ? html : `<div class="tc-ksnk-actions">${html}</div>`;
	},

	parseRoute(route, search) {
		const params = new URLSearchParams(search || "");
		const filters = {};
		TC_KSNK_FILTERS.forEach((key) => {
			filters[key] = params.get(key) || "";
		});
		return { slug: (route && route[1]) || "", filters };
	},

	query(filters) {
		const params = new URLSearchParams();
		TC_KSNK_FILTERS.forEach((key) => {
			if (filters[key]) params.set(key, filters[key]);
		});
		return params.toString();
	},

	pick(nav, slug) {
		for (const group of (nav && nav.groups) || []) {
			for (const item of group.items) {
				if (item.slug === slug) return item;
			}
		}
		return null;
	},

	railHtml(nav, active) {
		const esc = TcKsnk.esc;
		return (
			((nav && nav.groups) || [])
				.filter((group) => group.items.length)
				.map((group) => {
					const items = group.items
						.map((item) => {
							const on = item.slug === active;
							const badge = item.badge
								? `<span class="tc-ksnk-count" title="${esc(
										__("{0} pending", [item.badge])
								  )}">${esc(item.badge)}</span>`
								: "";
							return (
								`<a href="/app/tc-ksnk/${esc(item.slug)}" class="tc-ksnk-nav-item${
									on ? " is-active" : ""
								}"` +
								` data-slug="${esc(item.slug)}"${
									on ? ' aria-current="page"' : ""
								}>` +
								`<span>${esc(item.label)}</span>${badge}</a>`
							);
						})
						.join("");
					return `<div class="tc-ksnk-group"><div class="tc-ksnk-group-label">${esc(
						group.label
					)}</div>${items}</div>`;
				})
				.join("") + TcKsnk.otherSurfacesHtml(nav)
		);
	},

	// Nhóm "Bề mặt khác" (ảnh SCR-66): lối sang Cổng khoa (DEPT) và PDA; ẩn với vai trò chỉ đọc. Quyền thật ở từng trang.
	otherSurfacesHtml(nav) {
		const esc = TcKsnk.esc;
		if (!nav || nav.read_only || !(nav.groups || []).length) return "";
		const link = (href, label) =>
			`<a href="${esc(href)}" class="tc-ksnk-nav-item"><span>${esc(label)}</span></a>`;
		return (
			`<div class="tc-ksnk-group"><div class="tc-ksnk-group-label">${esc(
				__("Other surfaces", null, "IC Rail")
			)}</div>` +
			link("/ksnk-khoa/chi-so", __("Department portal (DEPT)", null, "IC Rail")) +
			link("/app/station", __("Supervision PDA", null, "IC Rail")) +
			"</div>"
		);
	},

	stateHtml(kind, message) {
		const esc = TcKsnk.esc;
		if (kind === "loading") {
			return (
				`<div class="tc-ksnk-state is-loading" aria-busy="true">` +
				`<span class="tc-ksnk-skeleton"></span><span class="tc-ksnk-skeleton"></span>` +
				`<span class="tc-ksnk-skeleton"></span><span>${esc(__("Loading…"))}</span></div>`
			);
		}
		if (kind === "empty") {
			return `<div class="tc-ksnk-state is-empty">${esc(message || __("No data."))}</div>`;
		}
		if (kind === "forbidden") {
			return (
				`<div class="tc-ksnk-alert is-error" role="alert"><b>${esc(
					__("You are not allowed to open this screen.")
				)}</b> ` +
				`${esc(
					__("Ask the administrator (R10) to grant the infection control role you need.")
				)}</div>`
			);
		}
		if (kind === "offline") {
			return (
				`<div class="tc-ksnk-alert is-info" role="status">` +
				`${esc(
					__("You are offline. Connect to the network to see infection control data.")
				)}</div>`
			);
		}
		if (kind === "dept") {
			return (
				`<div class="tc-ksnk-alert is-info" role="status">` +
				`${esc(
					__(
						"Infection control network members work on the department portal, not on this screen."
					)
				)}` +
				// FEAT-065 (FR-M9-26): R12 mở Cổng khoa — chỉ số khoa cạnh toàn viện + việc cần làm
				` <a class="btn btn-default btn-sm" href="/ksnk-khoa/chi-so">${esc(
					__("Open the department portal")
				)}</a></div>`
			);
		}
		return (
			`<div class="tc-ksnk-alert is-error" role="alert"><b>${esc(
				__("Cannot load this screen.")
			)}</b> ` +
			`${esc(
				message || ""
			)} <button type="button" class="btn btn-default btn-sm" data-action="retry">` +
			`${esc(__("Retry"))}</button></div>`
		);
	},

	mount(wrapper) {
		const esc = TcKsnk.esc;
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Hospital Infection Control"),
			single_column: true,
		});
		const root = $(
			`<div class="tc-ksnk" data-surface="WEB">` +
				`<div class="tc-ksnk-zonebar" aria-hidden="true"></div>` +
				`<div class="tc-ksnk-body">` +
				`<nav class="tc-ksnk-rail" aria-label="${esc(__("Infection control"))}"></nav>` +
				`<main class="tc-ksnk-main">` +
				`<div class="tc-ksnk-crumb"></div>` +
				`<div class="tc-ksnk-head"><h2 class="tc-ksnk-title"></h2><span class="tc-ksnk-tag"></span></div>` +
				`<div class="tc-ksnk-content"></div>` +
				`</main></div></div>`
		).appendTo(page.main);
		const rail = root.find(".tc-ksnk-rail");
		const content = root.find(".tc-ksnk-content");
		const state = { nav: null, filters: {}, request: 0, loading: null };

		rail.on("click", ".tc-ksnk-nav-item", (event) => {
			event.preventDefault();
			frappe.set_route("tc-ksnk", $(event.currentTarget).attr("data-slug"));
		});
		content.on("click", '[data-action="retry"]', () => {
			if (!state.nav) state.loading = null;
			show();
		});
		window.addEventListener("online", () => show());
		window.addEventListener("offline", () => show());
		frappe.router.on("change", () => {
			if (frappe.get_route()[0] === "tc-ksnk") show();
		});

		function loadNav() {
			if (!state.loading) {
				state.loading = tracecore.desk_get(TC_KSNK_NAV).then((nav) => {
					state.nav = nav;
					return nav;
				});
			}
			return state.loading;
		}

		function header(item) {
			root.find(".tc-ksnk-crumb").text(item ? `${__("Hospital IC")} › ${item.label}` : "");
			root.find(".tc-ksnk-title").text(item ? item.label : __("Hospital Infection Control"));
			root.find(".tc-ksnk-tag").text(item ? `${item.scr} · ${item.uc}` : "");
		}

		function writeUrl(slug) {
			const query = TcKsnk.query(state.filters);
			window.history.replaceState(
				null,
				"",
				`/app/tc-ksnk/${slug}${query ? `?${query}` : ""}`
			);
		}

		function show() {
			const route = TcKsnk.parseRoute(frappe.get_route(), window.location.search);
			TC_KSNK_FILTERS.forEach((key) => {
				if (route.filters[key]) state.filters[key] = route.filters[key];
			});
			if (!navigator.onLine) {
				content.html(TcKsnk.stateHtml("offline"));
				return;
			}
			if (!state.nav) {
				header(null);
				content.html(TcKsnk.stateHtml("loading"));
				loadNav().then(show, (error) => {
					state.loading = null;
					content.html(TcKsnk.stateHtml("error", (error && error.message) || ""));
				});
				return;
			}
			if (state.nav.dept_only) {
				rail.html("");
				header(null);
				content.html(TcKsnk.stateHtml("dept"));
				return;
			}
			const slug = route.slug || state.nav.home;
			const item = TcKsnk.pick(state.nav, slug);
			rail.html(TcKsnk.railHtml(state.nav, slug));
			header(item);
			if (!item) {
				content.html(TcKsnk.stateHtml("forbidden"));
				return;
			}
			writeUrl(slug);
			const token = ++state.request;
			content.html(TcKsnk.stateHtml("loading"));
			frappe.require(item.script, () => {
				if (token !== state.request) return;
				const screen = window.TcKsnkScreens[item.slug];
				if (!screen) {
					content.html(TcKsnk.stateHtml("error", __("The screen script did not load.")));
					return;
				}
				screen.render(content.get(0), {
					item,
					filters: state.filters,
					departments: state.nav.departments || [],
					readOnly: !!state.nav.read_only,
					esc,
					get: (method, args) => tracecore.desk_get(method, args),
					state: (kind, message) => TcKsnk.stateHtml(kind, message),
					isCurrent: () => token === state.request,
					setFilters(updates) {
						Object.assign(state.filters, updates);
						writeUrl(item.slug);
					},
				});
			});
		}

		return { show };
	},
};

window.TcKsnk = TcKsnk;
