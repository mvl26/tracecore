/* global tracecore */
// Desk: form Set Unit (SCR-03, FEAT-016 Task 7; UC-03 bước 4-6, A2, E2; FR-M1-05.3, FR-M1-06, FR-M1-06.2).
// Ba tab Master Form: Thông tin (Set ID chữ to Courier New, trạng thái có chữ, đã dùng / tối đa / còn lại, Cycle ID hiệu
// lực, phiên bản BOM, trạng thái mã), Chi tiết (xem trước thẻ và nhãn khay, số lần in theo loại, quét kiểm tra thẻ, lệnh
// in đang chờ), Lịch sử (sự kiện vòng đời, phân trang "Xem thêm" theo next_before).
// Dữ liệu và quyền từ tracecore.v1.set_unit.form_context (nút theo permissions, RPC vẫn kiểm lại); giới hạn (độ dài lý
// do) lấy từ limits, không chép vào JS. Ghi (quét kiểm tra; in/in lại/hủy lệnh in qua tc_set_unit.js) dùng
// tracecore.codes.new_request/send: mỗi thao tác một khóa X-Idempotency-Key + client_ts, gửi lại sau lỗi mạng dùng đúng
// request cũ. Lỗi chặn: khối đỏ inline ngay tại chỗ thao tác (kết quả → lý do → hành động).

const TC_SU_FORM_PREVIEW = "tracecore.v1.set_unit.tag_preview";
const TC_SU_FORM_VERIFY = "tracecore.v1.set_unit.verify_tag";
const TC_SU_FORM_HISTORY = "tracecore.v1.set_unit.history";

function tc_su_form_ready() {
	return Boolean(window.tracecore && tracecore.codes && tracecore.set_unit);
}

function tc_su_form_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_su_form_mono(text) {
	return `<span style="font-family: var(--tc-font-mono)">${tc_su_form_escape(text)}</span>`;
}

function tc_su_form_muted(text) {
	return `<p class="text-muted">${tc_su_form_escape(text)}</p>`;
}

function tc_su_form_block(error) {
	if (window.tracecore && tracecore.codes) {
		return tracecore.codes.block_html(error);
	}
	return `<div class="alert alert-danger" role="alert"><p><strong>${tc_su_form_escape(
		error.title
	)}</strong></p><p>${tc_su_form_escape(error.reason)}</p><p>${tc_su_form_escape(
		error.action
	)}</p></div>`;
}

// Ảnh xem trước chỉ từ chuỗi base64 PNG do server trả; chuỗi khác → rỗng (hiện chữ thay ảnh)
function tc_su_png_src(b64) {
	return typeof b64 === "string" && /^[A-Za-z0-9+/]+=*$/.test(b64)
		? `data:image/png;base64,${b64}`
		: "";
}

function tc_su_form_kind_label(ctx, kind) {
	const row = (ctx.kinds || []).find((item) => item.kind === kind);
	return row ? row.label : kind;
}

// --- Thông tin --------------------------------------------------------------------------------------------------

function tc_su_form_row(label, value_html) {
	return `<tr><th style="width: 35%">${tc_su_form_escape(
		label
	)}</th><td>${value_html}</td></tr>`;
}

