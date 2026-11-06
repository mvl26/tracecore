// Mã trạm của trang trạm (người dùng báo 06/11/2026: thỉnh thoảng URL mất ?station= và báo Chưa cấu hình trạm).
// Tách khỏi station.js: station.js không bao giờ dùng localStorage (token phiên chỉ ở sessionStorage); file này chỉ nhớ
// mã trạm công khai dạng TR-###, không nhớ gì khác.
const TC_STATION_CODE_KEY = "tc-station-code";

function tcStationStore() {
	try {
		return window.localStorage;
	} catch (failure) {
		return null; // trình duyệt chặn storage: vẫn chạy, chỉ không nhớ mã trạm
	}
}

// Có ?station= thì dùng và nhớ (chỉ mã TR-###); thiếu thì lấy mã đã nhớ của trình duyệt này; không có thì null.
function tcResolveStation(search, storage = tcStationStore()) {
	const fromUrl = new URLSearchParams(search || "").get("station");
	const valid = (code) => /^TR-\d{3}$/.test(code || "");
	if (fromUrl) {
		try {
			if (storage && valid(fromUrl)) storage.setItem(TC_STATION_CODE_KEY, fromUrl);
		} catch (failure) {
			// không nhớ được thì thôi
		}
		return { station: fromUrl, restored: false };
	}
	let stored = null;
	try {
		stored = storage ? storage.getItem(TC_STATION_CODE_KEY) : null;
	} catch (failure) {
		stored = null;
	}
	return valid(stored)
		? { station: stored, restored: true }
		: { station: null, restored: false };
}
