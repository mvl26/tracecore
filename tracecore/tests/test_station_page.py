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
