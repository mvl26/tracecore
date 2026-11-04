// In PDF qua hộp thoại In của trình duyệt (A-114), dùng chung cho Desk và Page station (bundle Desk nạp ở cả hai).
// Máy chủ dựng PDF (nhãn khổ cuộn chung, giấy tờ A4); trình duyệt nạp PDF vào khung ẩn rồi gọi print(). Không mở được
// hộp thoại (bị chặn, thiếu trình xem PDF, quá thời gian) thì lưu file để người dùng tự mở in.
(function () {
	const PRINT_FRAME_WAIT_MS = 10000;
	const PRINT_FRAME_KEEP_MS = 60000; // xóa khung sớm thì hộp thoại In mất nội dung
	// khung 0 x 0 thay vì ẩn hẳn (display none): Chrome không in được khung bị ẩn hẳn
	const FRAME_STYLE = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";

	const pdfUrl = function (b64) {
		const bytes = Uint8Array.from(atob(b64), (char) => char.charCodeAt(0));
		return URL.createObjectURL(new Blob([bytes], { type: "application/pdf" }));
	};

	// A-99: lưu PDF (base64) thành file; A-114 chỉ còn là đường dự phòng khi không mở được hộp thoại In
	window.tcSavePdf = function (b64, filename) {
		const url = pdfUrl(b64);
		const link = document.createElement("a");
		link.href = url;
		link.download = filename;
		document.body.appendChild(link);
		link.click();
		link.remove();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	};

	// Trả Promise {dialog: true} khi đã mở hộp thoại In, {dialog: false} khi đã lưu file thay thế
	window.tcPrintPdf = function (b64, filename) {
		const url = pdfUrl(b64);
		const frame = document.createElement("iframe");
		frame.setAttribute("style", FRAME_STYLE);
		frame.setAttribute("aria-hidden", "true");
		frame.setAttribute("tabindex", "-1");
		const cleanup = () => {
			frame.remove();
			URL.revokeObjectURL(url);
		};
		return new Promise((resolve) => {
			let settled = false;
			const finish = (dialog) => {
				if (settled) return;
				settled = true;
				if (dialog) {
					setTimeout(cleanup, PRINT_FRAME_KEEP_MS);
				} else {
					cleanup();
					window.tcSavePdf(b64, filename);
				}
				resolve({ dialog });
			};
			frame.onload = () => {
				try {
					frame.contentWindow.focus();
					frame.contentWindow.print();
					finish(true);
				} catch (error) {
					finish(false);
				}
			};
			setTimeout(() => finish(false), PRINT_FRAME_WAIT_MS);
			frame.src = url;
			document.body.appendChild(frame);
		});
	};

	// Desk: báo kết quả in bằng thông báo ngắn của Frappe (thông tin, không phải lỗi chặn)
	window.tcPrintPdfAndTell = async function (res) {
		const printed = await window.tcPrintPdf(res.pdf_b64, res.filename);
		frappe.show_alert({
			message: printed.dialog
				? __("Label sent to the print dialog: {0}", [res.filename])
				: __("The print dialog did not open; the label was saved as PDF file {0}.", [res.filename]),
			indicator: printed.dialog ? "green" : "orange",
		});
		return printed;
	};
})();
