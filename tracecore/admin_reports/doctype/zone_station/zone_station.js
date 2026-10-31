/* global tracecore */
// Desk: form Zone Station (SCR-33, FEAT-002 Task 5).
// Chức năng trạm theo vùng lấy từ tracecore.v1.zone.allowed_functions; JS không giữ quy tắc (Zone Type là nguồn duy nhất).
// Ẩn/hiện khu cha, chức năng, thiết bị ngoại vi khi chọn "Là khu" do depends_on trong DocType lo.

const ZONE_STATION_ALLOWED_FUNCTIONS = "tracecore.v1.zone.allowed_functions";
const ZONE_STATION_CHAIN_STATUS = "tracecore.v1.zone.chain_status";

frappe.ui.form.on("Zone Station", {
	setup(frm) {
		frm.set_query("parent_zone", () => ({ filters: { is_zone: 1, is_active: 1 } }));
		frm.set_query("station_function", "functions", () => ({
			filters: { name: ["in", frm.tc_allowed_functions || []], is_active: 1 },
		}));
	},

	refresh(frm) {
		zone_station_indicator(frm);
		zone_station_load_functions(frm);
		zone_station_chain_status(frm);
		// "In nhãn QR" cho trạm (FEAT-005, tc_codes.js); khu không có mã QR. Trạm tắt vẫn in được (A-05 R4).
		if (!frm.doc.is_zone && window.tracecore && tracecore.codes) {
			tracecore.codes.add_print_button(
				frm,
				"Station",
				frm.doc.zone_station_name,
				[frm.doc.parent_zone, frm.doc.station_no ? `T${frm.doc.station_no}` : ""]
					.filter(Boolean)
					.join(" - ")
			);
		}
	},

	is_active(frm) {
		zone_station_indicator(frm);
	},

	is_zone(frm) {
		if (frm.doc.is_zone) {
			frm.set_value("parent_zone", null);
			frm.set_value("station_no", 0);
			frm.set_value("functions", []);
		}
	},

	parent_zone(frm) {
		zone_station_load_functions(frm, true);
	},
});

// Chỉ báo có chữ (không chỉ màu): "Đang hoạt động" / "Không hoạt động" cho trạm; khu không có trạng thái này.
function zone_station_indicator(frm) {
	if (frm.is_new() || frm.doc.is_zone) {
		return;
	}
	if (frm.doc.is_active) {
		frm.page.set_indicator(__("Active", null, "Zone Station"), "green");
	} else {
		frm.page.set_indicator(__("Inactive", null, "Zone Station"), "red");
	}
}

// `clear_invalid`: khi đổi khu cha, bỏ các chức năng khu mới không cho phép.
function zone_station_load_functions(frm, clear_invalid = false) {
	if (frm.doc.is_zone) {
		return;
	}
	const zone = frm.doc.parent_zone;
	if (!zone) {
		frm.tc_allowed_functions = [];
		return;
	}
	frappe.call({
		method: ZONE_STATION_ALLOWED_FUNCTIONS,
		args: { zone },
		callback(r) {
			if (frm.doc.parent_zone !== zone) {
				return; // người dùng đã đổi khu cha trong lúc chờ
			}
			frm.tc_allowed_functions = (r.message || []).map((row) => row.value);
			if (clear_invalid) {
				const kept = (frm.doc.functions || []).filter((row) =>
					frm.tc_allowed_functions.includes(row.station_function)
				);
				frm.set_value("functions", kept);
			}
		},
	});
}

// Cảnh báo chuỗi còn thiếu: chức năng bắt buộc chưa có trạm hoạt động thì bộ sẽ kẹt khi đi tới đó (A-64).
function zone_station_chain_status(frm) {
	frappe.call({
		method: ZONE_STATION_CHAIN_STATUS,
		callback(r) {
			const missing = (r.message && r.message.missing) || [];
			frm.set_intro(
				missing.length
					? __("These functions have no active station yet: {0}.", [missing.join(", ")])
					: "",
				"orange"
			);
		},
	});
}
