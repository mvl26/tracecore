"""Desk SCR-02 (FEAT-015 Task 8): Client Script của loại bộ / dòng BOM / Item và gợi ý loại gói dùng được.

Hành vi trên trình duyệt kiểm bằng Playwright (Task 8 kiểm tay, Task 9 e2e); ở đây kiểm phần đọc được bằng Python:
script có mặt trong thư mục DocType, gọi đúng RPC, mỗi thao tác ghi một khóa idempotent, mọi chuỗi hiển thị qua __()
và có dòng trong translations/vi.csv, không chép hằng số nghiệp vụ (500 dòng, 999, danh sách phương pháp) vào JS, form có
ba tab Thông tin / Chi tiết / Lịch sử (Master Form), và query gợi ý loại gói chỉ trả loại gói dùng được kèm số ngày.
"""

import json
import os
import re
import shutil
import subprocess

import frappe

from tracecore.tests.factories import make_department, make_pack_type, make_user
from tracecore.tests.test_station_page import JS_STRING, vi_translations
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import set_type as api

# Instrument Set Type liên kết Department, Item; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

APP_PATH = frappe.get_app_path("tracecore")
SET_TYPE_DIR = ("instrument", "doctype", "instrument_set_type")
BOM_ITEM_DIR = ("instrument", "doctype", "set_bom_item")
SCRIPTS = {
	"form": (*SET_TYPE_DIR, "instrument_set_type.js"),
	"list": (*SET_TYPE_DIR, "instrument_set_type_list.js"),
	"bom_list": (*BOM_ITEM_DIR, "set_bom_item_list.js"),
	"item": ("public", "js", "item.js"),
	"shelf_life": ("public", "js", "tc_shelf_life.js"),
}
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)


def _read(*parts):
	with open(os.path.join(APP_PATH, *parts), encoding="utf-8") as handle:
		return handle.read()


def _form_js():
	return _read(*SCRIPTS["form"])


