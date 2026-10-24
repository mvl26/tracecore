/* global tracecore */
// Desk: danh sách Stock Entry — hai nút nhập kho vật tư (SCR-24, FEAT-041, FR-M6-01.2, FR-M9-11):
//  * "Nhập kho vật tư": mở phiếu Material Receipt mới;
//  * "Nhập từ Excel": hộp thoại tải mẫu, chọn file .xlsx riêng tư, "Kiểm tra file" (receipt_check, không ghi),
//    rồi "Ghi sổ" (receipt_import, tất cả hoặc không gì). Nút ghi sổ chỉ bật sau khi kiểm sạch ĐÚNG file đó; đổi file
//    hoặc kho mặc định thì tắt lại. Lỗi chặn là khối inline đỏ (kết quả → lý do → hành động), không toast/modal.
// Mọi kiểm tra nghiệp vụ (hạn, lô, NCC, kho) nằm ở server; script này chỉ gửi file và trình bày kết quả.
// Gọi RPC bằng tracecore.codes.send (tc_codes.js): đọc body lỗi 422 của IMPORT_ROWS_INVALID và gửi lại cùng khóa
// X-Idempotency-Key khi mất mạng.

frappe.provide("tracecore.inventory");

const TC_INV_TEMPLATE = "tracecore.v1.inventory.receipt_template";
const TC_INV_CHECK = "tracecore.v1.inventory.receipt_check";
const TC_INV_IMPORT = "tracecore.v1.inventory.receipt_import";
// nhập kho: R09, R06 (UC-24); Administrator có System Manager
tracecore.inventory.ROLES = ["TC R09", "TC R06", "System Manager"];

// CSS chỉ dùng biến --tc-* (R4); chèn một lần vì Desk không nạp CSS riêng của Page
const TC_INV_CSS = `
.tc-inv-alert {
	margin-top: var(--tc-sp-3);
	padding: var(--tc-sp-2-5) var(--tc-sp-3);
	border-left: var(--tc-bw-alert) solid var(--tc-info);
	border-radius: 0 var(--tc-r-sm) var(--tc-r-sm) 0;
	background: var(--tc-info-tint);
	color: var(--tc-text);
}
.tc-inv-alert p { margin: 0 0 var(--tc-sp-1); }
.tc-inv-alert-title { font-weight: var(--tc-fw-bold); }
.tc-inv-alert-error { background: var(--tc-fail-tint); border-left-color: var(--tc-fail); }
.tc-inv-alert-error .tc-inv-alert-title { color: var(--tc-fail-text); }
.tc-inv-alert-warn { background: var(--tc-warn-tint); border-left-color: var(--tc-warn); }
.tc-inv-alert-warn .tc-inv-alert-title { color: var(--tc-warn-text); }
.tc-inv-alert-ok { background: var(--tc-pass-tint); border-left-color: var(--tc-pass); }
.tc-inv-alert-ok .tc-inv-alert-title { color: var(--tc-pass-text); }
.tc-inv-table { width: 100%; margin: var(--tc-sp-2) 0; border-collapse: collapse; }
.tc-inv-table th, .tc-inv-table td {
	padding: var(--tc-sp-1) var(--tc-sp-2);
	border-bottom: var(--tc-bw-hair) solid var(--tc-border-row);
	text-align: left;
	vertical-align: top;
}
.tc-inv-table th { color: var(--tc-text-2); font-weight: var(--tc-fw-bold); }
.tc-inv-mono { font-family: var(--tc-font-mono); }
.tc-inv-hint { color: var(--tc-text-2); }
`;

function tc_inv_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_inv_can_receive() {
	return frappe.user.has_role(tracecore.inventory.ROLES);
}

// Tên cột người dùng thấy trong Excel (cùng bản dịch với tiêu đề file mẫu)
function tc_inv_column_label(field) {
	const labels = {
		item_code: __("Item code"),
		batch_id: __("Lot number"),
		expiry_date: __("Expiry date"),
		qty: __("Received quantity"),
		rate: __("Unit price"),
		supplier: __("Supplier name"),
		document_no: __("Supplier document number"),
		warehouse: __("Receiving warehouse"),
	};
	return labels[field] || field || "";
}

function tc_inv_alert(variant, mark, notice, extra = "") {
	const role = variant === "error" ? "alert" : "status";
	return `<div class="tc-inv-alert tc-inv-alert-${variant}" role="${role}">
		<p class="tc-inv-alert-title"><span aria-hidden="true">${mark}</span> ${tc_inv_escape(
		notice.title
	)}</p>
		${notice.reason ? `<p>${tc_inv_escape(notice.reason)}</p>` : ""}
		${extra}
		${notice.action ? `<p>${tc_inv_escape(notice.action)}</p>` : ""}
	</div>`;
}

