frappe.pages["tracecore"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "TraceCore",
		single_column: true,
	});
	const root = $("<section class='tc-launcher' data-surface='WEB'></section>").appendTo(
		page.main
	);
	let request = 0;
	const visible = () => frappe.get_route()[0] === "tracecore";
	const message = (title, reason, action, error = false) => {
		root.empty();
		const box = $("<div role='status' class='tc-launcher-message'></div>").appendTo(root);
		if (error) box.addClass("tc-launcher-error").attr("role", "alert");
		$("<h2></h2>").text(title).appendTo(box);
		$("<p></p>").text(reason).appendTo(box);
		if (action)
			$("<button type='button' class='btn btn-primary'></button>")
				.text(__("Try again"))
				.on("click", load)
				.appendTo(box);
	};
	function card(grid, title, description, kind) {
		const item = $("<section class='tc-launcher-card'></section>")
			.addClass(kind)
			.appendTo(grid);
		$("<h2></h2>").text(title).appendTo(item);
		$("<p></p>").text(description).appendTo(item);
		return item;
	}
	// Trang chủ admin có sidebar (ux-foundations NAV-02)
	const KIND_ICONS = {
		page: "external-link",
		catalog: "folder-normal",
		document: "file",
		report: "chart",
	};
	let selected_module = null;
	function icon(name, size = "md") {
		return $(frappe.utils.icon(name, size)).attr("aria-hidden", "true");
	}
	function tile(grid, label, route, badge) {
		const item = $(
			route ? "<a class='tc-admin-tile'></a>" : "<div class='tc-admin-tile'></div>"
		)
			.append(badge)
			.append($("<span class='tc-admin-tile-label'></span>").text(label))
			.appendTo(grid);
		if (route) item.attr("href", route).append(icon("right", "sm"));
		return item;
	}
	function section(body, title, count) {
		const block = $("<section class='tc-admin-section'></section>").appendTo(body);
		$("<h3></h3>").text(title).append($("<span></span>").text(count)).appendTo(block);
		return $("<div class='tc-admin-grid'></div>").appendTo(block);
	}
	function render_module(body, module) {
		module.sections.forEach((group) => {
			const grid = section(
				body,
				__(group.label, null, "TraceCore Launcher"),
				group.links.length
			);
			group.links.forEach((link) =>
				tile(
					grid,
					__(link.label, null, "TraceCore Launcher"),
					link.route,
					$("<span class='tc-admin-badge'></span>")
						.addClass(`tc-admin-kind-${group.kind}`)
						.append(icon(KIND_ICONS[group.kind]))
				)
			);
		});
	}
	function render_stations(body, data) {
		const zones = new Map();
		data.stations.forEach((item) => {
			const zone = __(item.zone || "Other stations", null, "TraceCore Launcher");
			if (!zones.has(zone)) zones.set(zone, []);
			zones.get(zone).push(item);
		});
		if (!zones.size)
			$("<p class='tc-launcher-note'></p>").text(__("No available station")).appendTo(body);
		zones.forEach((items, zone) => {
			const grid = section(body, zone, items.length);
			items.forEach((item) => {
				const badge = $("<span class='tc-admin-badge'></span>").addClass(
					`tc-admin-zone-${item.zone_color}`
				);
				if (item.station_no) badge.text(`T${item.station_no}`);
				else badge.append(icon("scan"));
				// tên trạm cấu hình thường đã có số ("T1 Tiếp nhận"); ô số đã hiện nên không lặp
				const full = __(item.label);
				const name = full.replace(new RegExp(`^T${item.station_no}\\s+`), "") || full;
				const label = item.implemented ? name : `${name} — ${__("Not implemented yet")}`;
				const route = item.implemented
					? `/app/station?station=${encodeURIComponent(item.name)}`
					: null;
				// router Desk bỏ ?station= khi bấm <a>; Page station đọc mã từ URL lúc nạp nên phải nạp lại trang
				tile(grid, label, route, badge).on("click", (event) => {
					if (!route) return;
					event.preventDefault();
					event.stopPropagation();
					window.location.assign(route);
				});
			});
		});
		if (data.department)
			$("<p class='tc-launcher-note'></p>")
				.text(__("Department portal is not implemented yet."))
				.appendTo(body);
	}
	function render_admin(data) {
		root.empty();
		const STATIONS = {
			key: "stations",
			cluster: "operations",
			label: "Stations",
			icon: "scan",
			description: "Choose a station, then scan your employee card.",
		};
		const modules = [...data.admin_modules];
		const last_operation = modules.findLastIndex((module) => module.cluster === "operations");
		modules.splice(last_operation + 1, 0, STATIONS);
		if (!modules.some((module) => module.key === selected_module))
			selected_module = modules[0].key;
		const shell = $("<div class='tc-admin'></div>").appendTo(root);
		const nav = $("<nav class='tc-admin-nav'></nav>")
			.attr("aria-label", __("CSSD management"))
			.appendTo(shell);
		const main = $("<div class='tc-admin-main'></div>").appendTo(shell);
		function show(module) {
			selected_module = module.key;
			nav.find("button").each(function () {
				$(this).attr("aria-current", $(this).data("key") === module.key ? "page" : null);
			});
			main.empty();
			const head = $("<header class='tc-admin-head'></header>").appendTo(main);
			$("<span class='tc-admin-head-icon'></span>").append(icon(module.icon)).appendTo(head);
			const text = $("<div></div>").appendTo(head);
			$("<h2></h2>").text(__(module.label, null, "TraceCore Launcher")).appendTo(text);
			$("<p></p>").text(__(module.description, null, "TraceCore Launcher")).appendTo(text);
			const body = $("<div class='tc-admin-body'></div>").appendTo(main);
			if (module.key === STATIONS.key) render_stations(body, data);
			else render_module(body, module);
		}
		let cluster = modules[0].cluster;
		modules.forEach((module) => {
			if (module.cluster !== cluster) {
				cluster = module.cluster;
				$("<div class='tc-admin-nav-gap'></div>").appendTo(nav);
			}
			$("<button type='button'></button>")
				.data("key", module.key)
				.append(icon(module.icon))
				.append($("<span></span>").text(__(module.label, null, "TraceCore Launcher")))
				.on("click", () => show(module))
				.appendTo(nav);
		});
		show(modules.find((module) => module.key === selected_module));
	}
	function render(data) {
		if (data.admin_modules.length) return render_admin(data);
		root.empty();
		$("<h1>TraceCore</h1>").appendTo(root);
		$("<p class='tc-launcher-intro'></p>")
			.text(
				__("Choose your workspace. Station access requires an authorised employee card.")
			)
			.appendTo(root);
		const grid = $("<div class='tc-launcher-grid'></div>").appendTo(root);
		const management = card(
			grid,
			__("CSSD management"),
			__("Manage instruments, equipment and processing records."),
			"tc-launcher-management"
		);
		if (data.management.length) {
			const links = $("<nav></nav>")
				.attr("aria-label", __("CSSD management"))
				.appendTo(management);
			// link theo nhóm (thứ tự thiết lập ban đầu); context "TraceCore Launcher" để tên CSSD thắng bản dịch chung
			let group = null;
			data.management.forEach((link) => {
				if (link.group !== group) {
					group = link.group;
					$("<h3 class='tc-launcher-group'></h3>")
						.text(__(group, null, "TraceCore Launcher"))
						.appendTo(links);
				}
				$("<a class='tc-launcher-link'></a>")
					.attr("href", link.route)
					.text(__(link.label, null, "TraceCore Launcher"))
					.appendTo(links);
			});
		} else
			$("<p></p>").text(__("No management access for this account.")).appendTo(management);
		const station = card(
			grid,
			__("Instrument processing technician"),
			__("Choose a station, then scan your employee card."),
			"tc-launcher-station"
		);
		$("<label for='tc-launcher-station'></label>").text(__("Station")).appendTo(station);
		const select = $(
			"<select id='tc-launcher-station' class='form-control'></select>"
		).appendTo(station);
		data.stations.forEach((item) =>
			$("<option></option>")
				.val(item.name)
				.prop("disabled", !item.implemented)
				.text(
					`${__(item.label)} (${item.name})${
						item.implemented ? "" : " — " + __("Not implemented yet")
					}`
				)
				.appendTo(select)
		);
		const available = data.stations.filter((item) => item.implemented);
		if (available.length) select.val(available[0].name);
		else
			select
				.append($("<option selected></option>").text(__("No available station")))
				.prop("disabled", true);
		$("<button type='button' class='btn btn-primary'></button>")
			.text(__("Enter station"))
			.prop("disabled", !available.length)
			.on("click", () => {
				if (!navigator.onLine) return load();
				const item = available.find((item) => item.name === select.val());
				if (item)
					window.location.assign(
						`/app/station?station=${encodeURIComponent(item.name)}`
					);
			})
			.appendTo(station);
		$("<p class='tc-launcher-note'></p>")
			.text(
				__(
					"Stations marked as not implemented will be enabled after their feature is delivered."
				)
			)
			.appendTo(station);
		const department = card(
			grid,
			__("Clinical department"),
			__("Department stock, instrument usage and issue requests."),
			"tc-launcher-department"
		);
		$("<p class='tc-launcher-note'></p>")
			.text(
				data.department
					? __("Department portal is not implemented yet.")
					: __("No department access for this account.")
			)
			.appendTo(department);
		$("<button type='button' class='btn btn-primary' disabled></button>")
			.text(__("Not implemented yet"))
			.appendTo(department);
	}
	async function load() {
		const current = ++request;
		if (!navigator.onLine) {
			message(
				__("Offline", null, "TraceCore Launcher"),
				__("Connect to the network to choose a workspace."),
				true
			);
			return;
		}
		message(__("Loading workspaces…"), "", false);
		try {
			const response = await frappe.call({
				method: "tracecore.v1.navigation.context",
				type: "GET",
			});
			if (current === request && visible()) render(response.message);
		} catch (error) {
			if (current === request && visible())
				message(
					__("Cannot load workspaces"),
					__("Check your connection and account permissions, then try again."),
					true,
					true
				);
		}
	}
	window.addEventListener("offline", () => {
		if (visible()) load();
	});
	window.addEventListener("online", () => {
		if (visible()) load();
	});
	wrapper.tc_launcher_load = load;
};

frappe.pages["tracecore"].on_page_show = function (wrapper) {
	wrapper.tc_launcher_load();
};
