// Vật tư của chương trình ở T2, T5 và test đầu ngày (A-111; FR-M2-03.9, FR-M2-09.9, FR-M5-05.5, BRU-INV-003).
// Frappe nối file này trước station_t2.js, station_t5.js, station_daily_test.js (hook page_js). `lines` là
// `consumables` của chương trình trong RPC quét máy / tổng quan test: {item, item_name, role, is_required, uom, issued,
// per_load, per_pack, per_kg}. `state` là phiên nạp hoặc form test: {consumables_qty: {vật tư: chuỗi đã gõ},
// consumables_confirmed}. Server tính lại định mức và kiểm xác nhận khi Hoàn thành nạp / Bắt đầu test.

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

	reset(state) {
		if (!state) return;
		state.consumables_qty = {};
		state.consumables_confirmed = false;
	},

	// Thiếu xác nhận: có vật tư bắt buộc mà chưa tick, hoặc vật tư bắt buộc có số ≤ 0 / không phải số
	missing(state, lines, units) {
		const required = (lines || []).filter((line) => line.is_required);
		if (!required.length) return false;
		if (!(state && state.consumables_confirmed)) return true;
		return required.some((line) => !(this.qty(state, line, units) > 0));
	},

	payload(state) {
		return Object.entries((state && state.consumables_qty) || {})
			.filter(([, value]) => value !== "" && value !== undefined)
			.map(([item, value]) => ({ item, qty: Number(value) }));
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
			__("Norm for this run")
		)}</th><th>${esc(__("Actual quantity"))}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
			<p class="tc-hint">${esc(__("Leave the quantity empty to use the norm."))}</p>
			<label class="tc-t2-confirm"><input type="checkbox" id="${prefix}-consumables-ok" data-consumables-confirm="1"${
			confirmed ? " checked" : ""
		}> ${esc(__("Consumables are ready and the quantities are right"))}</label>
		</section>`;
	},
};