class TestSetTypeDeskAssets(IsolatedTestCase):
	def test_set_type_client_scripts_present_and_translated(self):
		ours = vi_translations()
		for key, parts in SCRIPTS.items():
			script = _read(*parts)
			strings = [match[1] for match in JS_STRING.findall(script)]
			self.assertTrue(strings, key)
			# chuỗi gọi kèm context DocType (__(s, null, doctype)) có thể dùng dòng "s,…,doctype"
			missing = sorted(
				{s for s in strings if not ours.get(s) and not any(k.startswith(f"{s}:") for k in ours)}
			)
			self.assertFalse(missing, f"{key}: thiếu dòng vi.csv {missing}")
			for number, line in enumerate(script.splitlines(), 1):
				code = line.split("//", 1)[0]
				self.assertFalse(VIETNAMESE.search(code), f"{key}:{number}: {line}")
		self.assertIn('frappe.ui.form.on("Instrument Set Type"', _form_js())
		self.assertIn('frappe.listview_settings["Instrument Set Type"]', _read(*SCRIPTS["list"]))

	def test_form_script_calls_rpcs_with_fresh_idempotency_key(self):
		script = _form_js()
		for method in (
			"tracecore.v1.set_type.form_context",
			"tracecore.v1.set_type.bom",
			"tracecore.v1.set_type.compare",
			"tracecore.v1.set_type.count_sheet",
			"tracecore.v1.set_type.pack_type_query",
			"tracecore.v1.set_type_admin.create",
			"tracecore.v1.set_type_admin.save_bom",
			"tracecore.v1.set_type_admin.copy",
		):
			self.assertIn(f'"{method}"', script, method)
		# ghi: một thao tác = một request (khóa X-Idempotency-Key + client_ts) của tc_codes.js; gửi lại sau lỗi mạng
		# dùng đúng request cũ; thiếu bundle thì chỉ đọc
		self.assertIn("tracecore.codes.new_request(", script)
		self.assertIn("tracecore.codes.send(", script)
		self.assertIn("window.tracecore && tracecore.codes", script)
		self.assertNotIn("frappe.call(", script)
		# form mới: nút lưu mặc định thay bằng "Lưu và tạo BOM v1" (loại bộ chỉ tạo cùng BOM v1, FR-M1-03.1)
		self.assertIn("disable_save()", script)
		self.assertIn('__("Save and create BOM v1")', script)
		# xung đột phiên bản: thông báo riêng + nút tải lại; lỗi dòng hiện tại từng dòng
		self.assertIn("BOM_VERSION_CONFLICT", script)
		self.assertIn("BOM_LINE_INVALID", script)
		# ngày hiệu lực: không chọn được ngày quá khứ trên datepicker (server vẫn kiểm)
		self.assertIn("min_date", script)
		# không xóa nút của Client Script khác
		self.assertNotIn("clear_custom_buttons", script)
		self.assertIn("remove_custom_button(", script)

	def test_form_script_has_no_business_constants(self):
		script = _form_js()
		methods = frappe.get_meta("Instrument Set Type").get_field("method").options.split("\n")
		for method in filter(None, methods):
			self.assertNotIn(f'"{method}"', script, method)
		# giới hạn 500 dòng, số lượng 999, độ dài lý do 500 chỉ ở server (bom_versions)
		self.assertNotRegex(script, r"\b(500|999)\b|MAX_LINES|MAX_QTY|REASON_MAX")
		# trạng thái phiên bản luôn có chữ (dùng lại nhãn của phiếu kiểm đếm)
		for label in (
			"BOM in effect",
			"BOM scheduled",
			"BOM superseded",
			"BOM replaced before taking effect",
		):
			self.assertIn(f'__("{label}")', script)

	def test_media_urls_rendered_only_from_site_files(self):
		script = _form_js()
		self.assertIn("function tc_st_safe_url(", script)
		for expr in ("image_url", "thumbnail_url", "line.thumbnail"):
			for match in re.finditer(re.escape(expr) + r"\b(?!:)", script):
				line_start = script.rfind("\n", 0, match.start())
				line = script[line_start : script.find("\n", match.end())]
				self.assertIn("tc_st_safe_url(", line, f"{expr}: {line.strip()}")
		node = shutil.which("node")
		if not node:
			self.skipTest("node not installed")
		source = re.search(r"function tc_st_safe_url\(.*?\n}\n", script, re.S).group(0)
		cases = {
			"/private/files/a-thumb.jpg": "/private/files/a-thumb.jpg",
			"/files/tray.png": "/files/tray.png",
			"javascript:alert(1)": "",
			"https://evil.example/x.jpg": "",
			"//evil.example/files/x.jpg": "",
			"data:image/png;base64,AAAA": "",
			"/private/filesx/a.jpg": "",
		}
		program = source + "\nconst cases = " + json.dumps(list(cases)) + ";\n"
		program += "console.log(JSON.stringify(cases.map((c) => tc_st_safe_url(c))));\n"
		output = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True).stdout
		self.assertEqual(dict(zip(cases, json.loads(output), strict=True)), cases)

	def test_set_type_form_has_master_form_tabs(self):
		meta = frappe.get_meta("Instrument Set Type")
		tabs = [field.label for field in meta.fields if field.fieldtype == "Tab Break"]
		self.assertEqual(tabs, ["Information", "Details", "History"])
		for fieldname in ("shelf_life_html", "tray_html", "bom_html", "history_html"):
			field = meta.get_field(fieldname)
			self.assertIsNotNone(field, fieldname)
			self.assertEqual(field.fieldtype, "HTML")
		order = [field.fieldname for field in meta.fields]
		self.assertLess(order.index("tray_html"), order.index("tab_bom"))
		self.assertLess(order.index("tab_bom"), order.index("bom_html"))
		self.assertLess(order.index("tab_history"), order.index("history_html"))

	def test_bom_item_list_is_read_only_with_open_set_type_button(self):
		script = _read(*SCRIPTS["bom_list"])
		self.assertIn('frappe.listview_settings["Set BOM Item"]', script)
		self.assertIn('frappe.set_route("Form", "Instrument Set Type"', script)
		self.assertIn('__("Open set type")', script)
		# không ai tạo dòng trực tiếp (S12)
		perms = frappe.get_meta("Set BOM Item").permissions
		self.assertFalse(any(perm.create or perm.write for perm in perms))

	def test_item_script_registers_shelf_life_button(self):
		self.assertEqual(
			frappe.get_hooks("doctype_js", app_name="tracecore").get("Item"), ["public/js/item.js"]
		)
		script = _read(*SCRIPTS["item"])
		self.assertIn('frm.doc.tc_item_group_cssd === "Packaging"', script)
		self.assertIn('__("Set shelf life")', script)
		self.assertIn("tracecore.shelf_life.dialog(", script)
		self.assertIn("tracecore.shelf_life.can_set()", script)
		# nút nhãn cuộn của FEAT-005 giữ nguyên
		self.assertIn("tracecore.codes.issue_rolls_dialog(frm)", script)
		self.assertIn("tracecore.codes.roll_labels_dialog(frm)", script)
		# hộp thoại dùng chung (bundle Desk): form Item và form loại bộ (R02/R10 không đọc được Item của ERPNext nên
		# sửa hạn lưu loại gói mặc định ngay trên loại bộ, quyền do form_context trả)
		self.assertIn('import "./tc_shelf_life.js";', _read("public", "js", "tracecore.bundle.js"))
		helper = _read(*SCRIPTS["shelf_life"])
		self.assertIn('"tracecore.v1.set_type_admin.set_pack_shelf_life"', helper)
		self.assertIn("tracecore.codes.new_request(", helper)
		self.assertIn("affected_set_types", helper)
		form = _form_js()
		self.assertIn("perms.can_set_shelf_life", form)
		self.assertIn("tracecore.shelf_life.dialog(", form)


