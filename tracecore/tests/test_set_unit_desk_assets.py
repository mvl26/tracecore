"""Desk SCR-03 (FEAT-016 Task 7): Client Script của Set Unit (form, list), hộp thoại Cấp Set ID dùng chung và nút
"Cấp Set ID" trên form loại bộ.

Hành vi trên trình duyệt kiểm tay một lần bằng Playwright (G17); ở đây kiểm phần đọc được bằng Python: script có mặt,
được nạp (thư mục DocType, bundle Desk), gọi đúng RPC, mỗi thao tác ghi một khóa idempotent qua tc_codes.js, mọi chuỗi
hiển thị qua __() và có bản dịch vi, không chép hằng số nghiệp vụ (100 bộ, 500 ký tự, 99 999) vào JS, trạng thái luôn có
chữ, ảnh xem trước chỉ nhận base64 PNG, form có ba tab Master Form.
"""

import json
import os
import re
import shutil
import subprocess

import frappe

from tracecore.tests.test_station_page import JS_STRING, other_app_translations, vi_translations
from tracecore.tests.utils import IsolatedTestCase

# Set Unit liên kết Department, Instrument Set Type (-> Item), User; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

APP_PATH = frappe.get_app_path("tracecore")
SET_UNIT_DIR = ("instrument", "doctype", "set_unit")
SCRIPTS = {
	"form": (*SET_UNIT_DIR, "set_unit.js"),
	"list": (*SET_UNIT_DIR, "set_unit_list.js"),
	"shared": ("public", "js", "tc_set_unit.js"),
}
SET_TYPE_FORM = ("instrument", "doctype", "instrument_set_type", "instrument_set_type.js")
VIETNAMESE = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
# hằng số nghiệp vụ chỉ ở server (form_context.limits): lô 100 bộ, lý do 500 ký tự, cơ số 99 999, 200 lệnh in
BUSINESS_NUMBERS = re.compile(r"(?<![\w.])(100|200|500|99999|99 999)(?![\w.])")


def _read(*parts):
	with open(os.path.join(APP_PATH, *parts), encoding="utf-8") as handle:
		return handle.read()


def _code_lines(script):
	"""Dòng mã bỏ chú thích // (chú thích tiếng Việt được phép)."""
	return [(number, line.split("//", 1)[0]) for number, line in enumerate(script.splitlines(), 1)]