// Bảng dòng lỗi: dòng Excel — cột — lý do (mọi dòng lỗi, theo số dòng nhìn thấy trong Excel)
function tc_inv_rows_table(items) {
	const body = items
		.map(
			(item) => `<tr>
			<td class="tc-inv-mono">${tc_inv_escape(item.row)}</td>
			<td>${tc_inv_escape(tc_inv_column_label(item.field))}</td>
			<td>${tc_inv_escape(item.reason)}</td>
		</tr>`
		)
		.join("");
	return `<table class="tc-inv-table">
		<thead><tr>
			<th>${tc_inv_escape(__("Excel row"))}</th>
			<th>${tc_inv_escape(__("Excel column"))}</th>
			<th>${tc_inv_escape(__("Problem"))}</th>
		</tr></thead>
		<tbody>${body}</tbody>
	</table>`;
}

// Cảnh báo không chặn (RATE_ZERO: đơn giá 0): cam, luôn có chữ "Warning" và ký hiệu
function tc_inv_warnings_html(warnings) {
	if (!warnings || !warnings.length) {
		return "";
	}
	const rows = warnings.map((warning) => ({
		row: warning.row,
		field: warning.code === "RATE_ZERO" ? "rate" : warning.field,
		reason: warning.reason,
	}));
	return tc_inv_alert(
		"warn",
		"!",
		{
			title: __("Warning", null, "Stock Entry"),
			reason: __("{0} row(s) are received with a warning. They are not blocked.", [
				rows.length,
			]),
		},
		tc_inv_rows_table(rows)
	);
}

function tc_inv_error_html(error) {
	const items = error.items && error.items.length ? tc_inv_rows_table(error.items) : "";
	return tc_inv_alert("error", "&#10005;", error, items);
}

