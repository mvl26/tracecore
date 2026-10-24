// Home entry point; keeps the existing ERPNext Workspace intact.
(() => {
	const roles = frappe.user_roles || [];
	if (!roles.some((role) => role === "System Manager" || /^TC R\d\d$/.test(role))) return;
	let observer;
	function update() {
		if (observer) observer.disconnect();
		const route = frappe.get_route();
		if (route[0] !== "Workspaces") return;
		frappe.after_ajax(() => {
			if (frappe.get_route().join("/") !== route.join("/")) return;
			const main = $(".layout-main-section:visible").first();
			if (!main.length) return;
			const insert = () => {
				const sidebar = main
					.closest(".page-container")
					.find('.standard-sidebar-section[data-title="Public"]');
				if (sidebar.length && !sidebar.find(".tc-sidebar-launcher").length) {
					const item = $(
						"<div class='tc-sidebar-launcher standard-sidebar-item'></div>"
					);
					$("<a class='item-anchor' href='/app/tracecore'>TraceCore</a>").appendTo(item);
					const home = sidebar.find('[item-name="Home"]');
					if (home.length) item.insertAfter(home);
					else item.appendTo(sidebar);
				}
				if (
					["Home", __("Home")].includes(route[1]) &&
					!main.find(".tc-home-launcher").length
				) {
					$("<a class='btn btn-primary tc-home-launcher' href='/app/tracecore'></a>")
						.text(__("Open TraceCore"))
						.prependTo(main);
				}
			};
			insert();
			observer = new MutationObserver(insert);
			observer.observe(main.closest(".page-container")[0] || main[0], {
				childList: true,
				subtree: true,
			});
		});
	}
	frappe.router.on("change", update);
	$(update);
})();
