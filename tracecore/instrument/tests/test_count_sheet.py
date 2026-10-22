"""Phiếu kiểm đếm PDF theo phiên bản BOM (FEAT-015 Task 7, S8, S9; FR-M1-03, FR-M1-03.2, EI-HW-007; AC-1, AC-3).

``count_sheet.context`` dựng dữ liệu phiếu (dòng theo thứ tự xếp, tổng, ảnh bộ nhúng base64, DataMatrix
``BOM-<TYPE_CODE>-V<n>``), ``render_html`` dùng Print Format Jinja ``TC Count Sheet``, ``render_pdf`` sinh PDF bằng
wkhtmltopdf của Frappe khi được yêu cầu (không lưu File, không tải gì từ mạng).
"""

import base64
import io
import re
import time
from collections import Counter
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, nowdate
from PIL import Image
from pypdf import PdfReader

from tracecore.core import gs1
from tracecore.instrument import bom, count_sheet
from tracecore.instrument.tests.test_bom_compare import bulk_set_type
from tracecore.tests.factories import attach_set_type_photo, make_bom, make_instrument, make_set_type
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import pack as pack_api
from tracecore.v1.tests.test_pack_api import STATION, assert_rejection, reject_count, rejects_since
from tracecore.v1.tests.test_pack_api import call as station_call

# Instrument Set Type liên kết Department, Item; Set BOM Item/Instrument liên kết Item; CI chưa có Setup Wizard
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

SET_TYPE = "Instrument Set Type"
TRAY = ("tray_image", "tray_image_2", "tray_image_3")
NAMES = {
	"CS-KEO": "Kéo phẫu tích có mấu",
	"CS-KEP": "Kẹp Kocher thẳng",
	"CS-BAT": "Bát inox đựng dung dịch",
	"CS-DAO": "Cán dao mổ số 4",
}
HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
DATA_URI = re.compile(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]+")
WHITESPACE = re.compile(r"\s+")


def _jpeg(color, size=(900, 600)):
	buffer = io.BytesIO()
	Image.new("RGB", size, color).save(buffer, format="JPEG")
	return buffer.getvalue()


def _with_photos(set_type, count):
	values = {}
	for index in range(count):
		field = TRAY[index]
		photo = attach_set_type_photo(
			set_type, field, _jpeg((40 * index, 120, 200)), f"{set_type.lower()}-{index}.jpg"
		)
		values[field] = photo.file_url
	doc = frappe.get_doc(SET_TYPE, set_type)
	doc.update(values)
	doc.save()


def _make_sheet_set_type(code="CSK", photos=3):
	"""Loại bộ có BOM v1 3 dòng theo thứ tự xếp không theo bảng chữ cái, tên dụng cụ có dấu."""
	for instrument, name in NAMES.items():
		make_instrument(instrument, name=name, methods=("Steam 134", "Plasma"))
	make_set_type(
		code,
		set_type_name="Bộ khám tổng quát",
		bom=[("CS-KEP", 2), ("CS-BAT", 1), ("CS-KEO", 4)],
		is_implant=1,
		assembly_minutes=15,
	)
	bom.invalidate(set_type=code)
	if photos:
		_with_photos(code, photos)
	return code


def _vi(test):
	frappe.local.lang = "vi"
	test.addCleanup(setattr, frappe.local, "lang", "en")


def _squash(text):
	return WHITESPACE.sub("", text)


def _pdf_pages(pdf):
	"""Text từng trang, đã bỏ mọi khoảng trắng. pypdf chèn/bỏ khoảng trắng và xuống dòng tùy vị trí glyph: giữa các đoạn
	font khác nhau (font dự phòng theo glyph khi Liberation 1.x thiếu chữ Việt có dấu → DejaVu) và khi chữ trong ô bảng
	xuống dòng; so chuỗi không tính khoảng trắng (fragment cũng qua ``_squash``)."""
	reader = PdfReader(io.BytesIO(pdf))
	return reader, [_squash(page.extract_text()) for page in reader.pages]


def _decode_png_uri(uri):
	prefix = "data:image/png;base64,"
	assert uri.startswith(prefix), uri[:40]
	return gs1.decode_datamatrix_png(base64.b64decode(uri[len(prefix) :]))


