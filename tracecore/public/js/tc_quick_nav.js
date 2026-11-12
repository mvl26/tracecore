// NAV-05: thanh truy cập nhanh trên navbar Desk. Dụng cụ / Đồ vải / Chất thải mở phân hệ của trang chủ
// (/app/tracecore/<key>), KSNK mở Page tc-ksnk. Server gửi key tài khoản mở được trong frappe.boot.tc_quick_nav
// (tracecore.ui.quick_nav); file này chỉ có hàm thuần để test bằng tracecore/tests/js_harness.py.
const TcQuickNav = {
	LINKS: [
		{
			key: "instruments",
			label: "Instruments",
			icon: "tool",
			href: "/app/tracecore/instruments",
		},
		{ key: "linen", label: "Linen", icon: "retail", href: "/app/tracecore/linen" },
		{ key: "waste", label: "Waste", icon: "delete", href: "/app/tracecore/waste" },
		{ key: "ksnk", label: "Infection control", icon: "healthcare", href: "/app/tc-ksnk" },
	],
	CONTEXT: "TraceCore Quick Access",

	// ô đang mở theo URL: trang chủ giữ phân hệ trên URL nên đọc pathname, không đọc frappe.get_route()
	current_key(pathname) {
		const parts = String(pathname || "")
			.split("/")
			.filter(Boolean);
		if (parts[0] !== "app") return null;
		if (parts[1] === "tc-ksnk") return "ksnk";
		if (parts[1] !== "tracecore" || !parts[2]) return null;
		const key = decodeURIComponent(parts[2]);
		return TcQuickNav.LINKS.some((link) => link.key === key) ? key : null;
	},

	// phân hệ trang chủ mở: phân hệ trên URL nếu tài khoản có, rồi phân hệ đang chọn, rồi phân hệ mặc định
	pick_module(modules, requested, selected, opens_here) {
		const ok = (key) =>
			key && modules.some((module) => module.key === key && opens_here(module));
		if (ok(requested)) return requested;
		if (ok(selected)) return selected;
		return (modules.find(opens_here) || modules[0]).key;
	},

	module_path(key) {
		return key ? `/app/tracecore/${encodeURIComponent(key)}` : "/app/tracecore";
	},

	// HTML của thanh; không có ô nào thì chuỗi rỗng. deps: t = __, icon = frappe.utils.icon, esc = escape HTML
	render(allowed, current, deps) {
		const links = TcQuickNav.LINKS.filter((link) => (allowed || []).includes(link.key));
		if (!links.length) return "";
		const t = (text) => deps.esc(deps.t(text, null, TcQuickNav.CONTEXT));
		const items = links.map((link) => {
			const label = t(link.label);
			const state = link.key === current ? ' aria-current="page"' : "";
			return (
				`<a href="${link.href}" title="${label}" data-key="${link.key}"${state}>` +
				`${deps.icon(link.icon, "sm")}<span>${label}</span></a>`
			);
		});
		return `<nav class="tc-quick-nav d-none d-lg-flex" aria-label="${t(
			"Quick access"
		)}">${items.join("")}</nav>`;
	},

	// chuyển trạng thái đang mở (chữ + aria-current, không chỉ bằng màu) sang ô của key
	mark(anchors, key) {
		Array.from(anchors || []).forEach((anchor) => {
			if (anchor.dataset.key === key) anchor.setAttribute("aria-current", "page");
			else anchor.removeAttribute("aria-current");
		});
	},

	refresh() {
		TcQuickNav.mark(
			document.querySelectorAll(".tc-quick-nav a"),
			TcQuickNav.current_key(window.location.pathname)
		);
	},
};

window.TcQuickNav = TcQuickNav;
