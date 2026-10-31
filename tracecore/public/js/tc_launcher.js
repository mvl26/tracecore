// TraceCore accounts enter the application home instead of sample ERPNext Workspaces.
// Destination List/Form permissions and station card authentication still apply.
// frappe.user_roles chỉ có sau khi Desk khởi động nên phải chờ app_ready.
$(document).on("app_ready", () => {
	const roles = frappe.user_roles || [];
	if (!roles.some((role) => role === "System Manager" || /^TC R\d\d$/.test(role))) return;
	function show_brand() {
		const home = $(".navbar-home");
		if (!home.length || home.find(".tc-navbar-brand").length) return;
		$("<span class='tc-navbar-brand'>TraceCore</span>")
			.css({
				marginLeft: "var(--tc-sp-2)",
				fontSize: "var(--tc-fs-lg)",
				fontWeight: "var(--tc-fw-bold)",
				color: "var(--tc-primary)",
			})
			.appendTo(home);
	}
	function update() {
		if (frappe.get_route()[0] === "Workspaces") frappe.set_route("tracecore");
	}
	show_brand();
	frappe.router.on("change", update);
	update();
});
