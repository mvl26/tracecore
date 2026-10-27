"""Nhập ảnh thực tế hàng loạt từ file zip (FEAT-011 Task 9; FR-M9-11.1, UC-39 bước 5; A-41 D4)."""

import io
import uuid
import zipfile

import frappe
from PIL import Image

from tracecore.instrument import photo_import
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Department"]


def png(color=(200, 30, 30), size=(40, 30)):
	buffer = io.BytesIO()
	Image.new("RGB", size, color).save(buffer, format="PNG")
	return buffer.getvalue()


def archive(files):
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w") as handle:
		for name, content in files.items():
			handle.writestr(name, content)
	return buffer.getvalue()


class TestPhotoImport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.instrument = factories.make_instrument("PH-" + uuid.uuid4().hex[:6].upper()).name
		self.set_type = factories.make_set_type(
			"PH" + uuid.uuid4().hex[:4].upper(), bom=[(self.instrument, 1)]
		).name

	def test_instrument_and_tray_photos_attached_by_file_name(self):
		result = photo_import.import_zip(
			archive(
				{
					f"{self.instrument.lower()}.png": png(),
					f"bo/{self.set_type}.png": png((10, 10, 200)),
					f"{self.set_type}-2.jpg": png((10, 200, 10)),
				}
			)
		)
		self.assertEqual(result["unmatched"], [])
		self.assertEqual(result["rejected"], [])
		self.assertEqual(len(result["attached"]), 3)
		instrument = frappe.get_doc("Instrument", self.instrument)
		self.assertTrue(instrument.image.startswith("/private/files/"))
		self.assertTrue(instrument.image_thumbnail)  # thumbnail như khi tải tay
		set_type = frappe.get_doc("Instrument Set Type", self.set_type)
		self.assertTrue(set_type.tray_image)
		self.assertTrue(set_type.tray_image_2)
		self.assertFalse(set_type.tray_image_3)

	def test_unmatched_names_are_listed(self):
		result = photo_import.import_zip(archive({"KHONG-CO-MA.png": png()}))
		self.assertEqual(result["unmatched"], ["KHONG-CO-MA.png"])
		self.assertEqual(result["attached"], [])

	def test_unsafe_paths_and_non_images_rejected(self):
		result = photo_import.import_zip(
			archive(
				{
					f"../{self.instrument}.png": png(),
					"/etc/passwd.png": png(),
					f"{self.instrument}.txt": b"hello",
					f"{self.instrument}.png": b"not really a png",
				}
			)
		)
		reasons = {row["file"]: row["reason"] for row in result["rejected"]}
		self.assertEqual(
			set(reasons),
			{
				f"../{self.instrument}.png",
				"/etc/passwd.png",
				f"{self.instrument}.txt",
				f"{self.instrument}.png",
			},
		)
		self.assertFalse(frappe.db.get_value("Instrument", self.instrument, "image"))

	def test_not_a_zip_is_file_error(self):
		from tracecore.core.importer import ImportFileError

		with self.assertRaises(ImportFileError):
			photo_import.import_zip(b"plain text")
