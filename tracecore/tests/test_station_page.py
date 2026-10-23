import csv
import json
import os
import re
import unicodedata
from collections import defaultdict

import frappe
from frappe import _
from frappe.tests.utils import FrappeTestCase
from frappe.utils import set_request
from frappe.website.serve import get_response

APP_PATH = frappe.get_app_path("tracecore")
PY_STRING = re.compile(r"(?<![\w.])_\(\s*\"((?:[^\"\\]|\\.)+)\"")
JS_STRING = re.compile(r"__\(\s*([\"'])((?:(?!\1)[^\\]|\\.)+)\1")


def _source_files(extensions):
	for root, dirs, files in os.walk(APP_PATH):
		dirs[:] = [d for d in dirs if d not in ("tests", "node_modules", "__pycache__", "dist")]
		for name in files:
			if name.endswith(extensions) and not name.startswith("test_"):
				yield os.path.join(root, name)


def source_strings():
	"""{(chuỗi nguồn, context)}: context = tên DocType cho nhãn/option (Desk dịch bằng __(label, null, doctype))."""
	strings = set()
	for path in _source_files((".py",)):
		with open(path, encoding="utf-8") as handle:
			strings.update((s, None) for s in PY_STRING.findall(handle.read()))
	for path in _source_files((".js", ".html")):
		with open(path, encoding="utf-8") as handle:
			strings.update((match[1], None) for match in JS_STRING.findall(handle.read()))
	for path in _source_files((".json",)):
		if os.sep + "doctype" + os.sep not in path:
			continue
		with open(path, encoding="utf-8") as handle:
			meta = json.load(handle)
		if meta.get("doctype") != "DocType":
			continue
		doctype = meta["name"]
		strings.add((doctype, None))
		for field in meta.get("fields", []):
			if field.get("label"):
				strings.add((field["label"], doctype))
			# mô tả dưới trường: Desk dịch bằng __(description, null, doctype)
			if field.get("description"):
				strings.add((field["description"], doctype))
			if field.get("fieldtype") == "Select":
				options = (field.get("options") or "").split("\n")
				strings.update((option, doctype) for option in options if option)
	strings.update(_custom_field_strings())
	return strings


def _custom_field_strings():
	"""Nhãn và option Select của Custom Field fixtures (Desk dịch bằng __(label, null, dt)); bỏ option số thuần."""
	path = os.path.join(APP_PATH, "fixtures", "custom_field.json")
	if not os.path.exists(path):
		return set()
	with open(path, encoding="utf-8") as handle:
		fields = json.load(handle)
	strings = set()
	for field in fields:
		if field.get("label"):
			strings.add((field["label"], field["dt"]))
		if field.get("fieldtype") == "Select":
			options = (field.get("options") or "").split("\n")
			strings.update((option, field["dt"]) for option in options if option and not option.isdigit())
	return strings


def vi_rows():
	with open(os.path.join(APP_PATH, "translations", "vi.csv"), encoding="utf-8", newline="") as handle:
		return [row for row in csv.reader(handle) if row]


def vi_translations():
	"""Khóa giống Frappe: "nguồn" hoặc "nguồn:context"."""
	return {(f"{row[0]}:{row[2]}" if len(row) > 2 and row[2] else row[0]): row[1] for row in vi_rows()}


def _nfc(text):
	return unicodedata.normalize("NFC", text.strip())


def other_app_translations():
	"""{nguồn: {bản dịch}} đọc thẳng từ translations/vi.csv và locale/vi.po của frappe/erpnext/hrms.

	Không dùng get_translations_from_apps: kết quả của nó đổi theo việc .mo đã biên dịch hay chưa
	(CI không `bench build` nên dùng CSV cũ, máy dev dùng .mo) → test phải ổn định ở mọi môi trường.
	"""
	from babel.messages.pofile import read_po

	found = defaultdict(set)
	for app in ("frappe", "erpnext", "hrms"):
		base = frappe.get_app_path(app)
		csv_path = os.path.join(base, "translations", "vi.csv")
		if os.path.exists(csv_path):
			with open(csv_path, encoding="utf-8", newline="") as handle:
				for row in csv.reader(handle):
					if len(row) >= 2 and row[1] and not (len(row) > 2 and row[2]):
						found[row[0]].add(_nfc(row[1]))
		po_path = os.path.join(base, "locale", "vi.po")
		if os.path.exists(po_path):
			with open(po_path, "rb") as handle:
				for message in read_po(handle):
					if isinstance(message.id, str) and message.id and message.string and not message.context:
						found[message.id].add(_nfc(message.string))
	return found


