/* global tracecore */
// Desk: lệnh thu hồi (SCR-14, FEAT-029; UC-14, FR-M2-20, WF-05).
// Quy tắc nằm ở server (tracecore.reprocessing.recall): ai xác nhận dòng nào, đóng khi đủ 100 % gói. JS chỉ hiện nút,
// thu thập giá trị và đưa lỗi chặn về dạng kết quả → lý do → hành động ngay trong hộp thoại hoặc khối đỏ trên form.

const TC_RECALL_API = "tracecore.v1.recall.";

function tc_recall_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

// lỗi chặn: kết quả (đậm) → lý do → hành động, màu đỏ toàn khối
function tc_recall_error_html(error) {
	const lines = [
		`<b>✕ ${tc_recall_escape(error.title)}</b>`,
		tc_recall_escape(error.reason),
		tc_recall_escape(error.action),
	];
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

function tc_recall_call(frm, method, args, show_error, done) {
	// tracecore.desk_call: body ok: false đi kèm HTTP 409/422 nên phải đọc cả nhánh lỗi của frappe.call
	tracecore.desk_call({
		method: TC_RECALL_API + method,
		args: { recall: frm.doc.name, ...args },
		on_ok: () => {
			if (done) {
				done();
			}
			frm.reload_doc();
		},
		on_block: (error) => show_error(tc_recall_error_html(error)),
	});
}

function tc_recall_confirm(frm) {
	const pending = (frm.doc.packs || []).filter((row) => row.line_status !== "Confirmed");
	const dialog = new frappe.ui.Dialog({
		title: __("Confirm pack"),
		fields: [
			{ fieldname: "error_html", fieldtype: "HTML" },
			{
				fieldname: "pack",
				label: __("Pack"),
				fieldtype: "Select",
				options: pending.map((row) => ({
					value: row.pack,
					label: `${row.pack} · ${__(row.action, null, "Recall Order Pack")}`,
				})),
				reqd: 1,
			},
			{ fieldname: "note", label: __("Note", null, "Station"), fieldtype: "Small Text" },
		],
		primary_action_label: __("Confirm"),
		primary_action(values) {
			dialog.get_primary_btn().prop("disabled", true);
			tc_recall_call(
				frm,
				"confirm_pack",
				{ pack: values.pack, note: values.note },
				(html) => {
					dialog.get_primary_btn().prop("disabled", false);
					dialog.fields_dict.error_html.$wrapper.html(html);
				},
				() => dialog.hide()
			);
		},
	});
	dialog.show();
}

function tc_recall_dashboard(frm) {
	frm.dashboard.clear_headline();
	if (frm.is_new()) {
		return;
	}
	if (frm.doc.status === "Closed") {
		frm.dashboard.set_headline_alert(
			tc_recall_escape(__("Closed: every pack was confirmed")),
			"green"
		);
		return;
	}
	const text = __("{0} of {1} pack(s) confirmed", [
		frm.doc.confirmed_count || 0,
		frm.doc.pack_count || 0,
	]);
	frm.dashboard.set_headline_alert(tc_recall_escape(text), "orange");
}

frappe.ui.form.on("Recall Order", {
	refresh(frm) {
		tc_recall_dashboard(frm);
		if (frm.is_new() || frm.doc.docstatus !== 0) {
			return;
		}
		const show_error = (html) => frm.dashboard.set_headline_alert(html);
		if ((frm.doc.packs || []).some((row) => row.line_status !== "Confirmed")) {
			frm.add_custom_button(__("Confirm pack"), () => tc_recall_confirm(frm));
		}
		frm.add_custom_button(__("Close recall"), () =>
			tc_recall_call(frm, "close", {}, show_error)
		);
	},
});
