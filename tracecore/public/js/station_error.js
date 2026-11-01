/* global esc, clientTs */
// Khung mã lỗi (FEAT-052, A-71, FR-M9-19): tiêu đề "[Mã] – Tên – đối tượng" và nút mở Hướng dẫn xử lý, dùng chung mọi màn trạm.
// Hướng dẫn hiện inline ngay dưới khối lỗi; bản đã tải giữ lại trong trình duyệt để mở được khi mất mạng.
(function () {
	const CACHE_PREFIX = "tc_error_guide_";
	const escape = (value) => frappe.utils.escape_html(value == null ? "" : String(value));

	// A-99: lưu PDF nhãn máy chủ trả về (base64) thành file trên máy trạm
	window.tcSavePdf = function (b64, filename) {
		const bytes = Uint8Array.from(atob(b64), (char) => char.charCodeAt(0));
		const url = URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
		const link = document.createElement("a");
		link.href = url;
		link.download = filename;
		document.body.appendChild(link);
		link.click();
		link.remove();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	};

	// A-101: lấy PDF nhãn từ máy chủ rồi lưu một file; không ném lỗi. Trả {ok, filename, res} hoặc {ok: false, reason}.
	// Phiên trạm vừa kết thúc → {ended: true}: màn đã đổi, không báo gì thêm.
	window.tcPrintLabelPdf = async function (station, method, args) {
		let res = null;
		try {
			res = await station.rpcRead(method, { ...args, client_ts: clientTs() });
			if (res && res.ok && res.pdf_b64) {
				window.tcSavePdf(res.pdf_b64, res.filename);
				return { ok: true, filename: res.filename, res };
			}
		} catch (error) {
			if (error.sessionEnded) return { ok: false, ended: true };
			return { ok: false, reason: station.failureCause(error) };
		}
		return { ok: false, reason: station.failureCause(null, res) };
	};

	// A-101: nút In lại của khối cảnh báo khi chưa tạo được PDF
	window.tcPdfRetryButton = function (action, disabled) {
		return `<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-action="${esc(
			action
		)}"${disabled ? " disabled" : ""}>${esc(__("Print again"))}</button></div>`;
	};

	// #1832 cho mọi màn: nhãn liên kết của ô quét luôn theo placeholder mà màn đang đặt
	window.tcBindScanLabel = function (input) {
		const sync = () => {
			for (const label of input.labels || []) label.textContent = input.placeholder;
		};
		sync();
		new MutationObserver(sync).observe(input, {
			attributes: true,
			attributeFilter: ["placeholder"],
		});
	};

	// Dấu phẩy thập phân khi hiển thị số (CLAUDE.md); máy chủ nhận cả phẩy nên ô điền sẵn gửi lại nguyên chuỗi được
	window.tcDecimal = function (value) {
		if (value === null || value === undefined) return "";
		return String(value).replace(/^(-?\d+)\.(\d+)$/, "$1,$2");
	};

	window.tcErrorTitle = function (notice) {
		if (!notice || !notice.error_code) return (notice && notice.title) || "";
		const parts = [`[${notice.error_code}]`, notice.error_name || notice.title];
		if (notice.object_label) parts.push(notice.object_label);
		return parts.join(" – ");
	};

	window.tcGuideButton = function (notice) {
		if (!notice || !notice.error_code || !notice.has_guide) return "";
		return `<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-tc-guide="${escape(
			notice.error_code
		)}">${escape(
			__("Open handling guide")
		)}</button></div><div class="tc-error-guide" hidden></div>`;
	};

	window.tcWarningsHtml = function (warnings) {
		if (!warnings || !warnings.length) return "";
		return warnings
			.map(
				(warning) => `<div class="tc-alert tc-alert-warn" role="status">
					<p class="tc-alert-title"><span aria-hidden="true">!</span> ${escape(
						window.tcErrorTitle(warning)
					)}</p>
					${warning.reason ? `<p class="tc-alert-reason">${escape(warning.reason)}</p>` : ""}
					${window.tcGuideButton(warning)}
				</div>`
			)
			.join("");
	};

	function cached(code) {
		try {
			return window.localStorage.getItem(CACHE_PREFIX + code);
		} catch (error) {
			return null;
		}
	}

	function remember(code, html) {
		try {
			window.localStorage.setItem(CACHE_PREFIX + code, html);
		} catch (error) {
			// Bộ nhớ bị tắt trên PDA quản lý: chỉ mất khả năng xem khi mất mạng.
		}
	}

	async function load(code) {
		const query = new URLSearchParams({ error_code: code });
		const response = await fetch(`/api/method/tracecore.v1.error_code.guide?${query}`, {
			headers: { Accept: "application/json" },
		});
		const body = await response.json();
		if (!body.message || !body.message.ok) throw new Error("guide");
		remember(code, body.message.guide_html);
		return body.message.guide_html;
	}

	document.addEventListener("click", async (event) => {
		const button = event.target.closest && event.target.closest("[data-tc-guide]");
		if (!button) return;
		const panel = button.parentElement.nextElementSibling;
		if (!panel) return;
		if (!panel.hidden) {
			panel.hidden = true;
			return;
		}
		const code = button.getAttribute("data-tc-guide");
		panel.hidden = false;
		panel.textContent = __("Loading...");
		try {
			// guide_html đã được server sanitize
			panel.innerHTML = await load(code);
		} catch (error) {
			const saved = cached(code);
			if (saved) panel.innerHTML = saved;
			else panel.textContent = __("The guide cannot be opened while offline. Call R02.");
		}
	});
})();
