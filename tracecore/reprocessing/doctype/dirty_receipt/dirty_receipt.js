// Desk: phiếu tiếp nhận T1, xác nhận thành phần hiển thị theo từng bộ (FEAT-019; UC-05, FR-M2-23).
// Chỉ đổi cách xem bảng confirm_lines: dữ liệu và dịch vụ tiếp nhận giữ nguyên, xem gộp là bảng con gốc của Frappe.

const TC_RECEIPT_VIEW_SETS = "sets";
const TC_RECEIPT_VIEW_LIST = "list";

function tc_receipt_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_receipt_mono(text) {
	return `<span style="font-family: var(--tc-font-mono)">${tc_receipt_escape(text)}</span>`;
}

function tc_receipt_badge(text, fill) {
	return `<span style="padding: var(--tc-sp-0-5) var(--tc-sp-2); background: var(${fill}); border-radius: var(--tc-r-badge); color: var(--tc-text-inverse); font-size: var(--tc-fs-xs); font-weight: var(--tc-fw-bold); white-space: nowrap">${tc_receipt_escape(
		text
	)}</span>`;
}

// mỗi bộ theo thứ tự bảng items, dòng của bộ theo position
function tc_receipt_groups(doc) {
	const all_lines = doc.confirm_lines || [];
	return (doc.items || []).map((item) => {
		const lines = all_lines
			.filter((line) => line.set_unit === item.set_unit)
			.sort((a, b) => cint(a.position) - cint(b.position));
		return {
			item,
			lines,
			confirmed: lines.filter((line) => cint(line.confirmed)).length,
		};
	});
}

function tc_receipt_total_text(groups) {
	const confirmed = groups.reduce((total, group) => total + group.confirmed, 0);
	const lines = groups.reduce((total, group) => total + group.lines.length, 0);
	return __("{0} sets, {1}/{2} instruments confirmed", [groups.length, confirmed, lines]);
}

function tc_receipt_mark(line) {
	if (cint(line.confirmed)) {
		return `<span style="color: var(--tc-pass-text)">✓</span>`;
	}
	return `<span style="color: var(--tc-fail-text)">✗ ${tc_receipt_escape(__("Missing"))}</span>`;
}

function tc_receipt_table(lines) {
	if (!lines.length) {
		return "";
	}
	const rows = lines
		.map(
			(line) => `<tr>
				<td>${cint(line.position)}</td>
				<td>${tc_receipt_escape(line.instrument_name)} ${tc_receipt_mono(line.instrument)}</td>
				<td>${cint(line.qty)}</td>
				<td>${tc_receipt_mark(line)}</td>
			</tr>`
		)
		.join("");
	return `<table class="table table-bordered" style="margin: var(--tc-sp-2) 0 0">
		<thead><tr>
			<th>${tc_receipt_escape(__("No."))}</th>
			<th>${tc_receipt_escape(__("Instrument"))}</th>
			<th>${tc_receipt_escape(__("Qty"))}</th>
			<th>${tc_receipt_escape(__("Confirmation"))}</th>
		</tr></thead>
		<tbody>${rows}</tbody>
	</table>`;
}

function tc_receipt_set_html(group) {
	const { item, lines, confirmed } = group;
	const complete = lines.length > 0 && confirmed === lines.length;
	const count = tc_receipt_badge(
		__("{0}/{1} confirmed", [confirmed, lines.length]),
		complete ? "--tc-pass" : "--tc-warn-fill"
	);
	const review = cint(item.needs_review)
		? tc_receipt_badge(__("Needs Review", null, "Dirty Receipt Set"), "--tc-fail")
		: "";
	const note = item.abnormal_note
		? `<div style="margin-top: var(--tc-sp-1); color: var(--tc-fail-text)">${tc_receipt_escape(
				item.abnormal_note
		  )}</div>`
		: "";
	return `<details style="margin-bottom: var(--tc-sp-2); padding: var(--tc-sp-2) var(--tc-sp-3); border: var(--tc-bw-hair) solid var(--tc-line); border-radius: var(--tc-r-sm)">
		<summary style="cursor: pointer">
			<b>${tc_receipt_escape(item.set_name)}</b> ${tc_receipt_mono(item.set_unit)} ${count} ${review}
			${note}
		</summary>
		${tc_receipt_table(lines)}
	</details>`;
}

function tc_receipt_sets_html(doc) {
	return tc_receipt_groups(doc).map(tc_receipt_set_html).join("");
}

function tc_receipt_show(frm) {
	const { holder, view } = frm.tc_receipt;
	const groups = tc_receipt_groups(frm.doc);
	if (!groups.length) {
		holder.html("");
		frm.set_df_property("confirm_lines", "hidden", 0);
		return;
	}
	const by_set = view === TC_RECEIPT_VIEW_SETS;
	const label = by_set ? __("View combined list") : __("View by set");
	holder.html(`<div style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: var(--tc-sp-2); margin-bottom: var(--tc-sp-2)">
			<div><b>${tc_receipt_escape(__("Component Confirmations"))}</b>: ${tc_receipt_escape(
		tc_receipt_total_text(groups)
	)}</div>
			<button type="button" class="btn btn-default btn-xs" data-tc-receipt-toggle>${tc_receipt_escape(
				label
			)}</button>
		</div>
		${by_set ? tc_receipt_sets_html(frm.doc) : ""}`);
	frm.set_df_property("confirm_lines", "hidden", by_set ? 1 : 0);
}

function tc_receipt_render(frm) {
	if (!frm.tc_receipt) {
		const holder = $("<div>").insertBefore(frm.fields_dict.confirm_lines.wrapper);
		frm.tc_receipt = { holder };
		holder.on("click", "[data-tc-receipt-toggle]", () => {
			frm.tc_receipt.view =
				frm.tc_receipt.view === TC_RECEIPT_VIEW_SETS
					? TC_RECEIPT_VIEW_LIST
					: TC_RECEIPT_VIEW_SETS;
			tc_receipt_show(frm);
		});
	}
	// Frappe dùng lại frm khi mở phiếu khác: phiếu mới luôn bắt đầu ở xem theo bộ
	if (frm.tc_receipt.docname !== frm.docname) {
		frm.tc_receipt.docname = frm.docname;
		frm.tc_receipt.view = TC_RECEIPT_VIEW_SETS;
	}
	tc_receipt_show(frm);
}

frappe.ui.form.on("Dirty Receipt", {
	refresh: tc_receipt_render,
});
