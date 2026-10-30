/* global esc */
// Component dùng chung "dòng cân" tc-weigh-line (FEAT-033, EI-HW-004, NFR-AVAIL-04); FEAT-047 (chất thải) dùng lại.
// Một ô kg + nút Lấy cân gọi station agent (GET /scale, hết giờ 2 giây). Cân không phản hồi thì nhập tay: ô kg ghi nguồn
// "Nhập tay" và phải tick xác nhận trước khi ghi sổ. Số hiển thị dùng dấu phẩy thập phân, chấp nhận cả dấu chấm khi gõ.
// Frappe nối file này sau station.js (hook page_js).

const TC_SCALE_URL = "http://127.0.0.1:8765/scale";
const TC_SCALE_TIMEOUT_MS = 2000;

class TcWeighLine {
	// Đọc cân qua agent: {ok: true, kg} hoặc {ok: false}; không bao giờ ném lỗi (cân là thiết bị ngoại vi tùy chọn)
	static async read(fetchImpl) {
		const call = fetchImpl || ((url, options) => fetch(url, options));
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), TC_SCALE_TIMEOUT_MS);
		try {
			const response = await call(TC_SCALE_URL, { signal: controller.signal });
			if (!response.ok) return { ok: false };
			const data = await response.json();
			const kg = Number(data && data.kg);
			return Number.isFinite(kg) && kg > 0 ? { ok: true, kg } : { ok: false };
		} catch (error) {
			return { ok: false };
		} finally {
			clearTimeout(timer);
		}
	}

	// "12,5" hoặc "12.5" thành 12.5; rỗng hoặc không phải số thành null
	static parse(text) {
		const value = String(text == null ? "" : text)
			.trim()
			.replace(",", ".");
		if (!value || !/^\d+(\.\d+)?$/.test(value)) return null;
		return Number(value);
	}

	// 12.5 thành "12,5" (3 chữ số lẻ tối đa, bỏ số 0 thừa)
	static format(kg) {
		if (kg == null || kg === "" || !Number.isFinite(Number(kg))) return "";
		return String(Math.round(Number(kg) * 1000) / 1000).replace(".", ",");
	}

	// Nguồn hiện trên dòng: Scale (đọc từ cân), Manual (gõ tay, cần xác nhận), Converted (suy ra từ số chiếc)
	static sourceLabel(source) {
		return (
			{
				Scale: __("From the scale"),
				Manual: __("Typed by hand"),
				Converted: __("Converted from pieces"),
			}[source] || ""
		);
	}

	// Markup của một dòng cân. state = {kg: "12,5", source, confirmed, error}; id là khóa dòng (data-row).
	// Nhãn nguồn, ô xác nhận và lỗi luôn có trong DOM (ẩn khi chưa cần) để `sync` cập nhật tại chỗ, không làm mất focus.
	static html(id, state) {
		const rid = esc(id);
		return `<div class="tc-weigh" data-row="${rid}">
			<label for="tc-weigh-kg-${rid}">${esc(__("Weight (kg)"))}</label>
			<div class="tc-weigh-input">
				<input id="tc-weigh-kg-${rid}" type="text" inputmode="decimal" autocomplete="off"
					data-field="weight_kg" data-row="${rid}" value="${esc(state.kg || "")}">
				<button type="button" class="tc-btn tc-btn-secondary" data-action="weigh" data-row="${rid}">${esc(
			__("Get weight")
		)}</button>
			</div>
			<p class="tc-weigh-source" data-role="source"></p>
			<label class="tc-weigh-confirm" data-role="confirm" hidden><input type="checkbox" data-field="confirmed" data-row="${rid}"> ${esc(
			__("I confirm the typed weight")
		)}</label>
			<p class="tc-field-error" data-role="error" role="alert" hidden></p>
		</div>`;
	}

	// Cập nhật nhãn nguồn, ô xác nhận và lỗi của dòng cân đang hiển thị (root = phần tử .tc-weigh)
	static sync(root, state) {
		if (!root) return;
		const label = TcWeighLine.sourceLabel(state.source);
		const source = root.querySelector('[data-role="source"]');
		source.textContent = label ? `⚖ ${label}` : "";
		source.hidden = !label;
		const confirm = root.querySelector('[data-role="confirm"]');
		const needsConfirm = state.source === "Manual" && Boolean(state.kg);
		confirm.hidden = !needsConfirm;
		confirm.querySelector("input").checked = Boolean(state.confirmed);
		const error = root.querySelector('[data-role="error"]');
		error.textContent = state.error || "";
		error.hidden = !state.error;
		root.querySelector("input[data-field=weight_kg]").classList.toggle(
			"is-error",
			Boolean(state.error)
		);
	}
}
