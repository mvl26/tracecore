/* global tracecore */
// Desk: form Zone Station (SCR-33, FEAT-002 Task 5).
// Chức năng trạm theo khu lấy từ tracecore.v1.zone.allowed_steps; JS không giữ bảng bước (core.zones là nguồn duy nhất).
// Ẩn/hiện khu cha, chức năng, thiết bị ngoại vi khi chọn "Là khu" do depends_on trong DocType lo.

const ZONE_STATION_ALLOWED_STEPS = "tracecore.v1.zone.allowed_steps";

frappe.ui.form.on("Zone Station", {
	setup(frm) {
		frm.set_query("parent_zone", () => ({ filters: { is_zone: 1 } }));
	},

	refresh(frm) {
		zone_station_indicator(frm);
		zone_station_load_steps(frm);
		// "In nhãn QR" cho trạm (FEAT-005, tc_codes.js); khu không có mã QR. Trạm tắt vẫn in được (A-05 R4).
		if (!frm.doc.is_zone) {
			tracecore.codes.add_print_button(
				frm,
				"Station",
				frm.doc.zone_station_name,
				[frm.doc.parent_zone, frm.doc.station_step].filter(Boolean).join(" - ")
			);
		}
	},

	is_active(frm) {
		zone_station_indicator(frm);
	},

	is_zone(frm) {
		if (frm.doc.is_zone) {
			frm.set_value("parent_zone", null);
			frm.set_value("station_step", null);
		}
	},

	parent_zone(frm) {
		zone_station_load_steps(frm, true);
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

function zone_station_set_step_options(frm, steps) {
	frm.set_df_property("station_step", "options", ["", ...steps].join("\n"));
	frm.refresh_field("station_step");
}

// `clear_invalid`: khi đổi khu cha, bỏ chức năng đang chọn nếu khu mới không cho phép.
function zone_station_load_steps(frm, clear_invalid = false) {
	if (frm.doc.is_zone) {
		return;
	}
	const zone = frm.doc.parent_zone;
	if (!zone) {
		zone_station_set_step_options(frm, []);
		if (clear_invalid && frm.doc.station_step) {
			frm.set_value("station_step", null);
		}
		return;
	}
	frappe.call({
		method: ZONE_STATION_ALLOWED_STEPS,
		args: { zone },
		callback(r) {
			if (frm.doc.parent_zone !== zone) {
				return; // người dùng đã đổi khu cha trong lúc chờ
			}
			const steps = r.message || [];
			zone_station_set_step_options(frm, steps);
			if (clear_invalid && frm.doc.station_step && !steps.includes(frm.doc.station_step)) {
				frm.set_value("station_step", null);
			}
		},
	});
}
