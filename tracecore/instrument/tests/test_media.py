"""Ảnh thực tế, IFU và thumbnail của dụng cụ (FEAT-014 Task 3, FR-M1-01.5/.6, A-06 I11, Review Focus 2)."""

import io
import os
import struct
import zlib

import frappe
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
		# đuôi .pdf / .jpg: Frappe tự đọc nội dung trước khi ghi đĩa (pypdf, bỏ EXIF) và đã ném lỗi riêng;
		# đuôi khác: hook media.check_upload đọc magic bytes và từ chối có hướng dẫn
		self.assertRejected("MD-SNIFF", "ifu", html, "manual.pdf", error=Exception)
		self.assertRejected("MD-SNIFF", "ifu", html, "manual.txt", "PDF")
		self.assertRejected("MD-SNIFF", "ifu", exe, "manual.png", "PDF")
		self.assertRejected("MD-SNIFF", "image", svg, "photo.jpg", error=Exception)
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