function tc_su_render_summary(frm, ctx) {
	const field = frm.fields_dict.summary_html;
	const s = ctx.summary;
	let cycles = __("Used {0} / Max {1} — Remaining {2}", [
		s.cycles_used,
		s.max_cycles,
		s.remaining,
	]);
	if (s.cycles_source === "Estimate") {
		cycles += ` (${__("Estimate")})`;
	}
	let bom = __("No BOM version in effect");
	if (s.bom_pinned) {
		bom = __("v{0} pinned", [s.cycle_bom_version]);
	} else if (s.bom_version_applied) {
		bom = __("v{0} — will be pinned at receiving", [s.bom_version_applied]);
	}
	const code = {
		Active: __("In use"),
		Disabled: __("Disabled permanently"),
	};
	let html = `<div style="font-family: var(--tc-font-mono); font-size: var(--tc-fs-2xl); font-weight: var(--tc-fw-bold); letter-spacing: var(--tc-ls-code)">${tc_su_form_escape(
		s.set_id
	)}</div><p>${tracecore.set_unit.status_html(s.status)}</p>`;
	if (ctx.test_labels) {
		html += `<div class="alert alert-warning" role="status">${tc_su_form_escape(
			__(
				"Test Set ID (GS1 demo prefix): its tag and tray label carry a TEST line. Do not fit them on real sets."
			)
		)}</div>`;
	}
	html += `<table class="table table-bordered table-sm"><tbody>
		${tc_su_form_row(
			__("Set type"),
			`${tc_su_form_mono(s.set_type)} ${tc_su_form_escape(s.set_type_name || "")}`
		)}
		${tc_su_form_row(__("Owning department"), tc_su_form_escape(s.department || "-"))}
		${tc_su_form_row(__("Cycles"), tc_su_form_escape(cycles))}
		${tc_su_form_row(
			__("Active Cycle ID"),
			s.active_cycle_id
				? tc_su_form_mono(s.active_cycle_id)
				: tc_su_form_escape(__("No active cycle"))
		)}
		${tc_su_form_row(__("Current station"), tc_su_form_escape(s.current_station || "-"))}
		${tc_su_form_row(__("BOM version"), tc_su_form_escape(bom))}
		${tc_su_form_row(
			__("Set ID code"),
			tc_su_form_escape(code[s.code_status] || __("Not registered in the code registry"))
		)}
	</tbody></table>`;
	field.$wrapper.html(html);
}

// --- Chi tiết: thẻ, nhãn khay, quét kiểm tra --------------------------------------------------------------------

function tc_su_counts_html(frm, ctx) {
	const counts = ctx.summary.print_counts || {};
	const rows = (ctx.kinds || [])
		.map((item) => {
			const c = counts[item.kind] || {};
			return `<tr>
				<td>${tc_su_form_escape(item.label)}</td>
				<td class="text-right">${tc_su_form_escape(c.printed || 0)}</td>
				<td class="text-right">${tc_su_form_escape(c.reprints || 0)}</td>
				<td class="text-right">${tc_su_form_escape(c.failed || 0)}</td>
				<td class="text-right">${tc_su_form_escape(c.pending || 0)}</td>
				<td>${tc_su_form_escape(tracecore.set_unit.datetime(c.last_printed_at) || "-")}</td>
			</tr>`;
		})
		.join("");
	return `<p><strong>${tc_su_form_escape(__("Print counts"))}</strong></p>
		<table class="table table-bordered table-sm">
			<thead><tr>
				<th>${tc_su_form_escape(__("Label kind"))}</th>
				<th class="text-right">${tc_su_form_escape(__("Printed"))}</th>
				<th class="text-right">${tc_su_form_escape(__("Reprints"))}</th>
				<th class="text-right">${tc_su_form_escape(__("Not printed"))}</th>
				<th class="text-right">${tc_su_form_escape(__("Pending"))}</th>
				<th>${tc_su_form_escape(__("Last printed"))}</th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>`;
}

