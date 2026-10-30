// Desk: hồ sơ bảo trì, kiểm định, hiệu chuẩn và sự cố thiết bị (SCR-22, FEAT-039; UC-22, FR-M5-03, FR-M5-04, BRU-EQP-002).
// Luật nằm ở server (tracecore.equipment.maintenance): JS chỉ hiện chỉ báo, banner trạng thái máy, nút "Bỏ bản nháp" và báo
// trước các điều kiện chặn ghi sổ bằng khối đỏ kết quả → lý do → hành động ngay trên form (không dùng thông báo nổi cho
// lỗi chặn). Server vẫn chặn nếu form bị vượt qua.

const TC_MAINT_ROLES = ["TC R02", "System Manager"];
const TC_MAINT_CERTIFIED = ["Inspection", "Calibration"];

function tc_maint_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_maint_can_edit() {
	return (
		frappe.session.user === "Administrator" ||
		TC_MAINT_ROLES.some((role) => frappe.user.has_role(role))
	);
}

// lỗi chặn: kết quả (đậm) → lý do → hành động, màu đỏ toàn khối
function tc_maint_error_html(error) {
	const lines = [
		`<b>✕ ${tc_maint_escape(error.title)}</b>`,
		tc_maint_escape(error.reason),
		tc_maint_escape(error.action),
	];
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

// điều kiện ghi sổ, cùng luật server (FR-M5-03.3, FR-M5-04.4); trả null khi đủ
function tc_maint_submit_problem(doc) {
	if (doc.abandoned) {
		return {
			title: __("Record is abandoned"),
			reason: __("An abandoned record cannot be closed."),
			action: __("Plan a new record instead."),
		};
	}
	if (TC_MAINT_CERTIFIED.includes(doc.record_type) && !doc.certificate) {
		return {
			title: __("Certificate is missing"),
			reason: __("A certificate is required to close an inspection or calibration record."),
			action: __("Attach the certificate, then close the record."),
		};
	}
	if (TC_MAINT_CERTIFIED.includes(doc.record_type) && !doc.valid_until) {
		return {
			title: __("Valid Until is missing"),
			reason: __("Valid Until is required to close an inspection or calibration record."),
			action: __("Enter the date the certificate is valid until, then close the record."),
		};
	}
	if (doc.record_type === "Incident" && !(doc.post_repair_check || "").trim()) {
		return {
			title: __("Post-repair check is missing"),
			reason: __("The post-repair check result is required to close an incident."),
			action: __("Enter the result of the check after the repair, then close the incident."),
		};
	}
	return null;
}

function tc_maint_indicator(frm) {
	if (frm.is_new()) {
		return;
	}
	let state = [__("Planned"), "orange"];
	if (frm.doc.docstatus === 2) {
		state = [__("Cancelled"), "darkgrey"];
	} else if (frm.doc.docstatus === 1) {
		state = [__("Closed"), "green"];
	} else if (frm.doc.abandoned) {
		state = [__("Abandoned"), "gray"];
	} else if (frm.doc.record_type === "Incident") {
		state = [__("Incident open"), "red"];
	} else if (frm.doc.planned_date && frm.doc.planned_date < frappe.datetime.get_today()) {
		state = [__("Overdue"), "red"];
	}
	frm.page.set_indicator(state[0], state[1]);
}

// dòng trạng thái hiện tại của máy (luôn có chữ), chỉ trên bản nháp
function tc_maint_machine_banner(frm) {
	frm.set_intro("");
	if (frm.is_new() || !frm.doc.equipment || frm.doc.docstatus !== 0 || frm.doc.abandoned) {
		return;
	}
	frappe.db.get_value("Equipment", frm.doc.equipment, "status").then((response) => {
		const status = response.message && response.message.status;
		if (!status) {
			return;
		}
		// refresh có thể chạy hai lần liền nhau: xóa dòng cũ ngay trước khi đặt để banner không nhân đôi
		frm.set_intro("");
		frm.set_intro(
			__("Equipment {0} status: {1}.", [frm.doc.equipment, __(status, null, "Equipment")]),
			status === "Ready" ? "green" : "orange"
		);
	});
}

function tc_maint_abandon(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Abandon draft {0}", [frm.doc.name]),
		fields: [
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason"),
				description: __(
					"The record stays for the audit trail; an incident returns the machine to its previous status."
				),
				reqd: 1,
			},
		],
		primary_action_label: __("Abandon draft"),
		primary_action(values) {
			dialog.get_primary_btn().prop("disabled", true);
			frm.call("abandon", { reason: values.reason })
				.then(() => {
					dialog.hide();
					frm.reload_doc();
				})
				.catch(() => dialog.get_primary_btn().prop("disabled", false));
		},
	});
	dialog.show();
}

frappe.ui.form.on("Maintenance Record", {
	setup(frm) {
		frm.set_query("equipment", () => ({ filters: { status: ["!=", "Retired"] } }));
	},

	refresh(frm) {
		frm.dashboard.clear_headline();
		tc_maint_indicator(frm);
		tc_maint_machine_banner(frm);
		if (frm.doc.docstatus === 0 && frm.doc.abandoned) {
			frm.page.clear_primary_action(); // bản đã bỏ không ghi sổ được (server cũng chặn)
		}
		if (
			!frm.is_new() &&
			frm.doc.docstatus === 0 &&
			!frm.doc.abandoned &&
			tc_maint_can_edit()
		) {
			frm.add_custom_button(__("Abandon draft"), () => tc_maint_abandon(frm));
		}
	},

	before_submit(frm) {
		const error = tc_maint_submit_problem(frm.doc);
		if (error) {
			frappe.validated = false;
			frm.dashboard.set_headline_alert(tc_maint_error_html(error));
		}
	},
});