class TestSetUnitDeskAssets(IsolatedTestCase):
	def test_set_unit_client_scripts_present_and_translated(self):
		ours, others = vi_translations(), other_app_translations()
		for key, parts in SCRIPTS.items():
			script = _read(*parts)
			strings = [match[1] for match in JS_STRING.findall(script)]
			self.assertTrue(strings, key)
			# chuỗi kèm context DocType (__(s, null, doctype)) dùng dòng "s,…,doctype"; chuỗi frappe đã dịch giữ nguyên
			missing = sorted(
				{
					s
					for s in strings
					if not ours.get(s) and not others.get(s) and not any(k.startswith(f"{s}:") for k in ours)
				}
			)
			self.assertFalse(missing, f"{key}: thiếu dòng vi.csv {missing}")
			for number, code in _code_lines(script):
				self.assertFalse(VIETNAMESE.search(code), f"{key}:{number}: {code}")
				self.assertFalse(BUSINESS_NUMBERS.search(code), f"{key}:{number}: hằng số nghiệp vụ {code}")
		self.assertIn('frappe.ui.form.on("Set Unit"', _read(*SCRIPTS["form"]))
		self.assertIn('frappe.listview_settings["Set Unit"]', _read(*SCRIPTS["list"]))
		# hộp thoại dùng chung nằm trong bundle Desk (form loại bộ và list Set Unit cùng gọi)
		self.assertIn('import "./tc_set_unit.js";', _read("public", "js", "tracecore.bundle.js"))

	def test_scripts_call_rpcs_with_fresh_idempotency_key(self):
		shared = _read(*SCRIPTS["shared"])
		form = _read(*SCRIPTS["form"])
		for method in (
			"tracecore.v1.set_unit.form_context",
			"tracecore.v1.set_unit.create_batch",
			"tracecore.v1.set_unit.print_tags",
			"tracecore.v1.set_unit.reprint_tag",
			"tracecore.v1.set_unit.cancel_print",
			"tracecore.v1.set_unit.print_status",
			"tracecore.v1.set_unit.batch_csv",
			"tracecore.v1.set_type.form_context",
			"tracecore.v1.set_type.department_query",
		):
			self.assertIn(f'"{method}"', shared, method)
		for method in (
			"tracecore.v1.set_unit.tag_preview",
			"tracecore.v1.set_unit.verify_tag",
			"tracecore.v1.set_unit.history",
			"tracecore.v1.set_unit.dispose",
		):
			self.assertIn(f'"{method}"', form, method)
		for key, script in (("shared", shared), ("form", form)):
			# ghi: một thao tác = một request (khóa X-Idempotency-Key + client_ts) của tc_codes.js, gửi lại sau lỗi
			# mạng dùng đúng request cũ; thiếu bundle thì báo lỗi thay vì gọi
			self.assertIn("tracecore.codes.new_request(", script, key)
			self.assertIn("tracecore.codes.send(", script, key)
			self.assertIn("window.tracecore && tracecore.codes", script, key)
			self.assertNotIn("frappe.call(", script, key)
			# lỗi chặn: khối đỏ inline, không toast/msgprint cho lỗi nghiệp vụ trong hộp thoại
			self.assertIn("block_html(", script, key)
			self.assertNotIn("innerHTML", script, key)
		# RPC chỉ đọc (GET) qua helper dùng chung của tc_codes.js
		codes = _read("public", "js", "tc_codes.js")
		self.assertIn("tracecore.codes.get = async function", codes)
		self.assertIn("tracecore.codes.get(", shared)
		self.assertIn("tracecore.codes.get(", form)
		# lỗi dòng BOM liệt kê từng dòng; in lại thiếu lý do liệt kê bộ cần mở; lệnh in kẹt có nút hủy
		self.assertIn("SET_TYPE_BOM_INVALID", shared)
		self.assertIn("REASON_REQUIRED", shared)
		self.assertIn("counts[kind].pending", form)
		# giới hạn lấy từ server
		self.assertIn("limits.max_batch", shared)
		self.assertIn("limits.reason_max", form)
		# không xóa nút của Client Script khác
		for script in (shared, form, _read(*SCRIPTS["list"])):
			self.assertNotIn("clear_custom_buttons", script)

	def test_status_and_print_states_always_have_text(self):
		shared = _read(*SCRIPTS["shared"])
		statuses = frappe.get_meta("Set Unit").get_field("status").options.split("\n")
		for status in filter(None, statuses):
			# mỗi trạng thái có màu riêng trong bảng màu, nhãn luôn là chữ đã dịch
			self.assertTrue(f'"{status}":' in shared or f"\t{status}:" in shared, status)
		self.assertIn('__(status, null, "Set Unit")', shared)
		for label in ("Queued for printing", "Printed", "Not printed: {0}", "Waiting for the Station Agent"):
			self.assertIn(f'__("{label}"', shared)
		self.assertIn("var(--tc-font-mono)", shared)

	def test_preview_image_only_from_base64_png(self):
		form = _read(*SCRIPTS["form"])
		self.assertIn("function tc_su_png_src(", form)
		self.assertIn("png_b64", form)
		for match in re.finditer(r"png_b64", form):
			line = form[form.rfind("\n", 0, match.start()) : form.find("\n", match.end())]
			self.assertIn("tc_su_png_src(", line, line.strip())
		node = shutil.which("node")
		if not node:
			self.skipTest("node not installed")
		source = re.search(r"function tc_su_png_src\(.*?\n}\n", form, re.S).group(0)
		cases = {
			"iVBORw0KGgo=": "data:image/png;base64,iVBORw0KGgo=",
			'x" onerror="alert(1)': "",
			"javascript:alert(1)": "",
			"": "",
		}
		program = source + "\nconst cases = " + json.dumps(list(cases)) + ";\n"
		program += "console.log(JSON.stringify(cases.map((c) => tc_su_png_src(c))));\n"
		output = subprocess.run([node, "-e", program], capture_output=True, text=True, check=True).stdout
		self.assertEqual(dict(zip(cases, json.loads(output), strict=True)), cases)

	def test_set_unit_form_has_master_form_tabs(self):
		meta = frappe.get_meta("Set Unit")
		tabs = [field.label for field in meta.fields if field.fieldtype == "Tab Break"]
		self.assertEqual(tabs, ["Information", "Details", "History"])
		order = [field.fieldname for field in meta.fields]
		for fieldname, tab in (
			("summary_html", "tab_info"),
			("tag_html", "tab_details"),
			("history_html", "tab_history"),
		):
			field = meta.get_field(fieldname)
			self.assertIsNotNone(field, fieldname)
			self.assertEqual(field.fieldtype, "HTML")
			self.assertLess(order.index(tab), order.index(fieldname))
		self.assertLess(order.index("tab_details"), order.index("tab_history"))
		# vẫn không ai tạo Set Unit trên Desk (chỉ qua Cấp Set ID, G4)
		self.assertFalse(any(perm.create for perm in meta.permissions))

	def test_set_type_form_has_issue_button(self):
		script = _read(*SET_TYPE_FORM)
		self.assertIn('__("Issue Set IDs")', script)
		self.assertIn("tracecore.set_unit.issue_dialog({ set_type: frm.doc.name", script)
		self.assertIn("tracecore.set_unit", script)
		shared = _read(*SCRIPTS["shared"])
		self.assertIn("tracecore.set_unit.issue_dialog = ", shared)
		list_script = _read(*SCRIPTS["list"])
		self.assertIn("tracecore.set_unit.issue_dialog(", list_script)
		self.assertIn("tracecore.set_unit.add_bulk_actions(", list_script)
		self.assertIn("permissions.can_issue", list_script)
