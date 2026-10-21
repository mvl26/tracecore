"""Desk SCR-33 (FEAT-005 Task 5): script dùng chung in nhãn QR và nút cấp mã cuộn trên form Item được đăng ký qua hook."""

import os

import frappe
from frappe.tests.utils import FrappeTestCase

APP_PATH = frappe.get_app_path("tracecore")


def _read(*parts):
	with open(os.path.join(APP_PATH, *parts), encoding="utf-8") as handle:
		return handle.read()


class TestDeskCodes(FrappeTestCase):
	def test_hooks_register_item_script_and_include_js(self):
		# form Item (ERPNext) nhận nút "Cấp mã cuộn" qua doctype_js, không sửa app erpnext
		self.assertIn("public/js/item.js", frappe.get_hooks("doctype_js").get("Item", []))
		self.assertIn("tracecore.codes.issue_rolls_dialog(frm)", _read("public", "js", "item.js"))
		# tracecore.codes.print_dialog nạp sẵn trên mọi trang Desk (bundle có hash, như tracecore.bundle.css)
		self.assertEqual(frappe.get_hooks("app_include_js", app_name="tracecore"), ["tracecore.bundle.js"])
		self.assertIn('import "./tc_codes.js";', _read("public", "js", "tracecore.bundle.js"))
		helper = _read("public", "js", "tc_codes.js")
		self.assertIn("tracecore.codes.print_dialog", helper)
		self.assertIn("tracecore.v1.print.object_label", helper)
		self.assertIn("tracecore.v1.print.object_preview", helper)
		self.assertIn("tracecore.v1.codes.issue_rolls", helper)
		self.assertIn("X-Idempotency-Key", helper)

	def test_item_form_prints_issued_roll_labels_and_dialog_polls_job_status(self):
		# mã cuộn đã cấp mà lần in trước lỗi vẫn in lại được từ form Item (list_rolls → print_dialog)
		item_js = _read("public", "js", "item.js")
		self.assertIn("tracecore.codes.roll_labels_dialog(frm)", item_js)
		helper = _read("public", "js", "tc_codes.js")
		self.assertIn("tracecore.v1.codes.list_rolls", helper)
		self.assertIn("tracecore.codes.roll_labels_dialog = ", helper)
		# kết quả thật của lệnh in (Đã in / Không in được / Đang chờ agent) thay vì dừng ở "Đã xếp hàng"
		self.assertIn("tracecore.v1.print.job_status", helper)
		# một thao tác = một khóa idempotent, gửi lại dùng đúng request cũ
		self.assertIn("tracecore.codes.new_request = ", helper)

	def test_doctype_scripts_guard_missing_shared_helper(self):
		# tc_codes.js nạp qua bundle; trang cũ/bundle lỗi không được làm hỏng form và list view
		for parts in (
			("equipment", "doctype", "equipment", "equipment.js"),
			("equipment", "doctype", "equipment", "equipment_list.js"),
			("admin_reports", "doctype", "zone_station", "zone_station.js"),
			("admin_reports", "doctype", "zone_station", "zone_station_list.js"),
		):
			self.assertIn("window.tracecore && tracecore.codes", _read(*parts), parts)

	def test_gateway_error_is_unknown_outcome_like_network_error(self):
		# 502/503/504 hay 5xx không phải JSON (proxy/gateway): chưa biết server đã làm chưa → như lỗi mạng
		# (network: true), gửi lại đúng request cũ; hộp thoại cấp mã cuộn giữ pending và không đóng
		helper = _read("public", "js", "tc_codes.js")
		self.assertIn("TC_CODES_GATEWAY_STATUSES = [502, 503, 504]", helper)
		self.assertIn("response.status >= 500", helper)
		self.assertIn("return tc_codes_unknown_outcome(", helper)
		self.assertIn("if (result.network) {", helper)

	def test_dialog_has_single_poll_token(self):
		# lần hỏi mới thay lần cũ; poll_done chỉ đặt cho dòng mà chính vòng hỏi đó đã hỏi
		helper = _read("public", "js", "tc_codes.js")
		self.assertIn("dialog.tc_poll_token", helper)
		self.assertIn("polled.forEach((row) => {", helper)
		self.assertNotIn("rows.forEach((row) => {\n\t\trow.poll_done = true;", helper)

	def test_user_text_is_escaped_in_html(self):
		helper = _read("public", "js", "tc_codes.js")
		self.assertIn("label: frappe.utils.escape_html(code)", helper)
		self.assertIn("tc_codes_escape(frm.doc.item_name || frm.doc.name)", helper)
		self.assertNotIn("[\n\t\t\t\tfrm.doc.item_name || frm.doc.name,\n\t\t\t]", helper)
