/* global tracecore */
// Desk: nhóm GS1 của TraceCore Settings (A-76). Nhắc khi chưa khai mã doanh nghiệp, cảnh báo dải mã sắp hết, nút cấp bù
// GTIN-14 có màn xem trước. Dữ liệu và quy tắc ở server: tracecore.v1.gtin. Lỗi chặn: khối đỏ inline.

const TC_GS1_STATUS = "tracecore.v1.gtin.status";
const TC_GS1_PREVIEW = "tracecore.v1.gtin.backfill_preview";
const TC_GS1_BACKFILL = "tracecore.v1.gtin.backfill";

function tc_gs1_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_gs1_mono(text) {
	return `<span style="font-family: var(--tc-font-mono)">${tc_gs1_escape(text)}</span>`;
}

// RPC chỉ đọc là GET; frappe.xcall luôn POST
async function tc_gs1_get(method) {
	return (await frappe.call({ method, type: "GET" })).message;
}

function tc_gs1_block(error) {
	return tracecore.codes.block_html(error);
}

function tc_gs1_rows(rows) {
	const body = rows
		.map((row) => {
			let current = `<span class="text-muted">${tc_gs1_escape(__("None"))}</span>`;
			if (row.current_gtin) {
				const tag = row.pack_count
					? __("Test code, {0} packs labelled", [row.pack_count])
					: __("Test code");
				current = `${tc_gs1_mono(
					row.current_gtin
				)} <span class="indicator-pill orange">${tc_gs1_escape(tag)}</span>`;
			}
			return `<tr>
				<td>${tc_gs1_mono(row.set_type)}</td>
				<td>${tc_gs1_escape(row.set_type_name)}</td>
				<td>${current}</td>
				<td>${tc_gs1_mono(row.new_gtin)}</td>
			</tr>`;
		})
		.join("");
	return `<table class="table table-bordered table-sm">
		<thead><tr>
			<th>${tc_gs1_escape(__("Type Code"))}</th>
			<th>${tc_gs1_escape(__("Set Type Name"))}</th>
			<th>${tc_gs1_escape(__("Current GTIN"))}</th>
			<th>${tc_gs1_escape(__("New GTIN-14"))}</th>
		</tr></thead><tbody>${body}</tbody></table>`;
}

function tc_gs1_backfill_dialog(frm, preview) {
	const rows = preview.rows;
	const fields = [
		{
			fieldname: "intro",
			fieldtype: "HTML",
			options: `<p class="text-muted">${tc_gs1_escape(
				__(
					"Nothing is written until you confirm. A GTIN-14 printed on labels is very hard to change, so check that the company prefix {0} is the real one.",
					[preview.prefix]
				)
			)}</p>`,
		},
		{
			fieldname: "list",
			fieldtype: "HTML",
			options: rows.length
				? tc_gs1_rows(rows)
				: `<p>${tc_gs1_escape(__("No set type is waiting for a GTIN-14."))}</p>`,
		},
	];
	if (preview.needs_reason) {
		fields.push({
			fieldname: "reason",
			fieldtype: "Small Text",
			label: __("Reason for replacing the code on set types that have packs"),
			description: __("Required. Packs already labelled keep their old GTIN."),
		});
	}
	fields.push({ fieldname: "tc_error", fieldtype: "HTML" });
	const dialog = new frappe.ui.Dialog({
		title: __("Preview GTIN-14 issue ({0} set types)", [rows.length]),
		size: "extra-large",
		fields,
	});
	if (rows.length) {
		dialog.set_primary_action(__("Confirm {0} codes", [rows.length]), async (values) => {
			const args = {
				set_types: rows.map((row) => row.set_type),
				next_ref: preview.next_ref,
				reason: (values && values.reason) || "",
			};
			const signature = JSON.stringify(args);
			if (!dialog.tc_pending || dialog.tc_pending.signature !== signature) {
				dialog.tc_pending = { signature, request: tracecore.codes.new_request(args) };
			}
			const box = dialog.fields_dict.tc_error.$wrapper;
			box.empty();
			dialog.disable_primary_action();
			const result = await tracecore.codes.send(TC_GS1_BACKFILL, dialog.tc_pending.request);
			dialog.enable_primary_action();
			if (!result.network) {
				dialog.tc_pending = null;
			}
			if (!result.ok) {
				box.html(tc_gs1_block(result.error));
				return;
			}
			dialog.hide();
			frappe.show_alert({
				message: __("{0} GTIN-14 codes issued.", [result.data.issued]),
				indicator: "green",
			});
			frm.reload_doc();
		});
	}
	dialog.show();
}

async function tc_gs1_open_backfill(frm) {
	const box = frm.fields_dict.gs1_actions.$wrapper.find(".tc-gs1-error");
	box.empty();
	if (frm.is_dirty()) {
		box.html(
			tc_gs1_block({
				title: __("Preview not opened"),
				reason: __("This form has unsaved changes."),
				action: __("Save the form, then try again."),
			})
		);
		return;
	}
	const result = await tc_gs1_get(TC_GS1_PREVIEW);
	if (!result.ok) {
		box.html(tc_gs1_block(result.error));
		return;
	}
	tc_gs1_backfill_dialog(frm, result);
}

async function tc_gs1_refresh(frm) {
	const field = frm.fields_dict.gs1_actions;
	if (!field) {
		return;
	}
	const status = await tc_gs1_get(TC_GS1_STATUS);
	const notes = [];
	if (!status.prefix) {
		notes.push(
			__(
				"GS1 company prefix not declared. New set types do not get a GTIN-14 automatically; it can still be entered by hand."
			)
		);
	}
	if (status.range && status.range.low) {
		notes.push(
			__("GS1 item references are running low: {0} of {1} left (under 10 %).", [
				status.range.remaining,
				status.range.capacity,
			])
		);
	}
	frm.set_intro(notes.length ? notes.map(tc_gs1_escape).join("<br>") : "", "orange");
	field.$wrapper.empty();
	if (!status.can_manage) {
		return;
	}
	field.$wrapper.html(`<div class="tc-gs1-error"></div>
		<button type="button" class="btn btn-default btn-sm tc-gs1-open">${tc_gs1_escape(
			__("Issue GTIN-14 to set types without one")
		)}</button>`);
	field.$wrapper.find(".tc-gs1-open").on("click", () => tc_gs1_open_backfill(frm));
}

frappe.ui.form.on("TraceCore Settings", {
	refresh(frm) {
		tc_gs1_refresh(frm);
	},
});
