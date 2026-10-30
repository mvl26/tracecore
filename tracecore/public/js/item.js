/* global tracecore */
// Desk: form Item (ERPNext) — ba việc, gắn qua hook doctype_js:
// 1. Nút "Cấp mã cuộn" và "In nhãn cuộn" cho Item nhóm Nhãn (SCR-33, FEAT-005, A-05 R3); hộp thoại và lời gọi
//    tracecore.v1.codes.issue_rolls / list_rolls nằm ở tc_codes.js (tracecore.codes.issue_rolls_dialog,
//    roll_labels_dialog). Server kiểm Item là nhãn có phương pháp và số lượng.
//    "In nhãn cuộn": in lại mã CN- đã cấp (lần in trước lỗi, nhãn hỏng/mất), tối đa 50 mã mỗi lần.
// 2. Khai báo vật tư tiêu hao CSSD (SCR-24, FEAT-041, A-07 V1-V5): chọn nhóm thì hiện đúng các trường phụ thuộc và
//    tích sẵn cờ lô / hạn dùng / bình quân gia quyền. Mọi luật nằm ở server (tracecore.inventory.items); script này
//    chỉ cho người dùng thấy ngay kết quả luật sẽ áp, nên hai danh sách dưới đây phải trùng server (có test).
// 3. Nút "Đặt hạn lưu" cho Item nhóm Packaging (FEAT-015 Task 8, FR-M2-07.8, BRU-REP-009, S7): hộp thoại dùng chung
//    tracecore.shelf_life.dialog (tc_shelf_life.js) gọi tracecore.v1.set_type_admin.set_pack_shelf_life.

const TC_LABEL_GROUP = "Label";
const TC_CI_GROUP = "Chemical Indicator";
// nhóm bắt buộc có hạn dùng (inventory.items.EXPIRY_REQUIRED_GROUPS)
const TC_EXPIRY_REQUIRED_GROUPS = [
	"Chemical Indicator",
	"Biological Indicator",
	"Chemical",
	"Lubricant",
];
const TC_VALUATION_METHOD = "Moving Average";

function tc_item_has_stock(frm) {
	// ERPNext khóa cờ lô / định giá của Item đã có tồn; không mở khóa lại
	return Boolean(frm.doc.__onload && frm.doc.__onload.stock_exists);
}

// Trường nào hiện theo nhóm: phương pháp cho nhãn chỉ ở nhóm Nhãn, loại chỉ thị chỉ ở nhóm Chỉ thị hóa học
function tc_item_toggle_fields(frm) {
	const group = frm.doc.tc_item_group_cssd;
	frm.toggle_display("tc_compatible_method", group === TC_LABEL_GROUP);
	frm.toggle_display("tc_ci_class", group === TC_CI_GROUP);
	frm.toggle_reqd("tc_compatible_method", group === TC_LABEL_GROUP);
}

// Cờ lô / hạn dùng / định giá mà server sẽ tự đặt; khóa cờ hạn dùng khi nhóm bắt buộc hạn
function tc_item_apply_stock_flags(frm) {
	const group = frm.doc.tc_item_group_cssd;
	if (!group || frm.doc.docstatus !== 0 || tc_item_has_stock(frm)) {
		return;
	}
	const expiry_required = TC_EXPIRY_REQUIRED_GROUPS.includes(group);
	const wanted = {
		is_stock_item: 1,
		has_batch_no: 1,
		valuation_method: TC_VALUATION_METHOD,
	};
	if (expiry_required) {
		wanted.has_expiry_date = 1;
	}
	Object.keys(wanted).forEach((field) => {
		if (frm.doc[field] !== wanted[field]) {
			frm.set_value(field, wanted[field]);
		}
	});
	frm.set_df_property("has_batch_no", "read_only", 1);
	frm.set_df_property("has_expiry_date", "read_only", expiry_required ? 1 : 0);
	frm.set_df_property(
		"has_expiry_date",
		"description",
		expiry_required ? __("Required for this group") : ""
	);
}

// Tồn tối thiểu theo kho (bảng Reorder level) và nhà cung cấp hiện ngay, không nằm trong phần gập
function tc_item_show_stock_tables(frm) {
	if (!frm.doc.tc_item_group_cssd) {
		return;
	}
	["reorder_levels", "supplier_items"].forEach((fieldname) => {
		const field = frm.fields_dict[fieldname];
		if (field && field.df) {
			frm.set_df_property(fieldname, "hidden", 0);
			if (field.section) {
				field.section.expanded_by_user = true; // Frappe không gập lại ở lần vẽ lại sau
				if (field.section.is_collapsed()) {
					field.section.collapse(false);
				}
			}
		}
	});
}

function tc_item_refresh_cssd(frm) {
	tc_item_toggle_fields(frm);
	tc_item_apply_stock_flags(frm);
	tc_item_show_stock_tables(frm);
}

frappe.ui.form.on("Item", {
	refresh(frm) {
		tc_item_refresh_cssd(frm);
		if (frm.is_new() || !(window.tracecore && tracecore.codes)) {
			return;
		}
		if (frm.doc.tc_item_group_cssd === "Label" && tracecore.codes.can_print()) {
			frm.add_custom_button(__("Issue roll codes"), () =>
				tracecore.codes.issue_rolls_dialog(frm)
			);
			frm.add_custom_button(__("Print roll labels"), () =>
				tracecore.codes.roll_labels_dialog(frm)
			);
		}
		if (
			frm.doc.tc_item_group_cssd === "Packaging" &&
			tracecore.shelf_life &&
			tracecore.shelf_life.can_set()
		) {
			frm.add_custom_button(__("Set shelf life"), () =>
				tracecore.shelf_life.dialog({
					item: frm.doc.name,
					current_days: frm.doc.tc_shelf_life_days,
					on_saved: () => frm.reload_doc(),
				})
			);
		}
	},

	tc_item_group_cssd(frm) {
		const group = frm.doc.tc_item_group_cssd;
		// server chặn loại chỉ thị ngoài nhóm Chỉ thị hóa học; phương pháp chỉ có nghĩa với nhãn
		if (group !== TC_CI_GROUP && frm.doc.tc_ci_class) {
			frm.set_value("tc_ci_class", "");
		}
		if (group !== TC_LABEL_GROUP && frm.doc.tc_compatible_method) {
			frm.set_value("tc_compatible_method", "");
		}
		tc_item_refresh_cssd(frm);
	},
});
