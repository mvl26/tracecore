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
# Tên DocType của ERPNext/HRMS bị dịch sai được phép ghi đè toàn site (tiêu đề, breadcrumb dịch không có context).
# Mỗi dòng phải có lý do; nhãn trường thì luôn sửa bằng dòng có context (tên DocType), không thêm vào đây.
GLOBAL_OVERRIDES = {
	"Shift Assignment": "Phân ca",  # HRMS dịch "Chuyển nhượng Shift" (sang nhượng quyền sở hữu)
	"Shift Type": "Loại ca",  # HRMS dịch "Loại thay đổi" (shift = thay đổi)
	"Department": "Khoa",  # ERPNext dịch "Cục" (cơ quan nhà nước); Department = khoa (CLAUDE.md)
	"Item": "Vật tư",  # ERPNext dịch "Hạng mục" (hạng mục công việc)
	"Material Request": "Yêu cầu vật tư",  # ERPNext dịch "Yêu cầu nguyên liệu" (nguyên liệu sản xuất)
	"Batch": "Lô",  # ERPNext dịch "Lô hàng" (chuyến hàng); batch có hạn dùng = lô
}


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
		self.assertIn('return typeof T2Wash !== "undefined" ? T2Wash : null;', source)

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
		self.assertIn('return typeof T5Load !== "undefined" ? T5Load : null;', source)
		with open(os.path.join(APP_PATH, "public", "js", "station_t5.js"), encoding="utf-8") as handle:
			screen = handle.read()
		self.assertIn("clearSession() {", screen)
		self.assertIn("sessionEnded", screen)
		self.assertIn(
			'dataset.surface = query.matches ? "PDA" : "STN"', screen
		)  # SCR-35: cùng màn, surface PDA
		# giờ trên form theo múi giờ hệ thống, không theo đồng hồ trình duyệt (runner UTC lệch 7 giờ so với server)
		self.assertNotIn("getHours", screen)
		self.assertIn("frappe.boot.time_zone.system", screen)

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

	def test_station_page_includes_t7_script(self):
		# màn T7 cấp phát (SCR-12/SCR-36, FEAT-026) ở file riêng, nối sau station.js như T4/T6
		self.assertIn("public/js/station_t7.js", frappe.get_hooks("page_js").get("station", []))
		self.assertTrue(os.path.exists(os.path.join(APP_PATH, "public", "js", "station_t7.js")))
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn('case "issue":', source)
		self.assertIn('return typeof T7Issue !== "undefined" ? T7Issue : null;', source)

	def test_t7_rpcs_carry_station_token_and_screen_clears_on_session_end(self):
		# FEAT-003: rpc() gắn token phiên cho RPC issue như pack/putaway; hết phiên thì màn T7 xóa phiếu đang mở
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			self.assertIn('method.startsWith("tracecore.v1.issue.")', handle.read())
		with open(os.path.join(APP_PATH, "public", "js", "station_t7.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn("clearSession() {", source)
		self.assertIn("sessionEnded", source)

	def test_t7_screen_follows_station_ui_rules(self):
		# ô quét luôn là input của trạm; 4 trạng thái (loading / empty / error / offline); không hover-only, swipe, drag
		with open(os.path.join(APP_PATH, "public", "js", "station_t7.js"), encoding="utf-8") as handle:
			source = handle.read()
		for token in (
			"renderLoading",
			"offlineHtml",
			"tc-alert-",
			'"alert" : "status"',  # lỗi chặn là role=alert, thông báo khác là role=status
		):
			self.assertIn(token, source)
		for banned in ("mouseover", "mouseenter", "touchmove", "swipe", "dragstart", "contextmenu"):
			self.assertNotIn(banned, source)

	def test_station_page_includes_t1_script(self):
		# màn T1 tiếp nhận (SCR-05, FEAT-019) ở file riêng, cùng cơ chế page_js với T4/T2/T6
		self.assertIn("public/js/station_t1.js", frappe.get_hooks("page_js").get("station", []))
		self.assertTrue(os.path.exists(os.path.join(APP_PATH, "public", "js", "station_t1.js")))
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn('return typeof T1Receiving !== "undefined" ? T1Receiving : null;', source)
		self.assertIn('method.startsWith("tracecore.v1.receive.")', source)  # bearer trong body như T4

	def test_t1_screen_never_drops_a_scan_and_returns_focus_to_the_scan_box(self):
		with open(os.path.join(APP_PATH, "public", "js", "station_t1.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn("clearSession() {", source)
		self.assertIn("sessionEnded", source)
		# mã quét đến khi đang chờ máy chủ được xếp hàng, không bị bỏ (bài học FEAT-026)
		self.assertIn("this.queue.push(raw)", source)
		self.assertIn("runQueued()", source)
		# sau mỗi thao tác trên màn, ô quét lấy lại focus
		self.assertIn("this.station.focus(true)", source)

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
			"Zone and station configuration: zone type, station function by zone, active flag.",
			"Scanner or scale attached to a station: connection USB HID, Serial or TCP.",
		):
			self.assertTrue(translations.get(source), msg=source)

	def test_pda_menu_hides_navigation_and_keeps_scan_on_top(self):
		"""#1828, A-92: ≤ 768 px hàng nút trạm và dòng phiên vào menu; không còn cột trạm đẩy ô quét."""
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.css"), encoding="utf-8") as handle:
			css = handle.read()
		rules = css[css.index("@media (max-width: 768px)", css.index("A-92")) :]
		self.assertIn(".tc-station-pills,\n\t.tc-session,", rules)
		self.assertIn(".tc-menu-open .tc-station-pills", rules)
		with open(
			os.path.join(APP_PATH, "ui", "page", "station", "station.html"), encoding="utf-8"
		) as handle:
			html = handle.read()
		self.assertIn('data-action="toggle-station-menu"', html)
		self.assertNotIn("tc-rail", html)

	def test_t3_open_closes_picker_and_brings_set_to_top(self):
		"""#1827, #1834 T3-04, T3-07."""
		with open(os.path.join(APP_PATH, "public", "js", "station_t3.js"), encoding="utf-8") as handle:
			source = handle.read()
		on_open = source[source.index("onOpen(res) {") : source.index("onLine(res) {")]
		self.assertIn("picker.close()", on_open)
		self.assertIn("scrollResultIntoView()", on_open)
		self.assertIn('data-action="t3-zoom"', source)

	def test_read_blocks_retry_once_and_state_the_cause(self):
		"""#1825: khối dữ liệu đọc khi mở trạm tự thử lại một lần, lỗi nói rõ nguyên nhân mất mạng, hết phiên hay lỗi máy chủ."""
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			shell = handle.read()
		self.assertIn("async rpcRead(", shell)
		self.assertIn("failureCause(", shell)
		for path, call in (
			("station_t1.js", 'rpcRead(T1_API + "received_today"'),
			("station_t1.js", 'rpcRead(T1_API + "receipt_sets"'),
			("station_t2.js", 'rpcRead("tracecore.v1.wash.redo_queue"'),
			("station_t5.js", 'rpcRead("tracecore.v1.load.overview"'),
		):
			with open(os.path.join(APP_PATH, "public", "js", path), encoding="utf-8") as handle:
				self.assertIn(call, handle.read(), path)
		ours = vi_translations()
		for source in (
			"Cause: no connection to the server, or the server answered too slowly.",
			"Cause: the station session has ended.",
			"Cause: server error ({0}).",
		):
			self.assertTrue(ours.get(source), source)

	def test_vi_translations_do_not_override_other_apps(self):
		"""Dòng không có context áp cho cả site: không được đổi bản dịch sẵn có của frappe/erpnext/hrms, trừ tên DocType
		bị dịch sai đã duyệt trong ``GLOBAL_OVERRIDES`` (tên DocType trên tiêu đề, breadcrumb không có context)."""
		others = other_app_translations()
		# hợp lệ chỉ khi bản dịch của mình trùng (NFC) với MỌI bản dịch sẵn có (CSV cũ và .po)
		overrides = sorted(
			f"{row[0]!r}: {sorted(others[row[0]])!r} -> {row[1]!r}"
			for row in vi_rows()
			if not (len(row) > 2 and row[2])
			and others.get(row[0])
			and others[row[0]] != {_nfc(row[1])}
			and GLOBAL_OVERRIDES.get(row[0]) != _nfc(row[1])
		)
		self.assertFalse(overrides, msg="Dùng cột context (tên DocType) cho:\n" + "\n".join(overrides))

	def test_approved_global_overrides_are_in_vi_csv(self):
		ours = {row[0]: _nfc(row[1]) for row in vi_rows() if not (len(row) > 2 and row[2])}
		for source, vi in GLOBAL_OVERRIDES.items():
			with self.subTest(source=source):
				self.assertEqual(ours.get(source), vi)

	def test_vi_translation_examples(self):
		frappe.local.lang = "vi"
		try:
			self.assertEqual(_("Invalid code"), "Mã không hợp lệ")
			self.assertEqual(_("Set Unit"), "Bộ dụng cụ")
			self.assertEqual(_("Sterile"), "Vô khuẩn")
		finally:
			frappe.local.lang = "en"

	def test_default_station_and_zone_labels_are_vietnamese(self):
		# nhãn trạm mặc định (seed) và nhãn khu trên thanh trạm có bản dịch vi; khu khoa là "Khoa", không lấy bản
		# dịch chung "Department" của Frappe/ERPNext ("Cục")
		from tracecore.setup.seed import DEFAULT_STATIONS

		ours = vi_translations()
		missing = [
			row["zone_station_name"] for row in DEFAULT_STATIONS if not ours.get(row["zone_station_name"])
		]
		self.assertEqual(missing, [])
		self.assertEqual(ours.get("Department:Zone Station"), "Khoa")
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			source = re.sub(r"\s+", " ", handle.read())
		self.assertIn('ZONE_LABEL[station.zone_type] || station.zone_type || "Station"', source)

	def test_scans_while_screen_is_busy_are_kept_and_focus_leaves_the_clicked_button(self):
		# mã quét đến khi màn đang chờ máy chủ được giữ lại và quét khi màn rảnh (màn T2, T4, T5, T5b, T6, T8, test hằng
		# ngày không tự xếp hàng như T1/T3/T7); bấm nút xong mà nút còn giữ focus thì trả focus về ô quét, để ký tự máy
		# quét không rơi vào nút (Enter còn bấm lại nút)
		with open(os.path.join(APP_PATH, "ui", "page", "station", "station.js"), encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn("this.pendingScans.push(", source)
		self.assertIn("drainScans() {", source)
		self.assertIn("document.activeElement === button", source)