class TestCountSheet(IsolatedTestCase):
	def test_count_sheet_context_totals_order_photos(self):
		# FR-M1-03.2, AC-3: tổng số dụng cụ, ảnh bộ, thứ tự xếp, DataMatrix phiên bản BOM
		code = _make_sheet_set_type()
		ctx = count_sheet.context(code)
		self.assertLessEqual(
			{
				"set_type",
				"set_type_name",
				"department",
				"method",
				"is_implant",
				"assembly_minutes",
				"default_pack_type",
				"shelf_life",
				"bom_version",
				"effective_from",
				"reason",
				"status",
				"code",
				"code_png",
				"photos",
				"lines",
				"total_lines",
				"total_qty",
				"printed_at",
				"printed_by",
				"tc",
			},
			set(ctx),
		)
		self.assertEqual((ctx["set_type"], ctx["set_type_name"]), (code, "Bộ khám tổng quát"))
		self.assertEqual((ctx["bom_version"], ctx["status"]), (1, "Effective"))
		self.assertEqual(ctx["effective_from"], getdate(nowdate()))
		self.assertEqual((ctx["is_implant"], ctx["assembly_minutes"], ctx["method"]), (1, 15, "Steam"))
		self.assertEqual(ctx["shelf_life"]["days"], 365)
		self.assertEqual(
			[
				(line["position"], line["instrument"], line["instrument_name"], line["qty"])
				for line in ctx["lines"]
			],
			[
				(1, "CS-KEP", NAMES["CS-KEP"], 2),
				(2, "CS-BAT", NAMES["CS-BAT"], 1),
				(3, "CS-KEO", NAMES["CS-KEO"], 4),
			],
		)
		self.assertEqual((ctx["total_lines"], ctx["total_qty"]), (3, 7))
		self.assertEqual(len(ctx["photos"]), 3)
		for photo in ctx["photos"]:
			self.assertTrue(photo.startswith("data:image/jpeg;base64,"), msg=photo[:40])
			Image.open(io.BytesIO(base64.b64decode(photo.split(",", 1)[1]))).verify()
		self.assertEqual(ctx["code"], "BOM-CSK-V1")
		self.assertEqual(_decode_png_uri(ctx["code_png"]), "BOM-CSK-V1")
		self.assertRegex(ctx["printed_at"], r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$")
		self.assertTrue(ctx["printed_by"])
		self.assertEqual(ctx["tc"], count_sheet.token_values())
		# đọc phiếu không ghi gì (không Audit, không File)
		before = (frappe.db.count("Audit Log"), frappe.db.count("File"))
		count_sheet.render_html(code)
		self.assertEqual((frappe.db.count("Audit Log"), frappe.db.count("File")), before)

	def test_count_sheet_specific_old_version(self):
		_vi(self)
		code = _make_sheet_set_type(photos=0)
		# v1 hiệu lực từ hôm qua, v2 hiệu lực hôm nay → v1 Đã thay thế
		yesterday = add_days(getdate(nowdate()), -1)
		frappe.db.set_value("Set BOM Item", {"set_type": code, "bom_version": 1}, "effective_from", yesterday)
		bom.invalidate(set_type=code)
		make_bom(code, [("CS-DAO", 1), ("CS-KEO", 3)], version=2, reason="Thay kéo bằng cán dao")
		old = count_sheet.context(code, 1)
		self.assertEqual((old["bom_version"], old["status"], old["code"]), (1, "Superseded", "BOM-CSK-V1"))
		self.assertEqual([line["instrument"] for line in old["lines"]], ["CS-KEP", "CS-BAT", "CS-KEO"])
		self.assertEqual(old["effective_from"], yesterday)
		current = count_sheet.context(code)
		self.assertEqual((current["bom_version"], current["status"]), (2, "Effective"))
		self.assertEqual(current["reason"], "Thay kéo bằng cán dao")
		self.assertEqual(_decode_png_uri(current["code_png"]), "BOM-CSK-V2")
		html = count_sheet.render_html(code, 1)
		self.assertIn("BOM phiên bản 1", html)
		self.assertIn("Đã thay thế", html)
		self.assertIn(yesterday.strftime("%d/%m/%Y"), html)
		self.assertIn(NAMES["CS-KEP"], html)
		self.assertNotIn(NAMES["CS-DAO"], html)
		new_html = count_sheet.render_html(code, 2)
		self.assertIn("BOM phiên bản 2", new_html)
		self.assertIn("Đang hiệu lực", new_html)
		self.assertIn("Thay kéo bằng cán dao", new_html)
		# phiên bản không có / loại bộ không có → lỗi nghiệp vụ, không 500
		with self.assertRaises(frappe.ValidationError) as missing:
			count_sheet.context(code, 9)
		self.assertEqual(missing.exception.block.code, "BOM_VERSION_NOT_FOUND")
		with self.assertRaises(frappe.ValidationError) as unknown:
			count_sheet.context("CSK-NONE")
		self.assertEqual(unknown.exception.block.code, "SET_TYPE_NOT_FOUND")

	def test_count_sheet_without_photos_shows_placeholder(self):
		_vi(self)
		code = _make_sheet_set_type("CSN", photos=0)
		ctx = count_sheet.context(code)
		self.assertEqual(ctx["photos"], [])
		html = count_sheet.render_html(code)
		self.assertIn("Chưa có ảnh bộ đã xếp", html)
		# chỉ một ảnh: DataMatrix
		self.assertEqual(html.count("<img"), 1)
		# ảnh khay trỏ tới file không còn hợp lệ (dữ liệu cũ) cũng hiện khung trống, không lỗi
		frappe.db.set_value(SET_TYPE, code, "tray_image", "/private/files/khong-co.jpg")
		bom.invalidate(set_type=code)
		self.assertEqual(count_sheet.context(code)["photos"], [])
		self.assertIn("Chưa có ảnh bộ đã xếp", count_sheet.render_html(code))

	def test_count_sheet_html_has_no_external_urls_or_css_vars(self):
		code = _make_sheet_set_type("CSH", photos=2)
		# giá trị động có ký tự HTML: phải được escape (ghi thẳng DB như dữ liệu nhập từ nguồn khác)
		frappe.db.set_value(SET_TYPE, code, "set_type_name", "Bộ <script>alert(1)</script> & co")
		frappe.db.set_value("Instrument", "CS-BAT", "instrument_name", 'Bát <img src=x onerror="y">')
		bom.invalidate(set_type=code)
		bom.invalidate(instrument="CS-BAT")
		html = count_sheet.render_html(code)
		# bỏ dữ liệu base64 (bảng chữ cái base64 có "/" nên về lý thuyết có thể chứa "/files/")
		markup = DATA_URI.sub("data:", html)
		for forbidden in ("http://", "https://", "/private/files/", "/files/", "var(--", "url(", "<script"):
			self.assertNotIn(forbidden, markup, msg=forbidden)
		self.assertIn("Bộ &lt;script&gt;alert(1)&lt;/script&gt; &amp; co", html)
		self.assertIn("Bát &lt;img src=x onerror=&#34;y&#34;&gt;", html)
		self.assertNotIn("<img src=x", html)
		# mọi màu đến từ tokens.css đã sinh (token_values), không gõ hex
		colours = set(HEX.findall(html))
		self.assertTrue(colours)
		self.assertLessEqual(colours, set(count_sheet.token_values().values()))
		self.assertEqual(html.count("data:image/jpeg;base64,"), 2)
		self.assertEqual(html.count("data:image/png;base64,"), 1)

	def test_token_values_from_generated_css(self):
		path = frappe.get_app_path("tracecore", "public", "css", "tokens.css")
		with open(path, encoding="utf-8") as handle:
			css = handle.read()
		root = dict(re.findall(r"--tc-([a-z0-9-]+):([^;]+);", css))
		values = count_sheet.token_values()
		self.assertEqual(values["text"], root["text"])
		self.assertEqual(values["heading"], root["text-heading"])
		self.assertEqual(values["border"], root["frame"])
		for key, variable in count_sheet.TOKEN_VARS.items():
			if key not in ("font_sans", "font_mono"):
				self.assertEqual(values[key], root[variable], msg=key)
		# font in: token + dự phòng có chữ Việt trên Linux (A-07: Liberation/DejaVu thay Arial)
		self.assertTrue(values["font_sans"].startswith(root["font-sans"].rsplit(",", 1)[0]))
		self.assertIn('"Liberation Sans","DejaVu Sans",sans-serif', values["font_sans"])
		self.assertTrue(values["font_mono"].startswith('"Courier New"'))
		self.assertIn('"Liberation Mono","DejaVu Sans Mono",monospace', values["font_mono"])
		# thiếu biến → lỗi rõ ràng nêu tên biến
		broken = css.replace("--tc-text:", "--tc-gone:")
		with patch.object(count_sheet, "_read_tokens_css", return_value=broken):
			with self.assertRaises(count_sheet.TokenError) as error:
				count_sheet.token_values(refresh=True)
		self.assertIn("--tc-text", str(error.exception))
		# giá trị lạ (có thể phá CSS / chèn HTML) → lỗi
		hostile = css.replace("--tc-frame:#222222;", "--tc-frame:#222}</style><script>;")
		with patch.object(count_sheet, "_read_tokens_css", return_value=hostile):
			with self.assertRaises(count_sheet.TokenError):
				count_sheet.token_values(refresh=True)
		self.assertEqual(count_sheet.token_values(refresh=True), values)

	def test_count_sheet_pdf_vietnamese_text(self):
		# FR-M1-03, AC-1: PDF in được, chữ Việt có dấu không bị thay bằng ô vuông
		_vi(self)
		code = _make_sheet_set_type("CSV", photos=1)
		pdf = count_sheet.render_pdf(code)
		self.assertTrue(pdf.startswith(b"%PDF"))
		reader, pages = _pdf_pages(pdf)
		self.assertEqual(len(pages), 1)
		text = pages[0]
		for fragment in (
			"Phiếu kiểm đếm",
			"Bộ khám tổng quát",
			NAMES["CS-KEO"],
			NAMES["CS-BAT"],
			"Tổng: 3 dòng, 7 dụng cụ",
			"BOM-CSV-V1",
			"Người kiểm",
			"Người đóng gói",
			"Trang 1/1",
		):
			self.assertIn(_squash(fragment), text, msg=fragment)
		self.assertNotIn("�", text)
		self.assertNotIn("□", text)
		fonts = set()
		for page in reader.pages:
			for font in page["/Resources"].get("/Font", {}).values():
				fonts.add(str(font.get_object().get("/BaseFont")).lstrip("/").split("+")[-1])
		self.assertTrue(fonts)
		for font in fonts:
			self.assertRegex(font, r"^(Liberation|DejaVu|Arial|Courier)", msg=fonts)

	def test_count_sheet_pdf_500_lines_paged(self):
		# Review Focus 5: BOM 500 dòng → nhiều trang, tiêu đề cột lặp mỗi trang, không dòng bị cắt, < 10 MB
		_vi(self)
		bulk_set_type("CSL", 500, [(list(range(500)), lambda index: 1 + index % 3)])
		bom.invalidate(set_type="CSL")
		_with_photos("CSL", 3)
		started = time.perf_counter()
		pdf = count_sheet.render_pdf("CSL")
		elapsed = time.perf_counter() - started
		print(f"\ncount sheet PDF 500 lines: {elapsed:.2f} s, {len(pdf) / 1024:.0f} KiB")
		self.assertLess(len(pdf), 10 * 1024 * 1024)
		_reader, pages = _pdf_pages(pdf)
		self.assertGreater(len(pages), 5)
		for number, text in enumerate(pages, 1):
			self.assertIn(_squash("STT xếp"), text, msg=f"page {number}")
			self.assertIn(_squash("Tên dụng cụ"), text, msg=f"page {number}")
			self.assertIn(_squash(f"Trang {number}/{len(pages)}"), text, msg=f"page {number}")
		# mỗi dòng xuất hiện đúng một lần (mã ở cột Mã + trong tên "Instrument CSL-xxx"): không dòng bị cắt đôi/mất
		seen = Counter(re.findall(r"CSL-(\d{3})", "".join(pages)))
		self.assertEqual(seen, Counter({f"{index:03d}": 2 for index in range(500)}))
		self.assertIn("CSL-499", pages[-1])
		total_qty = sum(1 + index % 3 for index in range(500))
		self.assertIn(_squash(f"Tổng: 500 dòng, {total_qty} dụng cụ"), pages[-1])

	def test_print_format_installed_and_renders_from_desk(self):
		code = _make_sheet_set_type("CSD", photos=0)
		row = frappe.db.get_value(
			"Print Format",
			"TC Count Sheet",
			["standard", "print_format_type", "doc_type", "module", "disabled"],
			as_dict=True,
		)
		self.assertEqual(
			(row.standard, row.print_format_type, row.doc_type, row.module, row.disabled),
			("Yes", "Jinja", SET_TYPE, "Instrument", 0),
		)
		html = frappe.get_print(SET_TYPE, code, "TC Count Sheet")
		self.assertIn("BOM-CSD-V1", html)
		self.assertIn(NAMES["CS-KEO"], html)
		self.assertIn("data:image/png;base64,", html)
		# loại bộ cũ chưa có BOM: phiếu hiện lỗi nghiệp vụ thay vì lỗi template
		make_set_type("CSE")
		bom.invalidate(set_type="CSE")
		empty = frappe.get_print(SET_TYPE, "CSE", "TC Count Sheet")
		self.assertIn("BOM version not found", empty)
		self.assertNotIn("BOM-CSE-V", empty)

	def test_count_sheet_context_requires_read_permission(self):
		code = _make_sheet_set_type("CSP", photos=0)
		from tracecore.tests.factories import make_user

		frappe.set_user(make_user("cs-norole@example.com", []))
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			count_sheet.context(code)


class TestBomCodeAtStations(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.local.response.pop("http_status_code", None)
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def test_pack_scan_of_bom_code_is_scan_invalid(self):
		# S8: T4 quét nhầm mã trên phiếu kiểm đếm → SCAN_INVALID 422 như mã không phải Set ID, không 500
		for open_set in (None, "9520000CSK000001"):
			with self.subTest(open_set=open_set):
				before = reject_count()
				kwargs = {"raw": "]d1BOM-KHAM01-V3\r\n", "station": STATION}
				if open_set:
					kwargs["open_set"] = open_set
				result = station_call(pack_api.scan, **kwargs)
				assert_rejection(self, result, "SCAN_INVALID", 422)
				self.assertIn("BOM-KHAM01-V3", result["error"]["reason"])
				[row] = rejects_since(before)
				self.assertEqual(row.reason, "SCAN_INVALID")