class TestStationPage(FrappeTestCase):
	def test_station_auth_shell_gates_the_existing_work_surface(self):
		with open(os.path.join(APP_PATH, "ui/page/station/station.html"), encoding="utf-8") as handle:
			html = handle.read()
		self.assertIn('class="tc-auth-form', html)
		self.assertIn('id="tc-card-input"', html)
		self.assertIn('class="tc-work" hidden', html)
		self.assertIn('class="tc-session" hidden', html)

	def test_station_bearer_never_uses_persistent_storage(self):
		with open(os.path.join(APP_PATH, "ui/page/station/station.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn("sessionStorage", source)
		self.assertNotIn("localStorage", source)
		self.assertNotIn('headers["Authorization"]', source)

	def test_station_page_registered(self):
		page = frappe.get_doc("Page", "station")
		self.assertEqual(page.module, "UI")
		roles = {row.role for row in page.roles}
		self.assertTrue({"System Manager", "TC R03", "TC R04", "TC R06"} <= roles, msg=roles)

	def test_service_worker_served(self):
		set_request(method="GET", path="/sw.js")
		response = get_response()
		self.assertEqual(response.status_code, 200)
		self.assertIn("javascript", response.mimetype)
		body = response.get_data(as_text=True)
		self.assertIn("CACHE_NAME", body)
		# precache đúng bundle có hash (đổi mỗi lần build), không phải file CSS URL cố định
		self.assertIn("tracecore.bundle", body)
		self.assertNotIn("/assets/tracecore/css/tokens.css", body)
		self.assertIn("response.ok", body)

	def test_desk_loads_hashed_token_bundle(self):
		self.assertEqual(frappe.get_hooks("app_include_css", app_name="tracecore"), ["tracecore.bundle.css"])
		with open(
			os.path.join(APP_PATH, "public", "css", "tracecore.bundle.css"), encoding="utf-8"
		) as handle:
			bundle = handle.read()
		self.assertIn("--tc-primary:", bundle)
		self.assertIn("--primary-color:var(--tc-primary)", bundle)

	def test_station_page_includes_t4_script(self):
		# màn T4 (SCR-08) ở file riêng; Frappe nối nó vào script của Page station qua hook page_js
		self.assertIn("public/js/station_t4.js", frappe.get_hooks("page_js").get("station", []))
		self.assertTrue(os.path.exists(os.path.join(APP_PATH, "public", "js", "station_t4.js")))

	def test_station_page_includes_t2_script(self):
		# màn T2 lô rửa (SCR-06, FEAT-021) ở file riêng, nối sau station.js như T4
		scripts = frappe.get_hooks("page_js").get("station", [])
		self.assertIn("public/js/station_t2.js", scripts)
		self.assertTrue(os.path.exists(os.path.join(APP_PATH, "public", "js", "station_t2.js")))
		with open(os.path.join(APP_PATH, "ui/page/station/station.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn('method.startsWith("tracecore.v1.wash.")', source)  # bearer trong body như T4
		self.assertIn("new T2Wash(this)", source)

	def test_t2_form_times_follow_the_system_timezone_not_the_browser(self):
		# Giờ kết thúc mặc định của form nhập tay gửi không kèm offset và server coi là giờ hệ thống: lấy theo múi giờ
		# hệ thống (frappe.boot.time_zone.system), không theo đồng hồ trình duyệt (runner CI chạy UTC → sớm hơn 7 giờ)
		with open(os.path.join(APP_PATH, "public", "js", "station_t2.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertNotIn("getHours", source)
		self.assertIn("Intl.DateTimeFormat", source)
		self.assertIn("frappe.boot.time_zone.system", source)

	def test_station_page_includes_t5_script(self):
		# màn T5 nạp mẻ (SCR-09 STN, SCR-35 PDA, FEAT-022) ở file riêng, nối sau station.js như T2
		scripts = frappe.get_hooks("page_js").get("station", [])
		self.assertIn("public/js/station_t5.js", scripts)
		self.assertTrue(os.path.exists(os.path.join(APP_PATH, "public", "js", "station_t5.js")))
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn('method.startsWith("tracecore.v1.load.")', source)  # bearer trong body như T4/T2
		self.assertIn("new T5Load(this)", source)
		with open(os.path.join(APP_PATH, "public", "js", "station_t5.js"), encoding="utf-8") as handle:
			screen = handle.read()
		self.assertIn("clearSession() {", screen)
		self.assertIn("sessionEnded", screen)
		self.assertIn(
			'dataset.surface = query.matches ? "PDA" : "STN"', screen
		)  # SCR-35: cùng màn, surface PDA

	def test_station_page_includes_t6_script(self):
		# màn T6 kho vô khuẩn (SCR-11, FEAT-025) ở file riêng, cùng cơ chế page_js với T4
		self.assertIn("public/js/station_t6.js", frappe.get_hooks("page_js").get("station", []))
		path = os.path.join(APP_PATH, "public", "js", "station_t6.js")
		self.assertTrue(os.path.exists(path))
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			self.assertIn("T6Storage", handle.read())

	def test_t6_rpcs_carry_station_token_and_screen_clears_on_session_end(self):
		# FEAT-003: rpc() gắn token phiên cho RPC putaway như pack; hết phiên thì màn T6 xóa gói/tồn đang hiện
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			self.assertIn('method.startsWith("tracecore.v1.putaway.")', handle.read())
		with open(os.path.join(APP_PATH, "public", "js", "station_t6.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn("clearSession() {", source)
		self.assertIn("sessionEnded", source)

	def test_manifest_served(self):
		set_request(method="GET", path="/manifest.json")
		response = get_response()
		self.assertEqual(response.status_code, 200)
		manifest = json.loads(response.get_data(as_text=True))
		self.assertTrue(manifest["start_url"].startswith("/app/station"))
		self.assertEqual(manifest["display"], "fullscreen")
		self.assertEqual(manifest["theme_color"], "#1F4E79")
		self.assertEqual(manifest["background_color"], "#F4F6F9")

	def test_vi_translations_cover_source_strings(self):
		ours, others = vi_translations(), other_app_translations()

		def translated(source, context):
			return (context and ours.get(f"{source}:{context}")) or ours.get(source) or others.get(source)

		missing = sorted(
			f"{s}" + (f" [{c}]" if c else "") for s, c in source_strings() if not translated(s, c)
		)
		self.assertFalse(missing, msg=f"Thiếu bản dịch vi: {missing}")

	def test_vi_generic_labels_of_feat018_doctypes_have_context_rows(self):
		"""Nhãn chung chung (Expiry Date, Label, Quantity…) trên DocType FEAT-018 dịch bằng dòng có context riêng,
		không dựa vào bản dịch toàn site của ERPNext/HRMS (có thể là thuật ngữ khác)."""
		ours = vi_translations()
		expected = [
			("Expiry Date", "Pack"),
			("Label", "Pack"),
			("Department", "Pack"),
			("Quantity", "Pack Instrument Confirmed"),
			("Quantity", "Set BOM Item"),
			("Action", "Pack Maintenance Done"),
			("Reason", "Pack Maintenance Done"),
		]
		sources = source_strings()
		for label, doctype in expected:
			with self.subTest(label=label, doctype=doctype):
				self.assertIn((label, doctype), sources)
				self.assertTrue(ours.get(f"{label}:{doctype}"))

	def test_vi_csv_parses_without_frappe_warnings(self):
		"""Mọi dòng vi.csv có 2 hoặc 3 cột như Frappe đọc; dòng sai cột ghi "Bad translation" vào Error Log mỗi lần
		nạp bản dịch (dấu phẩy trong chuỗi nguồn phải nằm trong ngoặc kép, không dùng ``\\,``)."""
		from frappe.translate import get_translation_dict_from_file

		path = os.path.join(APP_PATH, "translations", "vi.csv")
		bad = [row for row in vi_rows() if len(row) not in (2, 3)]
		self.assertFalse(bad, msg=f"Dòng vi.csv sai số cột: {bad}")
		with open(path, encoding="utf-8") as handle:
			self.assertNotIn("\\,", handle.read())
		before = frappe.db.count("Error Log", {"method": "Error in translation file"})
		translations = get_translation_dict_from_file(path, "vi", "tracecore", throw=True)
		self.assertEqual(frappe.db.count("Error Log", {"method": "Error in translation file"}), before)
		for source in (
			"Zone and station configuration (FEAT-002): zone type, station function by zone, active flag.",
			"Scanner or scale attached to a station (FEAT-002): connection USB HID, Serial or TCP.",
		):
			self.assertTrue(translations.get(source), msg=source)

	def test_vi_translations_do_not_override_other_apps(self):
		"""Dòng không có context áp cho cả site: không được đổi bản dịch sẵn có của frappe/erpnext/hrms."""
		others = other_app_translations()
		# hợp lệ chỉ khi bản dịch của mình trùng (NFC) với MỌI bản dịch sẵn có (CSV cũ và .po)
		overrides = sorted(
			f"{row[0]!r}: {sorted(others[row[0]])!r} -> {row[1]!r}"
			for row in vi_rows()
			if not (len(row) > 2 and row[2]) and others.get(row[0]) and others[row[0]] != {_nfc(row[1])}
		)
		self.assertFalse(overrides, msg="Dùng cột context (tên DocType) cho:\n" + "\n".join(overrides))

	def test_vi_translation_examples(self):
		frappe.local.lang = "vi"
		try:
			self.assertEqual(_("Invalid code"), "Mã không hợp lệ")
			self.assertEqual(_("Set Unit"), "Bộ dụng cụ")
			self.assertEqual(_("Sterile"), "Vô khuẩn")
		finally:
			frappe.local.lang = "en"
