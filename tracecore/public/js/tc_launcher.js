// TraceCore accounts enter the application home instead of sample ERPNext Workspaces.
// Destination List/Form permissions and station card authentication still apply.
// frappe.user_roles chỉ có sau khi Desk khởi động nên phải chờ app_ready.
/* global TcQuickNav */
$(document).on("app_ready", () => {
	const roles = frappe.user_roles || [];
	if (!roles.some((role) => role === "System Manager" || /^TC R\d\d$/.test(role))) return;
	function show_brand() {
		const home = $(".navbar-home");
		if (!home.length || home.find(".tc-navbar-brand").length) return;
		// tên bệnh viện theo ô App Name của Website Settings của site (tracecore.ui.branding), mặc định TraceCore
		$("<span class='tc-navbar-brand'></span>")
			.text(frappe.boot.tc_brand || "TraceCore")
			.css({
				marginLeft: "var(--tc-sp-2)",
				fontSize: "var(--tc-fs-lg)",
				fontWeight: "var(--tc-fw-bold)",
				color: "var(--tc-primary)",
			})
			.appendTo(home);
	}
	function update() {
		// lúc Desk khởi động route có thể chưa có; lỗi ở đây làm hỏng cả frappe.Application
		if ((frappe.get_route() || [])[0] === "Workspaces") frappe.set_route("tracecore");
	}
	// NAV-05: thanh truy cập nhanh; server chỉ gửi ô tài khoản mở được, không có role TC thì không có ô nào
	function show_quick_nav() {
		const collapse = $(".navbar .navbar-collapse").first();
		if (!collapse.length || collapse.find(".tc-quick-nav").length) return;
		const html = TcQuickNav.render(
			frappe.boot.tc_quick_nav,
			TcQuickNav.current_key(location.pathname),
			{
				t: __,
				icon: (name, size) =>
					frappe.utils.icon(name, size).replace("<svg", '<svg aria-hidden="true"'),
				esc: frappe.utils.escape_html,
			}
		);
		if (html) collapse.prepend(html);
	}
	show_brand();
	show_quick_nav();
	frappe.router.on("change", update);
	frappe.router.on("change", () => TcQuickNav.refresh());
	update();
});