class TestDepartmentQuery(IsolatedTestCase):
	"""Gợi ý khoa của trường ``department``: R02/R10 không có quyền Department của ERPNext/HRMS nhưng phải chọn khoa
	sở hữu loại bộ (FR-M1-03); query chỉ trả mã + tên khoa còn dùng, người gọi phải đọc được loại bộ."""

	def query(self, txt=""):
		return api.department_query("Department", txt, "name", 0, 20, {})

	def test_lists_enabled_departments_filtered_by_text(self):
		khoa = make_department("Khoa Ngoại Desk T8")
		old = make_department("Khoa Cũ Desk T8")
		frappe.db.set_value("Department", old, "disabled", 1)
		names = [row[0] for row in self.query("desk t8")]
		self.assertIn(khoa, names)
		self.assertNotIn(old, names)
		self.assertEqual(self.query("Ngoại Desk")[0][1], "Khoa Ngoại Desk T8")

	def test_r02_without_department_permission_gets_suggestions(self):
		khoa = make_department("Khoa Nội Desk T8")
		email = make_user("st-deptquery-r02@example.com", ["TC R02"])
		frappe.set_user(email)
		try:
			self.assertFalse(frappe.has_permission("Department", "select"))
			self.assertIn(khoa, [row[0] for row in self.query("Nội Desk")])
		finally:
			frappe.set_user("Administrator")
		email = make_user("st-deptquery-none@example.com", [])
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				self.query()
		finally:
			frappe.set_user("Administrator")

	def test_form_links_use_server_queries_without_client_link_check(self):
		script = _form_js()
		self.assertIn('"tracecore.v1.set_type.department_query"', script)
		# kiểm Link phía client (frappe.client.validate_link) cần quyền đọc Department/Item mà R02/R10 không có;
		# server vẫn kiểm Link tồn tại và luật loại gói khi lưu
		self.assertIn("ignore_link_validation", script)


class TestPackTypeQuery(IsolatedTestCase):
	"""Gợi ý loại gói của trường ``default_pack_type`` (FR-M1-03.5): chỉ loại gói dùng được, kèm "N ngày"."""

	def query(self, txt=""):
		return api.pack_type_query("Item", txt, "name", 0, 20, {})

	def test_only_usable_pack_types_with_days(self):
		good = make_pack_type("Giấy crepe Desk", 30)
		short = make_pack_type("Túi ép Desk", 14)
		zero = make_pack_type("Vải Desk", 0)
		off = make_pack_type("Hộp Desk", 60, disabled=1)
		rows = {row[0]: row for row in self.query("Desk")}
		self.assertIn(good, rows)
		self.assertIn(short, rows)
		self.assertNotIn(zero, rows)
		self.assertNotIn(off, rows)
		self.assertEqual(rows[good][2], frappe._("{0} days").format(30))
		# lọc theo chuỗi gõ (mã hoặc tên, không phân biệt hoa thường)
		frappe.db.set_value("Item", short, "item_name", "Túi ép tiệt khuẩn Desk")
		self.assertEqual([row[0] for row in self.query("túi ép tiệt")], [short])
		self.assertEqual([row[0] for row in self.query(short)], [short])

	def test_requires_set_type_read_permission(self):
		email = make_user("st-packquery-none@example.com", [])
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				self.query()
		finally:
			frappe.set_user("Administrator")
		email = make_user("st-packquery-r04@example.com", ["TC R04"])
		frappe.set_user(email)
		try:
			self.assertIsInstance(self.query(), list)
		finally:
			frappe.set_user("Administrator")
