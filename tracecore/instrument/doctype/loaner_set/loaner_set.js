/* global tracecore */
// Desk: bộ mượn (SCR-04, FEAT-017, A-38; UC-04, FR-M1-07, FR-M1-08).
// Ghi sổ phiếu = nhận bộ (server tạo dụng cụ, loại bộ mượn, Set ID LN). Quy tắc nằm ở server
// (tracecore.instrument.loaner): JS chỉ hiện nút, thu thập giá trị và đưa lỗi chặn về dạng kết quả → lý do → hành
// động ngay trong hộp thoại. Role chỉ để hiện nút, server kiểm lại.

const TC_LOANER_API = "tracecore.v1.loaner.";

function tc_loaner_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_loaner_error_html(error) {
	const lines = [
		`<b>✕ ${tc_loaner_escape(error.title)}</b>`,
		tc_loaner_escape(error.reason),
		tc_loaner_escape(error.action),
	];
	(error.items || []).forEach((item) => {
		lines.push(`${tc_loaner_escape(item.row)}: ${tc_loaner_escape(item.instrument)}`);
	});
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

function tc_loaner_call(frm, dialog, method, args) {
	const button = dialog.get_primary_btn();
	button.prop("disabled", true);
	tracecore.desk_call({
		method: TC_LOANER_API + method,
		args: { name: frm.doc.name, ...args },
		on_ok: () => {
			button.prop("disabled", false);
			dialog.hide();
			frm.reload_doc();
		},
		on_block: (error) => {
			button.prop("disabled", false);
			dialog.fields_dict.error_html.$wrapper.html(tc_loaner_error_html(error));
		},
		on_fail: () => button.prop("disabled", false),
	});
}

function tc_loaner_return(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Return to vendor"),
		size: "large",
		fields: [
			{ fieldname: "error_html", fieldtype: "HTML" },
			{
				fieldname: "lines",
				label: __("Loaner BOM"),
				fieldtype: "Table",
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: true,
				data: (frm.doc.items || []).map((row) => ({
					idx: row.idx,
					instrument_name: row.instrument_name,
					qty: row.qty,
					returned_qty: row.qty,
					damaged_qty: 0,
					note: "",
				})),
				fields: [
					{
						fieldname: "instrument_name",
						label: __("Instrument Name"),
						fieldtype: "Data",
						read_only: 1,
						in_list_view: 1,
						columns: 4,
					},
					{
						fieldname: "qty",
						label: __("Qty"),
						fieldtype: "Int",
						read_only: 1,
						in_list_view: 1,
						columns: 1,
					},
					{
						fieldname: "returned_qty",
						label: __("Returned Qty"),
						fieldtype: "Int",
						in_list_view: 1,
						columns: 1,
					},
					{
						fieldname: "damaged_qty",
						label: __("Damaged Qty"),
						fieldtype: "Int",
						in_list_view: 1,
						columns: 1,
					},
					{
						fieldname: "note",
						label: __("Note"),
						fieldtype: "Data",
						in_list_view: 1,
						columns: 3,
					},
				],
			},
			{ fieldname: "note", label: __("Return Note"), fieldtype: "Small Text" },
		],
		primary_action_label: __("Return to vendor"),
		primary_action(values) {
			const lines = (values.lines || []).map((row) => ({
				idx: row.idx,
				returned_qty: row.returned_qty,
				damaged_qty: row.damaged_qty,
				note: row.note,
			}));
			tc_loaner_call(frm, dialog, "return_set", {
				lines: JSON.stringify(lines),
				note: values.note,
			});
		},
	});
	dialog.show();
}

function tc_loaner_extend(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Extend loan"),
		fields: [
			{ fieldname: "error_html", fieldtype: "HTML" },
			{
				fieldname: "expected_return",
				label: __("Expected Return"),
				fieldtype: "Date",
				default: frm.doc.expected_return,
				reqd: 1,
			},
			{
				fieldname: "reason",
				label: __("Extension Reason"),
				fieldtype: "Small Text",
				reqd: 1,
			},
		],
		primary_action_label: __("Extend loan"),
		primary_action(values) {
			tc_loaner_call(frm, dialog, "extend", values);
		},
	});
	dialog.show();
}

function tc_loaner_print(frm, format) {
	const query = new URLSearchParams({
		doctype: frm.doctype,
		name: frm.doc.name,
		format,
		no_letterhead: 1,
	});
	window.open(`/printview?${query.toString()}`, "_blank");
}

frappe.ui.form.on("Loaner Set", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		const group = __("Actions");
		if (frm.doc.status === "Received" && frappe.user.has_role("TC R02")) {
			frm.add_custom_button(__("Return to vendor"), () => tc_loaner_return(frm), group);
			frm.add_custom_button(__("Extend loan"), () => tc_loaner_extend(frm), group);
		}
		frm.add_custom_button(
			__("Loaner set receipt"),
			() => tc_loaner_print(frm, "TC Loaner Receipt"),
			__("Print")
		);
		if (frm.doc.status === "Returned") {
			frm.add_custom_button(
				__("Loaner set return note"),
				() => tc_loaner_print(frm, "TC Loaner Return"),
				__("Print")
			);
		}
		if (frm.doc.set_unit) {
			frm.add_custom_button(__("Open Set Unit"), () =>
				frappe.set_route("Form", "Set Unit", frm.doc.set_unit)
			);
		}
		if (
			frm.doc.status === "Received" &&
			frm.doc.expected_return < frappe.datetime.get_today()
		) {
			frm.dashboard.set_headline_alert(
				`<div class="alert alert-warning" role="alert">⚠ ${tc_loaner_escape(
					__("Overdue: the expected return date has passed.")
				)}</div>`
			);
		}
	},
});