// Lệnh in đang chờ (Queued/Waiting) chặn in mới cùng loại (TAG_PRINT_PENDING): báo và cho hủy khi bị kẹt
function tc_su_pending_html(ctx) {
	const counts = ctx.summary.print_counts || {};
	return (ctx.kinds || [])
		.map((item) => item.kind)
		.filter((kind) => counts[kind] && counts[kind].pending > 0)
		.map(
			(kind) =>
				`<div class="alert alert-warning" role="status"><p>${tc_su_form_escape(
					__("{0}: {1} print jobs still waiting to be printed.", [
						tc_su_form_kind_label(ctx, kind),
						counts[kind].pending,
					])
				)}</p>${
					ctx.permissions.can_print
						? `<p><button type="button" class="btn btn-default btn-sm tc-su-cancel" data-kind="${tc_su_form_escape(
								kind
						  )}">${tc_su_form_escape(__("Cancel pending print"))}</button></p>`
						: ""
				}</div>`
		)
		.join("");
}

function tc_su_verified_text(s) {
	if (!s.tag_verified_on) {
		return __("Tag not verified yet.");
	}
	return __("Verified on {0} by {1}.", [
		tracecore.set_unit.datetime(s.tag_verified_on),
		tracecore.set_unit.user(s.tag_verified_by),
	]);
}

function tc_su_verify_html(ctx) {
	if (!ctx.permissions.can_verify) {
		return "";
	}
	return `<p><strong>${tc_su_form_escape(__("Scan to verify the tag"))}</strong></p>
		<div class="form-inline">
			<input type="text" class="form-control tc-su-scan" autocomplete="off"
				style="font-family: var(--tc-font-mono); min-width: 50%"
				aria-label="${tc_su_form_escape(__("Scan to verify the tag"))}"
				placeholder="${tc_su_form_escape(__("Scan the DataMatrix on the tag"))}">
			<button type="button" class="btn btn-primary btn-sm ml-2 tc-su-verify">${tc_su_form_escape(
				__("Verify")
			)}</button>
			${
				ctx.permissions.can_reprint
					? `<button type="button" class="btn btn-default btn-sm ml-2 tc-su-faulty">${tc_su_form_escape(
							__("Faulty tag")
					  )}</button>`
					: ""
			}
		</div>
		<p class="tc-su-verified">${tc_su_form_escape(tc_su_verified_text(ctx.summary))}</p>
		<div class="tc-su-verify-result"></div>`;
}

function tc_su_render_tag(frm, ctx) {
	const field = frm.fields_dict.tag_html;
	let html = tc_su_verify_html(ctx) + tc_su_pending_html(ctx) + tc_su_counts_html(frm, ctx);
	if (ctx.permissions.can_print) {
		html += `<div class="row">${(ctx.kinds || [])
			.map(
				(item) => `<div class="col-sm-6">
					<p><strong>${tc_su_form_escape(item.label)}</strong></p>
					<div class="tc-su-preview" data-kind="${tc_su_form_escape(item.kind)}">${tc_su_form_muted(
					__("Loading label preview...")
				)}</div>
				</div>`
			)
			.join("")}</div>`;
	} else {
		html += tc_su_form_muted(__("Tag previews are shown to R02, R10 and the System Manager."));
	}
	field.$wrapper.html(html);
	field.$wrapper.find(".tc-su-verify").on("click", () => tc_su_verify(frm, ctx));
	field.$wrapper.find(".tc-su-scan").on("keydown", (event) => {
		if (event.key === "Enter") {
			event.preventDefault();
			tc_su_verify(frm, ctx);
		}
	});
	field.$wrapper.find(".tc-su-faulty").on("click", () =>
		tracecore.set_unit.reprint_dialog({
			set_unit: frm.doc.name,
			ctx,
			kind: "tag",
			reason: __("Faulty tag – unreadable"),
			on_done: () => tc_su_load(frm),
		})
	);
	field.$wrapper.find(".tc-su-cancel").on("click", (event) =>
		tracecore.set_unit.cancel_dialog({
			set_unit: frm.doc.name,
			ctx,
			kind: $(event.currentTarget).attr("data-kind"),
			on_done: () => tc_su_load(frm),
		})
	);
	if (ctx.permissions.can_print) {
		(ctx.kinds || []).forEach((item) => tc_su_load_preview(frm, ctx, item));
	}
}

async function tc_su_load_preview(frm, ctx, item) {
	const name = frm.doc.name;
	const result = await tracecore.codes.get(TC_SU_FORM_PREVIEW, {
		set_unit: name,
		kind: item.kind,
	});
	if (frm.doc.name !== name || frm.tc_su_ctx !== ctx) {
		return;
	}
	const box = frm.fields_dict.tag_html.$wrapper.find(
		`.tc-su-preview[data-kind="${item.kind.replace(/[^a-z]/g, "")}"]`
	);
	if (!result.ok) {
		box.html(tc_su_form_block(result.error));
		return;
	}
	const src = tc_su_png_src(result.data.png_b64);
	const alt = __("{0} preview of {1}: {2}", [item.label, name, result.data.hri || ""]);
	box.html(
		src
			? `<img src="${src}" alt="${tc_su_form_escape(
					alt
			  )}" class="img-fluid img-thumbnail"><p>${tc_su_form_mono(result.data.hri)}</p>`
			: tc_su_form_muted(alt)
	);
}

