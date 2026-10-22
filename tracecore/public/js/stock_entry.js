// Desk: form Stock Entry (ERPNext) loại Material Receipt = phiếu nhập kho vật tư theo lô/hạn (SCR-24, FEAT-041,
// A-07 V6). Gắn qua hook doctype_js. Chỉ trình bày: luật hạn dùng, lô, đơn giá nằm ở server
// (tracecore.inventory.receipt) và chạy cho cả Desk lẫn nhập Excel.

const TC_RECEIPT_PURPOSE = "Material Receipt";
// Trường chuyển kho / sản xuất / gia công không liên quan tới phiếu nhập; chỉ ẩn khi có trong form
const TC_RECEIPT_HIDDEN_FIELDS = [
	"from_warehouse",
	"from_bom",
	"bom_no",
	"use_multi_level_bom",
	"fg_completed_qty",
	"inspection_required",
	"work_order",
	"purchase_order",
	"subcontracting_order",
	"delivery_note_no",
	"sales_invoice_no",
	"pick_list",
];
const TC_RECEIPT_FIELDS = ["tc_supplier", "tc_document_no"];
const TC_RECEIPT_COLUMNS = ["tc_batch_id", "tc_expiry_date"];
const TC_TRANSFER_COLUMNS = ["s_warehouse"];

function tc_is_receipt(frm) {
	return (frm.doc.purpose || frm.doc.stock_entry_type) === TC_RECEIPT_PURPOSE;
}

// Hạn dùng trước hôm nay: chữ cam kèm ký hiệu và chữ "Expired", không chỉ màu (design.md, F-14)
function tc_expiry_formatter(value, df, options, doc) {
	const shown = frappe.form.formatters.Date(value, df, options, doc);
	if (value && value < frappe.datetime.get_today()) {
		return `<span style="color: var(--tc-warn-text); font-weight: var(--tc-fw-bold)"><span aria-hidden="true">!</span> ${shown} · ${__(
			"Expired",
			null,
			"Stock Entry Detail"
		)}</span>`;
	}
	return shown;
}

function tc_receipt_layout(frm) {
	const receipt = tc_is_receipt(frm);
	TC_RECEIPT_HIDDEN_FIELDS.forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, !receipt && Boolean(frm.doc[fieldname]));
		}
	});
	TC_RECEIPT_FIELDS.forEach((fieldname) => frm.toggle_display(fieldname, receipt));
	// NCC và số chứng từ nằm trong phần "Kho mặc định" (gập sẵn): mở ra để thấy ngay khi nhập kho
	const section = frm.fields_dict.to_warehouse && frm.fields_dict.to_warehouse.section;
	if (receipt && section) {
		// expanded_by_user: Frappe không gập lại phần này ở lần vẽ lại sau
		section.expanded_by_user = true;
		if (section.is_collapsed()) {
			section.collapse(false);
		}
	}
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (grid) {
		TC_RECEIPT_COLUMNS.forEach((fieldname) =>
			grid.update_docfield_property(fieldname, "hidden", receipt ? 0 : 1)
		);
		TC_TRANSFER_COLUMNS.forEach((fieldname) =>
			grid.update_docfield_property(fieldname, "hidden", receipt ? 1 : 0)
		);
		grid.update_docfield_property("tc_expiry_date", "formatter", tc_expiry_formatter);
		grid.reset_grid();
	}
}

// Trạng thái phiếu nhập luôn bằng chữ Nháp / Đã ghi sổ / Đã hủy (bản dịch chuẩn của Frappe "Đã lần gửi" khó hiểu)
function tc_receipt_indicator(frm) {
	if (!tc_is_receipt(frm) || frm.is_new() || frm.doc.__unsaved) {
		return;
	}
	const states = {
		0: [__("Draft", null, "Stock Entry"), "orange"],
		1: [__("Posted", null, "Stock Entry"), "green"],
		2: [__("Cancelled", null, "Stock Entry"), "red"],
	};
	const state = states[frm.doc.docstatus];
	if (state) {
		frm.page.set_indicator(state[0], state[1]);
	}
}

frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		tc_receipt_layout(frm);
		tc_receipt_indicator(frm);
		if (frm.is_new() && tc_is_receipt(frm) && !frm.doc.to_warehouse) {
			const warehouse = frappe.defaults.get_user_default("Warehouse");
			if (warehouse) {
				frm.set_value("to_warehouse", warehouse);
			}
		}
	},

	onload_post_render(frm) {
		// Frappe vẽ và gập các phần sau lần refresh đầu: vẽ lại bố cục khi form đã dựng xong
		tc_receipt_layout(frm);
	},

	stock_entry_type(frm) {
		tc_receipt_layout(frm);
	},

	purpose(frm) {
		tc_receipt_layout(frm);
	},

	validate(frm) {
		// server cắt khoảng trắng đầu/cuối mã lô; cắt trước để người dùng thấy đúng giá trị sẽ lưu
		(frm.doc.items || []).forEach((row) => {
			if (row.tc_batch_id && row.tc_batch_id !== row.tc_batch_id.trim()) {
				frappe.model.set_value(
					row.doctype,
					row.name,
					"tc_batch_id",
					row.tc_batch_id.trim()
				);
			}
		});
	},
});
