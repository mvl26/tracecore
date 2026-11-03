// Vật tư của chương trình ở T2, T5 và test đầu ngày (A-111; FR-M2-03.9, FR-M2-09.9, FR-M5-05.5, BRU-INV-003).
// Frappe nối file này trước station_t2.js, station_t5.js, station_daily_test.js (hook page_js). `lines` là
// `consumables` của chương trình trong RPC quét máy / tổng quan test: {item, item_name, role, is_required, uom, issued,
// per_load, per_pack, per_kg, lots}. `state` là phiên nạp hoặc form test: {consumables_qty: {vật tư: chuỗi đã gõ},
// consumables_lot: {vật tư: lô đã gõ/quét/chọn}, consumables_confirmed}. Server tính lại định mức, kiểm lô và kiểm xác
// nhận khi Hoàn thành nạp / Bắt đầu test.
// A-112 (FR-M6-03.6): cột Lô gõ, quét hoặc chọn từ `lots` (còn hạn, còn tồn, hết hạn trước); mặc định lô đầu tiên.

const TC_NEAR_EXPIRY_DAYS = 30; // cùng ngưỡng của core.lots

window.TcRunConsumables = {
	// cùng ngữ cảnh DocType với cột Vai trò trên Desk (tránh trùng bản dịch chung của app khác)
	roleLabel(role) {
		return role ? __(role, null, "Program Consumable") : "";
	},

	norm(line, units) {
		const value = Number(line.per_load || 0) + Number(line.per_pack || 0) * Number(units || 0);
		return Math.round(value * 1e6) / 1e6;
	},

	qty(state, line, units) {
		const typed = ((state && state.consumables_qty) || {})[line.item];
		if (typed === undefined || typed === "") return this.norm(line, units);
		const value = Number(typed);
		return Number.isFinite(value) ? value : NaN;
	},

	// lô của dòng: đã gõ/quét/chọn, ngược lại lô FEFO đầu tiên (server cũng lấy lô này khi không gửi)
	lot(state, line) {
		const typed = ((state && state.consumables_lot) || {})[line.item];
		if (typed) return typed;
		return ((line.lots || [])[0] || {}).batch || "";
	},

	reset(state) {
		if (!state) return;
		state.consumables_qty = {};
		state.consumables_lot = {};
		state.consumables_confirmed = false;
	},

	// ghi ô số thực dùng hoặc ô lô vào `state`; trả true khi `target` là một trong hai ô đó
	remember(state, target) {
		if (target.dataset.consumable) {
			state.consumables_qty = state.consumables_qty || {};
			state.consumables_qty[target.dataset.consumable] = target.value;
			return true;
		}
		if (target.dataset.consumableLot) {
			state.consumables_lot = state.consumables_lot || {};
			state.consumables_lot[target.dataset.consumableLot] = target.value.trim();
			return true;
		}
		return false;
	},

	// Thiếu xác nhận: có vật tư bắt buộc mà chưa tick, hoặc vật tư bắt buộc có số ≤ 0 / không phải số
	missing(state, lines, units) {
		const required = (lines || []).filter((line) => line.is_required);
		if (!required.length) return false;
		if (!(state && state.consumables_confirmed)) return true;
		return required.some((line) => !(this.qty(state, line, units) > 0));
	},

	payload(state) {
		const rows = {};
		Object.entries((state && state.consumables_qty) || {})
			.filter(([, value]) => value !== "" && value !== undefined)
			.forEach(([item, value]) => (rows[item] = { item, qty: Number(value) }));
		Object.entries((state && state.consumables_lot) || {})
			.filter(([, value]) => value)
			.forEach(([item, batch]) => (rows[item] = { ...(rows[item] || { item }), batch }));
		return Object.values(rows);
	},

	// hạn và nhãn cảnh báo của lô đang chọn: Sắp hết hạn, Hết tồn (không chặn, A-112 E2)
	lotNote(line, batch) {
		const esc = frappe.utils.escape_html;
		const found = (line.lots || []).find((row) => row.batch === batch);
		if (!found) {
			return batch
				? `<span class="tc-badge tc-badge-o"><span aria-hidden="true">! </span>${esc(
						__("Not in the suggested lots: checked on save")
				  )}</span>`
				: `<span class="tc-badge tc-badge-o"><span aria-hidden="true">! </span>${esc(
						__("Out of stock")
				  )}</span>`;
		}
		const expiry = found.expiry_date ? frappe.datetime.str_to_user(found.expiry_date) : "-";
		const days = found.expiry_date
			? frappe.datetime.get_day_diff(found.expiry_date, frappe.datetime.get_today())
			: null;
		const soon =
			days !== null && days <= TC_NEAR_EXPIRY_DAYS
				? ` <span class="tc-badge tc-badge-o"><span aria-hidden="true">! </span>${esc(
						__("Expires soon")
				  )}</span>`
				: "";
		return `${esc(__("Expiry {0}", [expiry]))}${soon}`;
	},

	lotCell(state, line) {
		const esc = frappe.utils.escape_html;
		const batch = this.lot(state, line);
		const list = `tc-lots-${String(line.item).replace(/[^A-Za-z0-9_-]/g, "_")}`;
		const options = (line.lots || [])
			.map(
				(row) =>
					`<option value="${esc(row.batch)}">${esc(
						__("Expiry {0} · stock {1}", [
							row.expiry_date ? frappe.datetime.str_to_user(row.expiry_date) : "-",
							String(row.qty),
						])
					)}</option>`
			)
			.join("");
		return `<input type="text" autocomplete="off" class="tc-mono" list="${list}"
				data-consumable-lot="${esc(line.item)}" aria-label="${esc(
			__("Lot of {0}", [line.item_name || line.item])
		)}" value="${esc(batch)}">
			<datalist id="${list}">${options}</datalist>
			<div class="tc-hint">${this.lotNote(line, batch)}</div>`;
	},

	html(state, lines, units, prefix, title) {
		if (!(lines || []).length) return "";
		const esc = frappe.utils.escape_html;
		const rows = lines
			.map((line) => {
				const typed = ((state && state.consumables_qty) || {})[line.item];
				const norm = this.norm(line, units);
				const tags = [
					line.is_required
						? `<span class="tc-badge tc-badge-o"><span aria-hidden="true">! </span>${esc(
								__("Required", null, "Program Consumable")
						  )}</span>`
						: "",
					line.issued
						? ""
						: `<span class="tc-badge">${esc(
								__("Reminder only, not deducted")
						  )}</span>`,
				].join(" ");
				return `<tr>
					<td><b>${esc(line.item_name || line.item)}</b><br><span class="tc-mono">${esc(
					line.item
				)}</span> · ${esc(this.roleLabel(line.role))} ${tags}</td>
					<td>${this.lotCell(state, line)}</td>
					<td>${esc(window.tcDecimal ? window.tcDecimal(norm) : String(norm))} ${esc(line.uom || "")}</td>
					<td><input type="number" min="0" step="any" inputmode="decimal" class="tc-t1-actual"
						data-consumable="${esc(line.item)}" aria-label="${esc(
					__("Actual quantity of {0}", [line.item_name || line.item])
				)}" value="${esc(typed === undefined ? "" : typed)}" placeholder="${esc(
					String(norm)
				)}"></td>
				</tr>`;
			})
			.join("");
		const confirmed = Boolean(state && state.consumables_confirmed);
		return `<section class="tc-t4-block tc-run-consumables" aria-label="${esc(title)}">
			<h3>${esc(title)}</h3>
			<table class="tc-t2-table">
				<thead><tr><th>${esc(__("Item", null, "Run Consumable"))}</th><th>${esc(
			__("Lot", null, "Run Consumable")
		)}</th><th>${esc(__("Norm for this run"))}</th><th>${esc(
			__("Actual quantity")
		)}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
			<p class="tc-hint">${esc(
				__(
					"Leave the quantity empty to use the norm. Scan or choose the lot; the earliest expiry is suggested."
				)
			)}</p>
			<label class="tc-t2-confirm"><input type="checkbox" id="${prefix}-consumables-ok" data-consumables-confirm="1"${
			confirmed ? " checked" : ""
		}> ${esc(__("Consumables are ready and the quantities are right"))}</label>
		</section>`;
	},
};