async function tc_su_verify(frm, ctx) {
	const wrapper = frm.fields_dict.tag_html.$wrapper;
	const input = wrapper.find(".tc-su-scan");
	const box = wrapper.find(".tc-su-verify-result");
	const raw = String(input.val() || "");
	if (!raw.trim()) {
		box.html(
			tc_su_form_block({
				title: __("Nothing scanned"),
				reason: __("The scan box is empty."),
				action: __("Scan the DataMatrix on the printed tag."),
			})
		);
		input.trigger("focus");
		return;
	}
	if (!tc_su_form_ready()) {
		box.html(
			tc_su_form_block({
				title: __("Not available"),
				reason: __("The TraceCore Desk script is not loaded."),
				action: __("Reload the page and try again."),
			})
		);
		return;
	}
	// một lần quét = một thao tác; lỗi mạng → quét lại cùng chuỗi gửi lại đúng request cũ
	const signature = raw;
	if (!frm.tc_su_verify_pending || frm.tc_su_verify_pending.signature !== signature) {
		frm.tc_su_verify_pending = {
			signature,
			request: tracecore.codes.new_request({ set_unit: frm.doc.name, raw }),
		};
	}
	const result = await tracecore.codes.send(TC_SU_FORM_VERIFY, frm.tc_su_verify_pending.request);
	if (!result.network) {
		frm.tc_su_verify_pending = null;
	}
	input.val("").trigger("focus");
	if (!result.ok) {
		box.html(tracecore.set_unit.error_html(result.error, ctx));
		return;
	}
	ctx.summary.tag_verified_on = result.data.verified_on;
	ctx.summary.tag_verified_by = frappe.session.user;
	wrapper.find(".tc-su-verified").text(tc_su_verified_text(ctx.summary));
	box.html(
		`<div class="alert alert-success" role="status">${tc_su_form_escape(
			__("Tag matches set {0}.", [frm.doc.name])
		)}</div>`
	);
}

// --- Lịch sử ----------------------------------------------------------------------------------------------------

function tc_su_event_kind(kind) {
	const labels = {
		audit: __("Lifecycle"),
		gate: __("Step gate"),
		print: __("Print job"),
		pack: __("Packing"),
	};
	return labels[kind] || kind;
}

function tc_su_history_rows(events) {
	return events
		.map(
			(event) => `<tr>
				<td>${tc_su_form_escape(tracecore.set_unit.datetime(event.at))}</td>
				<td>${tc_su_form_escape(tc_su_event_kind(event.kind))}</td>
				<td><strong>${tc_su_form_escape(event.title)}</strong></td>
				<td>${tc_su_form_escape(event.detail)}</td>
				<td>${tc_su_form_escape(tracecore.set_unit.user(event.user))}</td>
				<td>${tc_su_form_escape(event.reason || "")}</td>
			</tr>`
		)
		.join("");
}

async function tc_su_load_history(frm, before) {
	const field = frm.fields_dict.history_html;
	const name = frm.doc.name;
	if (!before) {
		field.$wrapper.html(tc_su_form_muted(__("Loading...")));
	}
	const args = { set_unit: name };
	if (before) {
		args.before = before;
	}
	const result = await tracecore.codes.get(TC_SU_FORM_HISTORY, args);
	if (frm.doc.name !== name) {
		return;
	}
	const more = field.$wrapper.find(".tc-su-more-box");
	if (!result.ok) {
		(before ? more : field.$wrapper).html(tc_su_form_block(result.error));
		return;
	}
	const events = result.data.events || [];
	if (!before) {
		if (!events.length) {
			field.$wrapper.html(tc_su_form_muted(__("No history yet.")));
			return;
		}
		field.$wrapper.html(`<table class="table table-bordered table-sm">
			<thead><tr>
				<th>${tc_su_form_escape(__("Time"))}</th>
				<th>${tc_su_form_escape(__("Event type"))}</th>
				<th>${tc_su_form_escape(__("Event"))}</th>
				<th>${tc_su_form_escape(__("Details"))}</th>
				<th>${tc_su_form_escape(__("User"))}</th>
				<th>${tc_su_form_escape(__("Reason"))}</th>
			</tr></thead>
			<tbody class="tc-su-history"></tbody>
		</table><div class="tc-su-more-box"></div>`);
	}
	field.$wrapper.find(".tc-su-history").append(tc_su_history_rows(events));
	const box = field.$wrapper.find(".tc-su-more-box");
	if (result.data.next_before) {
		box.html(
			`<button type="button" class="btn btn-default btn-sm tc-su-more">${tc_su_form_escape(
				__("Show more")
			)}</button>`
		);
		box.find(".tc-su-more").on("click", () =>
			tc_su_load_history(frm, result.data.next_before)
		);
	} else {
		box.html(tc_su_form_muted(__("End of history.")));
	}
}

