// NAV-07: địa chỉ Page trạm theo Số trạm — /app/station/<số> (vd /app/station/1 = T1), thay cho ?station=TR-001.
// Link cũ ?station= vẫn mở đúng trạm; trạm chưa có số giữ dạng ?station=. Kiosk nhớ cặp số ↔ mã trạm trong trình duyệt
// để mở được khi mất mạng. Hàm thuần, test bằng tracecore/tests/js_harness.py.
const TC_STATION_NO_KEY = "tc-station-no:";

const TcStationUrl = {
	path(name, no) {
		const number = parseInt(no, 10);
		if (number > 0) return `/app/station/${number}`;
		return name ? `/app/station?station=${encodeURIComponent(name)}` : "/app/station";
	},

	// {no, name} từ URL: /app/station/<số> và/hoặc ?station=<mã>; mã có thì trang dùng mã
	parse(pathname, search) {
		const match = /^\/app\/station\/(\d+)\/?$/.exec(String(pathname || ""));
		const number = match ? parseInt(match[1], 10) : 0;
		const name = new URLSearchParams(search || "").get("station");
		return { no: number > 0 ? number : null, name: name || null };
	},

	// bộ nhớ lâu dài của trình duyệt chỉ giữ cặp số ↔ mã trạm (không bí mật); token phiên trạm vẫn chỉ ở sessionStorage.
	// Bị chặn (chế độ riêng tư) thì null: chỉ mất phần mở trạm theo số khi mất mạng.
	storage() {
		try {
			return window.localStorage;
		} catch (error) {
			return null;
		}
	},

	remember(storage, no, name) {
		const number = parseInt(no, 10);
		if (!(number > 0) || !name) return;
		try {
			storage.setItem(TC_STATION_NO_KEY + number, name);
		} catch (error) {
			/* chặn lưu trữ: chỉ mất phần mở trạm theo số khi mất mạng */
		}
	},

	recall(storage, no) {
		try {
			return storage.getItem(TC_STATION_NO_KEY + parseInt(no, 10)) || null;
		} catch (error) {
			return null;
		}
	},
};

window.TcStationUrl = TcStationUrl;
