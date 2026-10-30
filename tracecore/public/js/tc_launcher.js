// TraceCore accounts enter the application home instead of sample ERPNext Workspaces.
// Destination List/Form permissions and station card authentication still apply.
(() => {
	const roles = frappe.user_roles || [];
	if (!roles.some((role) => role === "System Manager" || /^TC R\d\d$/.test(role))) return;
	function update() {
		if (frappe.get_route()[0] === "Workspaces") frappe.set_route("tracecore");
	}
	frappe.router.on("change", update);
	$(update);
})();
