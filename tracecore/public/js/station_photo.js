/* global uuid4, clientTs */
// A-159: ảnh của màn trạm (T2 bản in/biểu đồ và ảnh chỉ thị, T3 ảnh hư hỏng, T5 bản in chu trình, test hằng ngày) tải
// qua RPC phiên thẻ `tracecore.v1.station.upload_photo`, không qua `/api/method/upload_file` của Desk (403 khi cookie
// Desk đã về Guest mà phiên thẻ vẫn còn — ticket 13/11/2026). Frappe nối file này trước các màn đó (hook page_js).
// Ảnh thu nhỏ ≤ 1600 px, JPEG như ảnh bất thường T1, để nằm trong giới hạn 5 MB của server.

const TC_PHOTO_METHOD = "tracecore.v1.station.upload_photo";
const TC_PHOTO_MAX_EDGE = 1600;

window.TcStationPhoto = {
	METHOD: TC_PHOTO_METHOD,

	shrink(file) {
		return new Promise((resolve, reject) => {
			const url = URL.createObjectURL(file);
			const image = new Image();
			image.onload = () => {
				const scale = Math.min(1, TC_PHOTO_MAX_EDGE / Math.max(image.width, image.height));
				const canvas = document.createElement("canvas");
				canvas.width = Math.max(1, Math.round(image.width * scale));
				canvas.height = Math.max(1, Math.round(image.height * scale));
				canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
				URL.revokeObjectURL(url);
				resolve(canvas.toDataURL("image/jpeg", 0.85).split(",")[1]);
			};
			image.onerror = () => {
				URL.revokeObjectURL(url);
				reject(new Error("unreadable"));
			};
			image.src = url;
		});
	},

	// {file_url} khi đính được; {notice} (alert-error: kết quả → lý do → hành động) khi không; {ended: true} khi phiên
	// thẻ đã kết thúc (shell đã xóa phiên và hiện màn quét thẻ kèm lý do, màn không hiện gì thêm)
	async upload(station, file) {
		const name = (file && file.name) || "photo.jpg";
		let content;
		try {
			content = await this.shrink(file);
		} catch (error) {
			return {
				notice: {
					variant: "error",
					title: __("Photo is not valid"),
					reason: __("The photo could not be read."),
					action: __("Take the photo again (JPEG, PNG or WebP, up to 5 MB)."),
				},
			};
		}
		let res;
		try {
			res = await station.rpc(
				TC_PHOTO_METHOD,
				{ station: station.station, file_name: name, content, client_ts: clientTs() },
				uuid4()
			);
		} catch (error) {
			if (error && error.sessionEnded) return { ended: true };
			return { notice: this.failure(error, name) };
		}
		if (res && res.ok === false && res.error)
			return { notice: { variant: "error", ...res.error } };
		if (!res || !res.file_url) return { notice: this.failure({ status: "?" }, name) };
		return { file_url: res.file_url };
	},

	// lỗi không phải từ chối nghiệp vụ: mất mạng/quá giờ → kiểm tra kết nối; 401/403 → phiên đăng nhập đã hết, quét lại
	// thẻ; lỗi khác của máy chủ → báo mã lỗi
	failure(error, name) {
		const title = __("Photo could not be attached");
		if (error && error.offline) {
			return {
				variant: "error",
				title,
				reason: __("No connection to the server: the file {0} was not uploaded.", [name]),
				action: __("Check the connection and choose the photo again."),
			};
		}
		if (error && (error.status === 401 || error.status === 403)) {
			return {
				variant: "error",
				title: __("Login session has ended"),
				reason: __("The server did not accept the photo {0} for this login.", [name]),
				action: __("Scan your employee card again, then choose the photo again."),
			};
		}
		return {
			variant: "error",
			title,
			reason: __("Server error ({0}): the file {1} was not uploaded.", [
				(error && error.status) || "?",
				name,
			]),
			action: __("Choose the photo again. If it fails again, call R10."),
		};
	},
};
