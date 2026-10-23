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
	function render(data) {
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
			data.management.forEach((link) =>
				$("<a class='tc-launcher-link'></a>")
					.attr("href", link.route)
					.text(__(link.doctype))
					.appendTo(links)
			);
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