tracecore.inventory.excel_dialog = function (listview) {
	const state = {
		file_url: null,
		file_name: null,
		checked: null, // "file_url|warehouse" đã kiểm sạch; chỉ khi khớp mới cho ghi sổ
		warnings: [],
		pending: null, // {signature, request}: lần ghi đang làm, gửi lại dùng đúng request cũ (cùng khóa)
		busy: false,
	};
	const signature = () => `${state.file_url || ""}|${dialog.get_value("warehouse") || ""}`;

	const dialog = new frappe.ui.Dialog({
		title: __("Import receipts from Excel"),
		size: "large",
		fields: [
			{
				fieldtype: "Button",
				fieldname: "download",
				label: __("Download template"),
				click: () => tc_inv_download_template(),
			},
			{
				fieldtype: "Link",
				fieldname: "warehouse",
				label: __("Default warehouse"),
				options: "Warehouse",
				description: __("Used for rows whose warehouse cell is empty."),
				get_query: () => ({ filters: { is_group: 0, disabled: 0 } }),
				change: () => sync(),
			},
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Button",
				fieldname: "choose",
				label: __("Choose Excel file"),
				click: () => choose_file(),
			},
			{ fieldtype: "HTML", fieldname: "file_info" },
			{ fieldtype: "HTML", fieldname: "result" },
		],
		primary_action_label: __("Post receipts"),
		primary_action: () => post(),
		secondary_action_label: __("Check file"),
		secondary_action: () => check(),
	});

	const result = () => dialog.get_field("result").$wrapper;

	function show(html) {
		result().html(html);
	}

	function idle_html() {
		return `<p class="tc-inv-hint">${tc_inv_escape(
			__("Download the template, fill it in and upload it again.")
		)}</p>`;
	}

	// Nút theo trạng thái: "Kiểm tra file" cần có file; "Ghi sổ" cần đã kiểm sạch đúng file + kho này
	function sync() {
		const has_file = Boolean(state.file_url);
		dialog
			.get_field("file_info")
			.$wrapper.html(
				has_file
					? `<p class="tc-inv-mono">${tc_inv_escape(state.file_name)}</p>`
					: `<p class="tc-inv-hint">${tc_inv_escape(__("No file chosen."))}</p>`
			);
		dialog.get_secondary_btn().prop("disabled", !has_file || state.busy);
		dialog.get_primary_btn().prop("disabled", state.checked !== signature() || state.busy);
	}

	function busy(on) {
		state.busy = on;
		sync();
	}

	function choose_file() {
		new frappe.ui.FileUploader({
			make_attachments_public: false,
			disable_file_browser: true,
			restrictions: { allowed_file_types: [".xlsx"], max_number_of_files: 1 },
			on_success: (file_doc) => {
				state.file_url = file_doc.file_url;
				state.file_name = file_doc.file_name;
				state.checked = null;
				state.pending = null;
				state.warnings = [];
				show(idle_html());
				sync();
			},
		});
	}

	async function check() {
		if (state.busy || !state.file_url) {
			return;
		}
		const key = signature();
		busy(true);
		show(`<p class="tc-inv-hint">${tc_inv_escape(__("Checking the file..."))}</p>`);
		const outcome = await tracecore.codes.send(TC_INV_CHECK, null, {
			file_url: state.file_url,
			warehouse: dialog.get_value("warehouse") || null,
		});
		state.busy = false;
		if (!outcome.ok) {
			state.checked = null;
			show(tc_inv_error_html(outcome.error));
			sync();
			return;
		}
		state.checked = key;
		state.warnings = outcome.data.warnings || [];
		show(
			tc_inv_alert("ok", "&#10003;", {
				title: __("The file is valid"),
				reason: __("{0} row(s) will be saved in {1} receipt(s).", [
					outcome.data.rows,
					outcome.data.documents,
				]),
				action: __("Choose Post receipts to save them."),
			}) + tc_inv_warnings_html(state.warnings)
		);
		sync();
	}

	async function post() {
		if (state.busy || state.checked !== signature()) {
			return;
		}
		const key = signature();
		if (!state.pending || state.pending.signature !== key) {
			// một lần ghi = một khóa; bấm lại (nhấp đúp, thử lại sau lỗi mạng) giữ nguyên request cũ
			state.pending = {
				signature: key,
				request: tracecore.codes.new_request({
					file_url: state.file_url,
					warehouse: dialog.get_value("warehouse") || null,
				}),
			};
		}
		busy(true);
		const outcome = await tracecore.codes.send(TC_INV_IMPORT, state.pending.request);
		state.busy = false;
		if (!outcome.ok) {
			if (!outcome.network) {
				// server đã trả lời từ chối: kiểm lại rồi mới ghi lại, bằng khóa mới
				state.pending = null;
				state.checked = null;
			}
			show(tc_inv_error_html(outcome.error));
			sync();
			return;
		}
		state.pending = null;
		state.checked = null;
		state.file_url = null;
		state.file_name = null;
		const links = (outcome.data.stock_entries || [])
			.map(
				(name) =>
					`<li><a href="${frappe.utils.get_form_link(
						"Stock Entry",
						name
					)}" class="tc-inv-mono">${tc_inv_escape(name)}</a></li>`
			)
			.join("");
		show(
			tc_inv_alert(
				"ok",
				"&#10003;",
				{
					title: __("Receipts saved"),
					reason: __("{0} row(s) saved in {1} receipt(s).", [
						outcome.data.rows,
						(outcome.data.stock_entries || []).length,
					]),
				},
				`<ul>${links}</ul>`
			) + tc_inv_warnings_html(outcome.data.warnings)
		);
		sync();
		if (listview) {
			listview.refresh();
		}
	}

	dialog.show();
	show(idle_html());
	sync();
	return dialog;
};

function tc_inv_download_template() {
	// GET nhị phân; cookie phiên đi kèm, quyền kiểm ở server
	const link = document.createElement("a");
	link.href = `/api/method/${TC_INV_TEMPLATE}`;
	link.download = "";
	document.body.appendChild(link);
	link.click();
	link.remove();
}

function tc_inv_new_receipt() {
	const values = {
		stock_entry_type: "Material Receipt",
		purpose: "Material Receipt",
		posting_date: frappe.datetime.get_today(),
	};
	const warehouse = frappe.defaults.get_user_default("Warehouse");
	if (warehouse) {
		values.to_warehouse = warehouse;
	}
	frappe.new_doc("Stock Entry", values);
}

// ERPNext cũng đặt frappe.listview_settings["Stock Entry"]: gộp, giữ onload cũ
const tc_inv_previous = frappe.listview_settings["Stock Entry"] || {};
frappe.listview_settings["Stock Entry"] = Object.assign({}, tc_inv_previous, {
	onload(listview) {
		if (tc_inv_previous.onload) {
			tc_inv_previous.onload(listview);
		}
		frappe.dom.set_style(TC_INV_CSS, "tc-inventory-style");
		if (!tc_inv_can_receive()) {
			return;
		}
		listview.page.add_inner_button(__("Receive supplies"), tc_inv_new_receipt);
		listview.page.add_inner_button(__("Import from Excel"), () =>
			tracecore.inventory.excel_dialog(listview)
		);
	},
});
