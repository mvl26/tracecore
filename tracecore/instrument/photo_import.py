"""Nhập ảnh thực tế hàng loạt từ file zip (FEAT-011 Task 9, FR-M9-11.1, UC-39 bước 5; A-41 D4).

Tên file (bỏ thư mục và đuôi) là mã: mã dụng cụ → ``Instrument.image``; ``<mã loại bộ>``, ``<mã loại bộ>-2``,
``-3`` → ``tray_image``, ``tray_image_2``, ``tray_image_3`` của loại bộ. Mỗi ảnh đi đúng đường tải tay: File riêng tư
đính vào trường (kiểm nội dung của `instrument.media`), gán URL rồi lưu bản ghi (sinh thumbnail). Đường dẫn không an
toàn (tuyệt đối, ``..``), file không phải ảnh, ảnh hỏng hay quá cỡ bị bỏ và liệt kê; tên không khớp mã nào cũng được
liệt kê. Mỗi ảnh một savepoint: ảnh lỗi không làm mất ảnh khác.
"""

import io
import os
import posixpath
import re
import zipfile

import frappe
from frappe import _

from tracecore.core.importer import ImportFileError
from tracecore.instrument import catalog, media

MAX_ZIP_BYTES = 200 * 1024 * 1024
MAX_FILES = 2000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
TRAY_FIELDS = {"": "tray_image", "2": "tray_image_2", "3": "tray_image_3"}
TRAY_NAME = re.compile(r"^([A-Z0-9]{2,8})(?:-([23]))?$")
SAVEPOINT = "tc_photo_import"


def _target(stem: str):
	"""``(doctype, tên, trường)`` cho tên file, hoặc None. Mã dụng cụ khớp trước (mã dụng cụ có thể chứa ``-``)."""
	code = catalog.clean_code(stem)
	if code and frappe.db.exists("Instrument", code):
		return "Instrument", code, "image"
	match = TRAY_NAME.fullmatch(stem.strip().upper())
	if match and frappe.db.exists("Instrument Set Type", match.group(1)):
		return "Instrument Set Type", match.group(1), TRAY_FIELDS[match.group(2) or ""]
	return None


def _unsafe(name: str) -> bool:
	parts = name.replace("\\", "/").split("/")
	return name.startswith(("/", "\\")) or ".." in parts or bool(re.match(r"^[A-Za-z]:", name))


def _attach(doctype, name, field, file_name, content) -> str:
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": content,
			"is_private": 1,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"attached_to_field": field,
		}
	).insert()
	doc = frappe.get_doc(doctype, name)
	doc.set(field, file_doc.file_url)
	doc.save()
	return file_doc.file_url


def import_zip(content: bytes) -> dict:
	"""Gắn ảnh trong zip vào bản ghi; trả ``{"attached": [{file, doctype, name, field}], "unmatched": [file],
	"rejected": [{file, reason}]}``. File không phải zip / quá cỡ → ``ImportFileError``."""
	if not content or len(content) > MAX_ZIP_BYTES:
		raise ImportFileError(
			_("The zip file is empty or larger than {0} MB.").format(MAX_ZIP_BYTES // (1024 * 1024))
		)
	try:
		archive = zipfile.ZipFile(io.BytesIO(content))
	except zipfile.BadZipFile:
		raise ImportFileError(_("The file is not a zip archive.")) from None
	entries = [info for info in archive.infolist() if not info.is_dir()]
	if len(entries) > MAX_FILES:
		raise ImportFileError(_("The zip file has more than {0} files.").format(MAX_FILES))
	if sum(info.file_size for info in entries) > MAX_UNCOMPRESSED_BYTES:
		raise ImportFileError(_("The zip file is too large to unpack."))

	result = {"attached": [], "unmatched": [], "rejected": []}
	for info in entries:
		name = info.filename
		base = posixpath.basename(name.replace("\\", "/"))
		stem, extension = os.path.splitext(base)
		if _unsafe(name):
			result["rejected"].append({"file": name, "reason": _("Unsafe path in the zip file.")})
			continue
		if extension.lower() not in IMAGE_EXTENSIONS:
			result["rejected"].append(
				{"file": name, "reason": _("Only JPEG, PNG or WebP photos are accepted.")}
			)
			continue
		if info.file_size > media.IMAGE_MAX_BYTES:
			result["rejected"].append(
				{
					"file": name,
					"reason": _("The photo is larger than {0} MB.").format(
						media.IMAGE_MAX_BYTES // (1024 * 1024)
					),
				}
			)
			continue
		target = _target(stem)
		if not target:
			result["unmatched"].append(name)
			continue
		doctype, record, field = target
		data = archive.read(info)
		_content, problem = media.inspect_content(data, field, doctype)
		if problem:
			result["rejected"].append({"file": name, "reason": problem})
			continue
		frappe.db.savepoint(SAVEPOINT)
		try:
			_attach(doctype, record, field, base, data)
		except (frappe.ValidationError, frappe.PermissionError) as error:
			frappe.db.rollback(save_point=SAVEPOINT)
			frappe.clear_last_message()
			result["rejected"].append({"file": name, "reason": frappe.utils.strip_html(str(error))})
			continue
		result["attached"].append({"file": name, "doctype": doctype, "name": record, "field": field})
	return result
