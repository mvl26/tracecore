// Desk: form Occupational Exposure (FEAT-071; FR-M16-01). Đổi nhân viên chỉ điền Khoa của nhân viên khi ô Khoa đang trống,
// không bao giờ xóa Khoa đã nhập (nhân viên chưa gán khoa). Không dùng fetch_from: Frappe v15 phía client bỏ qua
// fetch_if_empty nên ghi đè Khoa thành rỗng mà Tên khoa giữ tên cũ. Tên khoa do máy chủ đặt lại theo Khoa khi lưu.

const TcOccupationalExposureForm = {
	async employee(frm) {
		if (!frm.doc.employee || frm.doc.department) return;
		const response = await frappe.db.get_value("Employee", frm.doc.employee, "department");
		const department = response && response.message && response.message.department;
		if (department && !frm.doc.department) await frm.set_value("department", department);
	},
};

frappe.ui.form.on("Occupational Exposure", TcOccupationalExposureForm);
