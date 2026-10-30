/* global tracecore */
// Desk FEAT-006 (FR-M9-13, A-54 D11): ô quét chung trên List View các DocType nghiệp vụ. Phím "/" đưa con trỏ vào ô;
// quét hoặc gõ mã rồi Enter → server (tracecore.v1.dashboard.find_in_list) tìm bản ghi khớp đúng một thì mở form,
// không thì lọc danh sách theo mã. Tìm, lọc, sắp xếp, phân trang còn lại giữ nguyên List View chuẩn Frappe.

frappe.provide("tracecore.list_scan");

const TC_SCAN_FIND = "tracecore.v1.dashboard.find_in_list";
const TC_SCAN_DOCTYPES = ["Set Unit", "Pack", "Sterilization Load", "Wash Batch", "Dirty Receipt", "Issue Note", "Usage Record", "Instrument", "Equipment", "Recall Order", "Incident CAPA", "Par Override", "Item", "Batch"];

tracecore.list_scan.find = async function (listview, raw) {
	const code = (raw || "").trim();
	if (!code) return;
	try {
		const result = await tracecore.desk_get(TC_SCAN_FIND, { doctype: listview.doctype, code });
		listview.tc_scan.set_value("");
		if (result.name) {
			frappe.set_route("Form", listview.doctype, result.name);
			return;
		}
		await listview.filter_area.add([[listview.doctype, result.field, "like", "%" + result.code + "%"]]);
	} catch (error) {
		/* lỗi quyền/kết nối đã hiện bằng thông báo của Frappe; giữ mã trong ô để quét lại */
	}
};

tracecore.list_scan.attach = function (listview) {
	if (!listview || listview.tc_scan || !TC_SCAN_DOCTYPES.includes(listview.doctype) || !listview.page) return;
	const field = listview.page.add_field({
		fieldname: "tc_scan",
		fieldtype: "Data",
		label: __("Scan or type a code"),
		placeholder: __("Scan or type a code"),
	});
	listview.tc_scan = field;
	field.$input.attr({ autocomplete: "off", "aria-keyshortcuts": "/" }).addClass("tc-list-scan");
	field.$input.on("keydown", (event) => {
		if (event.key !== "Enter") return;
		event.preventDefault();
		tracecore.list_scan.find(listview, field.get_value());
	});
};

function tc_list_scan_patch() {
	const proto = frappe.views && frappe.views.ListView && frappe.views.ListView.prototype;
	if (!proto || proto.tc_scan_patched) return;
	const original = proto.after_render;
	proto.after_render = function (...args) {
		const result = original ? original.apply(this, args) : undefined;
		tracecore.list_scan.attach(this);
		return result;
	};
	proto.tc_scan_patched = true;
}

function tc_list_scan_current() {
	return frappe.get_route()[0] === "List" && window.cur_list && window.cur_list.tc_scan ? window.cur_list : null;
}

$(document).on("keydown", (event) => {
	if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
		const target = event.target;
		if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
		const listview = tc_list_scan_current();
		if (!listview) return;
		event.preventDefault();
		listview.tc_scan.$input.trigger("focus");
	}
});

tc_list_scan_patch();
frappe.router && frappe.router.on("change", () => {
	tc_list_scan_patch();
	setTimeout(() => window.cur_list && tracecore.list_scan.attach(window.cur_list), 0);
});
