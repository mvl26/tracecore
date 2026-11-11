/* global TcKsnk */
// Desk Page tc-ksnk — màn quản lý KSNK toàn viện (FEAT-056; A-131). Shell ở public/js/ksnk/ksnk_shell.js (page_js);
// mỗi màn SCR-47..66 (WEB) là một file trong public/js/ksnk/ do registry tracecore.ui.ksnk khai báo.

frappe.pages["tc-ksnk"].on_page_load = function (wrapper) {
	wrapper.tcKsnk = TcKsnk.mount(wrapper);
};

frappe.pages["tc-ksnk"].on_page_show = function (wrapper) {
	if (wrapper.tcKsnk) wrapper.tcKsnk.show();
};