// --- Nút theo quyền do server trả ---------------------------------------------------------------------------

// Chỉ gỡ nút do script này thêm (không xóa nút của Client Script khác)
function tc_su_add_button(frm, label, action, group) {
	frm.add_custom_button(label, action, group);
	(frm.tc_su_buttons || (frm.tc_su_buttons = [])).push([label, group]);
}

function tc_su_remove_buttons(frm) {
	(frm.tc_su_buttons || []).forEach(([label, group]) => frm.remove_custom_button(label, group));
	frm.tc_su_buttons = [];
}

function tc_su_buttons(frm, ctx) {
	const perms = ctx.permissions;
	const s = ctx.summary;
	const group = __("Print tags");
	const reload = () => tc_su_load(frm);
	const printable = s.status !== "Disposed" && s.code_status !== "Disabled";
	if (perms.can_print && printable) {
		tc_su_add_button(
			frm,
			__("Print"),
			() =>
				tracecore.set_unit.print_dialog({
					set_units: [frm.doc.name],
					ctx,
					on_done: reload,
				}),
			group
		);
	}
	if (perms.can_reprint && printable) {
		tc_su_add_button(
			frm,
			__("Reprint"),
			() =>
				tracecore.set_unit.reprint_dialog({
					set_unit: frm.doc.name,
					ctx,
					on_done: reload,
				}),
			group
		);
	}
}

function tc_su_render_state(frm, html) {
	["summary_html", "tag_html", "history_html"].forEach((fieldname) => {
		const field = frm.fields_dict[fieldname];
		if (field) {
			field.$wrapper.html(html);
		}
	});
}

async function tc_su_load(frm) {
	if (!tc_su_form_ready()) {
		tc_su_render_state(
			frm,
			tc_su_form_block({
				title: __("Not available"),
				reason: __("The TraceCore Desk script is not loaded."),
				action: __("Reload the page and try again."),
			})
		);
		return;
	}
	const token = (frm.tc_su_token = (frm.tc_su_token || 0) + 1);
	tc_su_render_state(frm, tc_su_form_muted(__("Loading...")));
	const result = await tracecore.set_unit.context(frm.doc.name);
	if (token !== frm.tc_su_token) {
		return; // form đã chuyển bản ghi hoặc đã tải lại
	}
	if (!result.ok) {
		tc_su_render_state(frm, tc_su_form_block(result.error));
		return;
	}
	const ctx = result.data;
	frm.tc_su_ctx = ctx;
	tc_su_remove_buttons(frm);
	tc_su_buttons(frm, ctx);
	tc_su_render_summary(frm, ctx);
	tc_su_render_tag(frm, ctx);
	tc_su_load_history(frm);
}

frappe.ui.form.on("Set Unit", {
	setup(frm) {
		// mở tab Chi tiết → con trỏ vào ô quét kiểm tra thẻ (máy quét gõ như bàn phím)
		frm.$wrapper.on("shown.bs.tab", (event) => {
			const target = String(
				$(event.target).attr("data-fieldname") || $(event.target).attr("href") || ""
			);
			if (target.includes("tab_details")) {
				frm.fields_dict.tag_html.$wrapper.find(".tc-su-scan").trigger("focus");
			}
		});
	},

	refresh(frm) {
		tc_su_remove_buttons(frm);
		if (frm.is_new()) {
			// Set Unit chỉ tạo qua "Cấp Set ID" (G4)
			tc_su_render_state(
				frm,
				tc_su_form_muted(__("Set units are created only with Issue Set IDs."))
			);
			return;
		}
		frm.disable_save();
		tc_su_load(frm);
	},
});
