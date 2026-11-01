// Frappe giữ script Page trong localStorage `_page:<tên>` và chỉ bỏ khi assets.json đổi (bench build) hoặc Page đổi `modified`.
// Sửa mã trạm mà không build (bench restart, git pull) thì trình duyệt vẫn chạy mã cũ: so khóa theo nội dung file do máy chủ
// gửi trong boot và bỏ bản giữ khi khác. Giữ `_page:station` khi khóa không đổi: PDA mở lại trạm lúc mất mạng cần bản này.
window.tcSyncStationBuild = function (boot, storage) {
	const build = boot && boot.tc_station_build;
	if (!build) return;
	try {
		if (storage.getItem("tc_station_build") === build) return;
		storage.removeItem("_page:station");
		storage.setItem("tc_station_build", build);
	} catch (error) {
		// PDA tắt storage: không có bản giữ nào để bỏ
	}
};

if (window.frappe && frappe.boot) window.tcSyncStationBuild(frappe.boot, window.localStorage);
