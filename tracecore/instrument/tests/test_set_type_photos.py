"""Ảnh bộ đã xếp (1-3 ảnh) của loại bộ (FEAT-015 Task 5; FR-M1-03, D-01, S6; AC-1 phần ảnh, AC-3 nguồn ảnh phiếu).

Cùng luật file với ảnh dụng cụ (FEAT-014 ``media``): kiểm nội dung, ≤ 5 MiB, ≤ 40 MP, riêng tư, File của chính loại bộ,
thumbnail 320 px chỉ server ghi.
"""

import base64
import io
import json
import os
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tracecore.instrument import media
from tracecore.tests.factories import (
	attach_instrument_file,
	attach_set_type_photo,
	make_instrument,
	make_set_type,
)

# Instrument Set Type liên kết Department, Item; Instrument liên kết Item; owner là User (ERPNext/HRMS): site CI
# mới chưa chạy Setup Wizard nên bỏ phụ thuộc này (dữ liệu tạo qua tracecore/tests/factories.py).
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Instrument Set Type"
TRAY = ("tray_image", "tray_image_2", "tray_image_3")
THUMBS = ("tray_thumbnail", "tray_thumbnail_2", "tray_thumbnail_3")
RED, BLUE = (220, 20, 20), (20, 20, 220)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(document.cookie)</script></svg>'
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64


def _image(fmt="JPEG", size=(64, 48), color=RED):
	buffer = io.BytesIO()
	Image.new("RGB", size, color).save(buffer, format=fmt)
	return buffer.getvalue()


