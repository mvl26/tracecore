/* global tracecore */
// Desk: hộp thoại "Đặt hạn lưu" của loại gói (FEAT-015 Task 8; FR-M2-07.8, BRU-REP-009, S7), dùng chung cho form Item
// (Item nhóm Packaging) và form loại bộ (loại gói mặc định). Nạp trên mọi trang Desk qua tracecore.bundle.js.
// Số ngày + lý do → tracecore.v1.set_type_admin.set_pack_shelf_life (R02/R10/System Manager; server kiểm role, Item là
// loại gói, số ngày, lý do). Chỉ áp cho gói đóng sau; kết quả liệt kê loại bộ có ghi đè không còn ngắn hơn (cảnh báo,
// không chặn). Một thao tác = một khóa X-Idempotency-Key (tracecore.codes.new_request), gửi lại sau lỗi mạng dùng đúng
// request cũ. Lỗi chặn: khối đỏ inline trong hộp thoại.

frappe.provide("tracecore.shelf_life");

const TC_SHELF_LIFE_RPC = "tracecore.v1.set_type_admin.set_pack_shelf_life";

// Chỉ để hiện nút; server (require_any_role) mới là nơi kiểm quyền
tracecore.shelf_life.ROLES = ["TC R02", "TC R10", "System Manager"];

tracecore.shelf_life.can_set = function () {
	return frappe.user.has_role(tracecore.shelf_life.ROLES);
};

function tc_shelf_life_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

async function tc_shelf_life_send(holder, args) {
	const signature = JSON.stringify(args);
	if (!holder.tc_pending || holder.tc_pending.signature !== signature) {
		holder.tc_pending = { signature, request: tracecore.codes.new_request(args) };
	}
	const result = await tracecore.codes.send(TC_SHELF_LIFE_RPC, holder.tc_pending.request);
	if (!result.network) {
		holder.tc_pending = null;
	}
	if (!result.ok && result.error && !result.error.code && !result.network) {
		result.error.action = __("Reload the page and try again.");
	}
	return result;
}

function tc_shelf_life_result(data, on_saved) {
	let message = `<p>${tc_shelf_life_escape(
		__("Shelf life of {0}: {1} → {2} days. It applies to packs packed from now on.", [
			data.item,
			data.old_days,
			data.new_days,
		])
	)}</p>`;
	const affected = data.affected_set_types || [];
	if (affected.length) {
		message += `<p>${tc_shelf_life_escape(
			__(
				"These set types override the shelf life with a value that is no longer shorter, so the pack type shelf life applies to them:"
			)
		)}</p><ul>${affected
			.map(
				(row) =>
					`<li><a href="/app/instrument-set-type/${encodeURIComponent(
						row.set_type
					)}"><span style="font-family: var(--tc-font-mono)">${tc_shelf_life_escape(
						row.set_type
					)}</span></a> ${tc_shelf_life_escape(
						__("override {0} days", [row.override])
					)}</li>`
			)
			.join("")}</ul>`;
	}
	frappe.msgprint({
		title: __("Shelf life saved"),
		indicator: affected.length ? "orange" : "green",
		message,
	});
	if (on_saved) {
		on_saved(data);
	}
}

// opts: {item: mã Item loại gói, current_days: hạn lưu hiện tại (hiển thị), on_saved(data)}
tracecore.shelf_life.dialog = function (opts) {
	const dialog = new frappe.ui.Dialog({
		title: __("Set shelf life of {0}", [opts.item]),
		fields: [
			{
				fieldname: "intro",
				fieldtype: "HTML",
				options: `<p class="text-muted">${tc_shelf_life_escape(
					__(
						"Current shelf life: {0} days. A new value applies only to packs packed after saving.",
						[opts.current_days || 0]
					)
				)}</p>`,
			},
			{
				fieldname: "days",
				fieldtype: "Int",
				label: __("Shelf life (days)"),
				default: opts.current_days || null,
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason for the change"),
				description: __("Required. Recorded in the audit log."),
			},
			{ fieldname: "tc_error", fieldtype: "HTML" },
		],
		primary_action_label: __("Save shelf life"),
		async primary_action(values) {
			const box = dialog.fields_dict.tc_error.$wrapper;
			box.empty();
			dialog.disable_primary_action();
			let result;
			try {
				result = await tc_shelf_life_send(dialog, {
					item: opts.item,
					days: values.days === undefined || values.days === null ? "" : values.days,
					reason: values.reason || "",
				});
			} finally {
				dialog.enable_primary_action();
			}
			if (result.ok) {
				dialog.hide();
				tc_shelf_life_result(result.data, opts.on_saved);
			} else {
				box.html(tracecore.codes.block_html(result.error));
			}
		},
	});
	dialog.show();
	return dialog;
};