def _split_jpeg(size=(2400, 1200), orientation=6):
	"""JPEG nửa trái đỏ, nửa phải xanh dương, có EXIF Orientation (6 = hiển thị xoay 90° theo chiều kim đồng hồ)."""
	width, height = size
	image = Image.new("RGB", size, BLUE)
	image.paste(Image.new("RGB", (width // 2, height), RED), (0, 0))
	exif = Image.Exif()
	exif[0x0112] = orientation
	buffer = io.BytesIO()
	image.save(buffer, format="JPEG", quality=95, exif=exif.tobytes())
	return buffer.getvalue()


def _photo_doc(set_type, field, content, file_name, is_private=1):
	return frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": is_private,
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": set_type,
			"attached_to_field": field,
		}
	)


def _loose_file(content, file_name, is_private=1):
	return frappe.get_doc(
		{"doctype": "File", "file_name": file_name, "content": content, "is_private": is_private}
	).insert()


def _save(set_type, **values):
	doc = frappe.get_doc(DOCTYPE, set_type)
	doc.update(values)
	doc.save()
	return doc


def _file_row(set_type, url):
	return frappe.get_doc(
		"File", {"file_url": url, "attached_to_doctype": DOCTYPE, "attached_to_name": set_type}
	)


class TestSetTypePhotos(FrappeTestCase):
	def assertRejected(self, set_type, field, content, file_name, *fragments):
		"""Tải lên bị từ chối: không bản ghi File, không blob trên đĩa (như ảnh dụng cụ)."""
		before = frappe.db.count("File", {"attached_to_name": set_type})
		file_doc = _photo_doc(set_type, field, content, file_name)
		with self.assertRaises(frappe.ValidationError) as raised:
			file_doc.insert()
		for fragment in fragments:
			self.assertIn(fragment, str(raised.exception))
		if file_doc.file_url:
			self.assertFalse(os.path.exists(file_doc.get_full_path()), msg=file_doc.file_url)
		self.assertEqual(frappe.db.count("File", {"attached_to_name": set_type}), before)
		return file_doc

	def test_set_type_photo_rules_same_as_instrument(self):
		# S6: JPEG/PNG/WebP theo nội dung, ≤ 5 MiB, ≤ 40 MP, luôn riêng tư — cùng luật với ảnh dụng cụ, cho cả 3 ảnh
		st = make_set_type("SPR").name
		big = _image("JPEG", size=(32, 32))
		big += b"\x00" * (media.IMAGE_MAX_BYTES + 1 - len(big))
		huge = io.BytesIO()
		Image.new("1", (9000, 9000), 1).save(huge, format="PNG")
		for field in TRAY:
			with self.subTest(field=field):
				self.assertRejected(st, field, big, "big.jpg", "5 MB")
				self.assertRejected(st, field, SVG, "tray.jpg", "JPEG")
				self.assertRejected(st, field, SVG, "tray.png", "JPEG")
				self.assertRejected(st, field, HEIC, "tray.heic", "HEIC")
				self.assertRejected(st, field, huge.getvalue(), "huge.png", "40")
		frappe.local.lang = "vi"
		try:
			self.assertRejected(st, "tray_image", SVG, "spr-vi.jpg", "Ảnh bộ đã xếp phải là ảnh JPEG")
		finally:
			frappe.local.lang = "en"
		self.assertEqual(
			media.TARGETS[(DOCTYPE, "tray_image")],
			media.Rule(("jpeg", "png", "webp"), 5 * 1024 * 1024, "tray_thumbnail"),
		)
		# ảnh hợp lệ yêu cầu công khai: vẫn lưu riêng tư, không để lại bản công khai, không chuyển công khai được
		ok = attach_set_type_photo(st, "tray_image_2", _image("PNG", color=(1, 160, 1)), "spr-ok.png", 0)
		self.assertEqual(ok.is_private, 1)
		self.assertTrue(ok.file_url.startswith("/private/files/"), msg=ok.file_url)
		self.assertFalse(
			os.path.exists(frappe.get_site_path("public", "files", os.path.basename(ok.file_url)))
		)
		ok.is_private = 0
		with self.assertRaises(frappe.ValidationError):
			ok.save()
		# liên kết web không nhận
		remote = _photo_doc(st, "tray_image", None, None)
		remote.file_url = "https://example.com/tray.jpg"
		with self.assertRaises(frappe.ValidationError):
			remote.insert()
		# File rời có sẵn đính (lại) vào ảnh khay: kiểm nội dung như tải lên
		loose = _loose_file(SVG, "spr-loose.txt")
		with self.assertRaises(frappe.ValidationError) as raised:
			frappe.client.set_value(
				"File",
				loose.name,
				{"attached_to_doctype": DOCTYPE, "attached_to_name": st, "attached_to_field": "tray_image_3"},
			)
		self.assertIn("JPEG", str(raised.exception))
		self.assertIsNone(frappe.db.get_value("File", loose.name, "attached_to_field"))
		# ngoài phạm vi: đính kèm sidebar của loại bộ và trường cùng tên của DocType khác không bị kiểm
		self.assertTrue(_photo_doc(st, None, b"ghi chu", "spr-note.txt").insert().name)
		todo = frappe.get_doc({"doctype": "ToDo", "description": "SPR scope"}).insert()
		other = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "spr-other.txt",
				"content": SVG,
				"is_private": 1,
				"attached_to_doctype": "ToDo",
				"attached_to_name": todo.name,
				"attached_to_field": "tray_image",
			}
		).insert()
		self.assertTrue(other.name)

	def test_desk_upload_of_fake_photo_rejected_cleanly(self):
		# Desk tải lên qua frappe.handler.upload_file: SVG đổi đuôi .jpg → ValidationError (4xx), không File, không blob
		from frappe import handler
		from werkzeug.datastructures import FileStorage

		st = make_set_type("SPH").name
		private_dir = frappe.get_site_path("private", "files")
		public_dir = frappe.get_site_path("public", "files")

		def upload(content, file_name, field="tray_image_2", is_private=1):
			storage = FileStorage(stream=io.BytesIO(content), filename=file_name)
			request = type("Request", (), {"files": {"file": storage}})()
			frappe.local.form_dict = frappe._dict(
				doctype=DOCTYPE, docname=st, fieldname=field, is_private=is_private, optimize=1
			)
			try:
				with patch.object(frappe, "request", request, create=True):
					return handler.upload_file()
			finally:
				frappe.local.form_dict = frappe._dict()

		before = (set(os.listdir(private_dir)), set(os.listdir(public_dir)))
		with self.assertRaises(frappe.ValidationError) as raised:
			upload(SVG, "tray.jpg")
		self.assertIn("JPEG", str(raised.exception))
		self.assertEqual((set(os.listdir(private_dir)), set(os.listdir(public_dir))), before)
		self.assertEqual(frappe.db.count("File", {"attached_to_name": st}), 0)
		frappe.clear_messages()
		saved = upload(_image("JPEG", color=(9, 99, 199)), "real.jpg", is_private=0)
		self.assertEqual(saved.is_private, 1)

	def test_set_type_photo_url_must_be_own_private_file(self):
		st = make_set_type("SPU").name
		other = make_set_type("SPU2").name
		make_instrument("SPU-I")
		foreign = attach_set_type_photo(other, "tray_image", _image("PNG", color=(2, 20, 200)), "spu-f.png")
		instrument_file = attach_instrument_file(
			"SPU-I", "image", _image("PNG", color=(3, 30, 130)), "spu-i.png"
		)
		sidebar = _photo_doc(st, None, _image("PNG", color=(4, 40, 140)), "spu-side.png").insert()
		for field, value in (
			("tray_image", "https://evil.example/x.png"),
			("tray_image", foreign.file_url),
			("tray_image_2", instrument_file.file_url),
			("tray_image_3", sidebar.file_url),
			("tray_image_3", "/private/files/../../site_config.json"),
			("tray_image", "/files/x.png"),
			("tray_image_2", "javascript:alert(1)"),
		):
			with self.subTest(field=field, value=value):
				doc = frappe.get_doc(DOCTYPE, st)
				doc.set(field, value)
				with self.assertRaises(frappe.ValidationError) as raised:
					doc.save()
				self.assertIn("set type", str(raised.exception))
		# File bị gắn thẳng ở DB (bỏ qua hook File): loại bộ đọc lại blob và kiểm nội dung
		loose = _loose_file(SVG, "spu-deep.txt")
		frappe.db.set_value(
			"File",
			loose.name,
			{"attached_to_doctype": DOCTYPE, "attached_to_name": st, "attached_to_field": "tray_image_3"},
		)
		doc = frappe.get_doc(DOCTYPE, st)
		doc.tray_image_3 = loose.file_url
		with self.assertRaises(frappe.ValidationError) as raised:
			doc.save()
		self.assertIn("JPEG", str(raised.exception))
		self.assertFalse(frappe.db.get_value(DOCTYPE, st, "tray_image_3"))
		# File riêng tư của chính loại bộ: nhận
		own = attach_set_type_photo(st, "tray_image", _image("PNG", color=(5, 50, 150)), "spu-own.png")
		self.assertEqual(_save(st, tray_image=own.file_url).tray_image, own.file_url)

	def test_three_photos_thumbnails_and_order(self):
		st = make_set_type("SPT").name
		p1 = attach_set_type_photo(st, "tray_image", _image("JPEG", (800, 600), (200, 10, 10)), "spt-1.jpg")
		p2 = attach_set_type_photo(st, "tray_image_2", _image("PNG", (600, 800), (10, 200, 10)), "spt-2.png")
		p3 = attach_set_type_photo(
			st, "tray_image_3", _image("WEBP", (1000, 500), (10, 10, 200)), "spt-3.webp"
		)
		doc = _save(st, tray_image=p1.file_url, tray_image_2=p2.file_url, tray_image_3=p3.file_url)
		hashes = {}
		for thumb, size in zip(THUMBS, ((320, 240), (240, 320), (320, 160)), strict=True):
			url = doc.get(thumb)
			self.assertTrue(url and url.startswith("/private/files/"), msg=(thumb, url))
			row = _file_row(st, url)
			self.assertEqual((row.attached_to_field, row.is_private), (thumb, 1))
			image = Image.open(row.get_full_path())
			self.assertEqual((image.format, image.size), ("JPEG", size), msg=thumb)
			hashes[thumb] = row.content_hash
		photos = media.set_type_photos(st)
		self.assertEqual(
			photos,
			[
				{
					"position": index + 1,
					"image_url": doc.get(field),
					"thumbnail_url": doc.get(thumb),
					"etag": hashes[thumb],
				}
				for index, (field, thumb) in enumerate(zip(TRAY, THUMBS, strict=True))
			],
		)
		# lưu lại không đổi ảnh: giữ thumbnail
		self.assertEqual(_save(st, assembly_minutes=15).tray_thumbnail_2, doc.tray_thumbnail_2)
		# đổi chỗ ảnh 1 ↔ 3 (nút trên form đổi giá trị): thumbnail đi theo ảnh
		doc = _save(st, tray_image=p3.file_url, tray_image_3=p1.file_url)
		swapped = media.set_type_photos(st)
		self.assertEqual([photo["image_url"] for photo in swapped], [p3.file_url, p2.file_url, p1.file_url])
		self.assertEqual(
			[photo["etag"] for photo in swapped],
			[hashes["tray_thumbnail_3"], hashes["tray_thumbnail_2"], hashes["tray_thumbnail"]],
		)
		self.assertEqual(Image.open(_file_row(st, doc.tray_thumbnail).get_full_path()).size, (320, 160))
		# xóa ảnh 2: bỏ thumbnail 2, danh sách còn ảnh 1 và 3 giữ đúng vị trí
		old_thumb_2 = frappe.db.get_value(
			"File", {"file_url": doc.tray_thumbnail_2, "attached_to_field": "tray_thumbnail_2"}, "name"
		)
		doc = _save(st, tray_image_2=None)
		self.assertIsNone(doc.tray_thumbnail_2)
		self.assertFalse(frappe.db.exists("File", old_thumb_2))
		self.assertEqual([photo["position"] for photo in media.set_type_photos(st)], [1, 3])
		# loại bộ chưa có ảnh → danh sách rỗng; không có loại bộ → DoesNotExistError
		self.assertEqual(media.set_type_photos(make_set_type("SPT0").name), [])
		with self.assertRaises(frappe.DoesNotExistError):
			media.set_type_photos("SPT-NONE")

	def test_thumbnail_fields_server_only(self):
		st = make_set_type("SPG").name
		source = attach_set_type_photo(st, "tray_image", _image("PNG", color=(6, 60, 160)), "spg.png")
		_save(st, tray_image=source.file_url)
		forged = attach_set_type_photo(st, "tray_image_2", _image("PNG", color=(7, 70, 170)), "spg-f.png")
		for thumb in THUMBS:
			with self.subTest(thumb=thumb):
				doc = frappe.get_doc(DOCTYPE, st)
				doc.set(thumb, forged.file_url)
				with self.assertRaises(frappe.ValidationError) as raised:
					doc.save()
				self.assertIn("thumbnail", str(raised.exception))
		doc = frappe.get_doc(DOCTYPE, st)
		doc.tray_thumbnail = None
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.client.set_value(DOCTYPE, st, "tray_thumbnail_3", forged.file_url)
		# tải lên / đính lại File vào trường thumbnail: từ chối trước khi ghi blob
		for content in (SVG, _image("JPEG", color=(8, 80, 180))):
			with self.subTest(upload=content[:4]):
				rejected = self.assertRejected(st, "tray_thumbnail_2", content, "thumb.jpg", "thumbnail")
				self.assertFalse(rejected.file_url)
		loose = _loose_file(_image("JPEG", color=(9, 90, 190)), "spg-loose.bin")
		with self.assertRaises(frappe.ValidationError):
			frappe.client.set_value(
				"File",
				loose.name,
				{
					"attached_to_doctype": DOCTYPE,
					"attached_to_name": st,
					"attached_to_field": "tray_thumbnail",
				},
			)

	def test_print_image_data_uri(self):
		# AC-3: ảnh in cho phiếu kiểm đếm dựng trong bộ nhớ từ ảnh gốc riêng tư, đúng hướng EXIF, cạnh dài ≤ 1200
		st = make_set_type("SPP").name
		# đuôi .png: Frappe không bỏ EXIF của file này, hàm phải tự xoay theo EXIF
		source = attach_set_type_photo(st, "tray_image", _split_jpeg(), "spp-portrait.png")
		self.assertEqual(Image.open(source.get_full_path()).getexif().get(0x0112), 6)
		uri = media.print_image_data_uri(source.file_url, DOCTYPE, st)
		self.assertTrue(uri.startswith("data:image/jpeg;base64,"), msg=uri[:40])
		image = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
		self.assertEqual((image.format, image.size), ("JPEG", (600, 1200)))
		self.assertFalse(dict(image.getexif()))
		rgb = image.convert("RGB")
		top, bottom = rgb.getpixel((300, 150)), rgb.getpixel((300, 1050))
		self.assertGreater(top[0], top[2], msg=top)  # nửa trái (đỏ) lên trên sau khi xoay
		self.assertGreater(bottom[2], bottom[0], msg=bottom)
		small = Image.open(
			io.BytesIO(
				base64.b64decode(
					media.print_image_data_uri(source.file_url, DOCTYPE, st, max_side=300).split(",", 1)[1]
				)
			)
		)
		self.assertEqual(small.size, (150, 300))
		# ảnh nhỏ hơn giới hạn không bị phóng to
		tiny = attach_set_type_photo(
			st, "tray_image_2", _image("PNG", (64, 48), (11, 110, 11)), "spp-tiny.png"
		)
		tiny_uri = media.print_image_data_uri(tiny.file_url, DOCTYPE, st)
		self.assertEqual(Image.open(io.BytesIO(base64.b64decode(tiny_uri.split(",", 1)[1]))).size, (64, 48))
		# không đọc URL ngoài, file công khai, đường dẫn thoát thư mục, file không phải ảnh
		public = _loose_file(_image("PNG", color=(12, 120, 12)), "spp-public.png", is_private=0)
		not_image = _loose_file(SVG, "spp-svg.txt")
		for bad in (
			"https://evil.example/x.jpg",
			"http://127.0.0.1/private/files/x.jpg",
			"/private/files/../../site_config.json",
			"/private/files/spp-missing.jpg",
			public.file_url,
			not_image.file_url,
			"",
			None,
		):
			with self.subTest(url=bad):
				self.assertIsNone(media.print_image_data_uri(bad, DOCTYPE, st))

	def test_print_image_data_uri_only_embeds_files_of_the_set_type(self):
		# review cuối Minor 1: chỉ nhúng File riêng tư đính vào CHÍNH loại bộ này; URL trỏ tới File riêng tư của bản ghi
		# khác (loại bộ khác, dụng cụ, file rời) không được đọc dù hợp lệ
		own = make_set_type("SPO").name
		other = make_set_type("SPX").name
		mine = attach_set_type_photo(own, "tray_image", _image("PNG", color=(14, 140, 14)), "spo.png")
		theirs = attach_set_type_photo(other, "tray_image", _image("PNG", color=(15, 150, 15)), "spx.png")
		make_instrument("SP-OWN-I")
		instrument_photo = attach_instrument_file(
			"SP-OWN-I", "image", _image("PNG", color=(16, 160, 16)), "sp-own-i.png"
		)
		loose = _loose_file(_image("PNG", color=(17, 170, 17)), "spo-loose.png")
		self.assertTrue(media.print_image_data_uri(mine.file_url, DOCTYPE, own).startswith("data:image/jpeg"))
		for url in (theirs.file_url, instrument_photo.file_url, loose.file_url):
			with self.subTest(url=url):
				self.assertIsNone(media.print_image_data_uri(url, DOCTYPE, own))
		self.assertIsNone(media.print_image_data_uri(mine.file_url, DOCTYPE, other))
		self.assertIsNone(media.print_image_data_uri(mine.file_url, "Instrument", own))

		# phiếu kiểm đếm: ảnh khay của loại bộ trỏ (ghi thẳng DB như dữ liệu cũ) tới File của loại bộ khác → không nhúng
		from tracecore.instrument import bom, count_sheet
		from tracecore.tests.factories import make_bom

		make_bom(own, [("SP-OWN-I", 1)])
		frappe.db.set_value(DOCTYPE, own, {"tray_image": theirs.file_url, "tray_image_2": mine.file_url})
		bom.invalidate(set_type=own)
		photos = count_sheet.context(own)["photos"]
		self.assertEqual(len(photos), 1)
		self.assertEqual(photos[0], media.print_image_data_uri(mine.file_url, DOCTYPE, own))

	def test_photo_change_audited(self):
		# S14: đổi ảnh khay ghi Audit Log Update (old/new) của loại bộ, kể cả thumbnail do server sinh
		st = make_set_type("SPA").name
		photo = attach_set_type_photo(st, "tray_image_2", _image("PNG", color=(13, 130, 13)), "spa.png")
		doc = _save(st, tray_image_2=photo.file_url)
		logs = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": DOCTYPE, "ref_name": st, "action": "Update"},
			fields=["old_value", "new_value"],
			order_by="creation desc",
			limit=1,
		)
		self.assertEqual(len(logs), 1)
		old, new = json.loads(logs[0].old_value), json.loads(logs[0].new_value)
		self.assertEqual((old.get("tray_image_2"), new.get("tray_image_2")), (None, photo.file_url))
		self.assertEqual(new.get("tray_thumbnail_2"), doc.tray_thumbnail_2)
		self.assertTrue(doc.tray_thumbnail_2)
