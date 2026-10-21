"""Ảnh thực tế và IFU của dụng cụ, thumbnail cho trạm (FR-M1-01.5/.6, A-06 I11/I12, architecture R-08).

Kiểm hai lớp:

0. Lớp File của TraceCore (``InstrumentMediaFile``, ``override_doctype_class``): ``before_insert`` của Frappe đọc nội
   dung **trước** mọi hook (bỏ EXIF của ``.jpg``/``.jpeg`` bằng Pillow, đọc ``.pdf`` bằng pypdf); file giả mạo (SVG
   đổi đuôi ``.jpg``, HTML đổi đuôi ``.pdf``) làm lỗi đó thành HTTP 500. ``precheck_upload`` kiểm nội dung trong bộ
   nhớ theo đúng luật của lớp 1 trước khi Frappe xử lý: từ chối sạch (ValidationError, thông báo dịch), chưa có blob
   nào được ghi.
1. Hook ``File.before_insert`` (``check_upload``): File đính vào trường ``ifu``/``image`` của Instrument được kiểm
   bằng **nội dung** (magic bytes, Pillow ``verify`` + giới hạn điểm ảnh, PDF không có nội dung chủ động), không tin
   đuôi file hay Content-Type; quá cỡ/sai định dạng thì xóa blob vừa ghi (nếu không dùng chung) và báo lỗi; Frappe
   hoàn tác giao dịch và ``File.on_rollback`` xóa nốt. File hợp lệ luôn riêng tư (``is_private = 1``). Trường
   ``image_thumbnail`` chỉ server ghi (``refresh_thumbnail``).
   Hook ``File.validate`` (``validate_file``): File **có sẵn** được đính (lại) vào các trường đó (đổi
   ``attached_to_doctype``/``attached_to_name``/``attached_to_field``/``file_url``, kể cả qua
   ``frappe.client.set_value``) qua đúng kiểm tra nội dung như khi tải lên và không được chuyển thành công khai. File
   công khai trước FEAT-014 lưu lại không đổi gì vẫn được, và chuyển sang riêng tư được.
2. ``Instrument.validate`` (``validate_fields``): giá trị mới của ``image``/``ifu`` phải là URL ``/private/files/…``
   của File đính vào chính dụng cụ (hoặc tên tạm của bản ghi chưa lưu trên Desk), đúng trường, và blob qua lại đúng
   kiểm tra nội dung của lớp 1 (phòng khi File bị gắn thẳng ở DB, bỏ qua hook); URL ngoài, File của bản ghi khác,
   File công khai → lỗi. Giá trị cũ không đổi (dữ liệu trước FEAT-014) không kiểm lại.

Thumbnail: 320 px cạnh dài, xoay theo EXIF rồi bỏ EXIF, JPEG q80, File riêng tư đính vào dụng cụ; ``etag`` =
``content_hash`` của File thumbnail (đổi ảnh → đổi etag) để Service Worker cache theo phiên bản (FEAT-009).
"""

import io
import os
import warnings

import frappe
from frappe import _
from frappe.core.doctype.file.file import File
from frappe.core.doctype.file.utils import decode_file_content
from frappe.utils import cint
from PIL import Image, ImageOps

DOCTYPE = "Instrument"
IFU_MAX_BYTES = 20 * 1024 * 1024
IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000
THUMB_MAX_SIDE = 320
THUMB_QUALITY = 80
THUMB_FIELD = "image_thumbnail"
MEDIA_FIELDS = ("image", "ifu")
PRIVATE_PREFIX = "/private/files/"

# trường → (định dạng nhận theo nội dung, số byte tối đa)
RULES = {
	"ifu": (("pdf", "jpeg", "png"), IFU_MAX_BYTES),
	"image": (("jpeg", "png", "webp"), IMAGE_MAX_BYTES),
}
PILLOW_FORMATS = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
MIB = 1024 * 1024


def sniff(content: bytes) -> str | None:
	"""Định dạng theo magic bytes: ``pdf``, ``jpeg``, ``png``, ``webp``; khác (HTML, SVG, EXE, HEIC…) → None."""
	if not content:
		return None
	if content.startswith(b"%PDF-"):
		return "pdf"
	if content.startswith(b"\xff\xd8\xff"):
		return "jpeg"
	if content.startswith(b"\x89PNG\r\n\x1a\n"):
		return "png"
	if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
		return "webp"
	return None


# --- Lớp 0: kiểm trước khi Frappe đọc nội dung ---------------------------------------------------------------


class InstrumentMediaFile(File):
	"""File của Frappe, thêm ``precheck_upload`` chạy trước ``File.before_insert`` gốc (xem lớp 0 ở docstring module)."""

	def before_insert(self):
		precheck_upload(self)
		super().before_insert()


def precheck_upload(file_doc) -> None:
	"""Kiểm nội dung tải lên (trong bộ nhớ) của File đính vào ``ifu``/``image`` của Instrument, trước khi Frappe ghi đĩa.

	Chỉ áp dụng khi File mang nội dung (``content``, kể cả base64 ``decode``); File trỏ ``file_url`` có sẵn, File ngoài
	(``http…``), bản sao đính kèm (``copy_from_existing_file``) và thumbnail để ``check_upload`` xử lý như cũ. Không đổi
	``content``/``decode`` của File: Frappe tự giải mã lại khi ghi.
	"""
	field = _media_field(file_doc)
	if field not in MEDIA_FIELDS or file_doc.flags.copy_from_existing_file:
		return
	content = file_doc.get("content")
	if not content:
		return
	if file_doc.get("decode"):
		try:
			content = decode_file_content(content)
		except Exception:
			frappe.throw(_unreadable_message(), title=_("File not accepted"))
	if isinstance(content, str):
		content = content.encode()
	problem = inspect_content(content, field)[1]
	if problem:
		frappe.throw(problem, title=_("File not accepted"))


# --- Lớp 1: File.before_insert / File.validate --------------------------------------------------------------


def check_upload(file_doc, method=None) -> None:
	"""Hook ``File.before_insert``: kiểm File đính vào ``ifu``/``image``/``image_thumbnail`` của Instrument."""
	field = _media_field(file_doc)
	if not field:
		return
	content = _check_media_file(file_doc, field)
	if content is not None:
		_force_private(file_doc, content)
	file_doc.flags.tc_media_checked = True


# đổi một trong các trường này = File được đính (lại) vào chỗ khác hoặc trỏ sang blob khác → kiểm lại nội dung
REATTACH_FIELDS = ("attached_to_doctype", "attached_to_name", "attached_to_field", "file_url")


def validate_file(file_doc, method=None) -> None:
	"""Hook ``File.validate``: File có sẵn đính (lại) vào ảnh/IFU/thumbnail của dụng cụ được kiểm như khi tải lên.

	Lần insert đã kiểm ở ``check_upload``. File đã đính, lưu lại mà không đổi trường nào trong ``REATTACH_FIELDS`` thì
	không kiểm lại (File công khai cũ vẫn lưu được), nhưng không được chuyển riêng tư → công khai.
	"""
	field = _media_field(file_doc)
	if not field or (file_doc.flags.in_insert and file_doc.flags.tc_media_checked):
		return
	reattached = bool(file_doc.flags.in_insert) or any(
		file_doc.has_value_changed(name) for name in REATTACH_FIELDS
	)
	if not cint(file_doc.is_private) and (reattached or file_doc.has_value_changed("is_private")):
		frappe.throw(_("Instrument photos and IFU files must stay private."), title=_("File not accepted"))
	if reattached:
		_check_media_file(file_doc, field)


def _media_field(file_doc):
	"""Trường ảnh/IFU/thumbnail của Instrument mà File đính vào; khác (sidebar, DocType khác, thư mục) → None."""
	if file_doc.attached_to_doctype != DOCTYPE or file_doc.is_folder:
		return None
	field = file_doc.attached_to_field
	return field if field in (*MEDIA_FIELDS, THUMB_FIELD) else None


def _check_media_file(file_doc, field):
	"""Kiểm blob của File theo trường; lỗi → ``_reject``. Trả nội dung đã đọc (thumbnail của server → None)."""
	if field == THUMB_FIELD:
		if not file_doc.flags.tc_thumbnail:
			_reject(file_doc, _("The image thumbnail is generated by TraceCore and cannot be uploaded."))
		return None
	if file_doc.is_remote_file:
		_reject(
			file_doc,
			_(
				"Instrument photos and IFU files must be uploaded to TraceCore; links to other websites are not accepted."
			),
		)
	content, problem = inspect_blob(_local_path(file_doc), field)
	if problem:
		_reject(file_doc, problem)
	return content


def inspect_blob(path, field) -> tuple[bytes | None, str | None]:
	"""Đọc blob ở ``path`` (đã kiểm an toàn) theo luật của ``field``: ``(nội dung, None)`` hoặc ``(…, thông báo lỗi)``.

	Cỡ file kiểm bằng ``getsize`` trước khi đọc; định dạng theo magic bytes; PDF không có nội dung chủ động; ảnh mở
	được trong giới hạn điểm ảnh.
	"""
	max_bytes = RULES[field][1]
	if os.path.getsize(path) > max_bytes:
		return None, _too_big_message(field)
	with open(path, "rb") as handle:
		content = handle.read(max_bytes + 1)
	return inspect_content(content, field)


def inspect_content(content: bytes, field) -> tuple[bytes | None, str | None]:
	"""Như ``inspect_blob`` nhưng trên bytes đã có trong bộ nhớ (lớp 0 và lớp 1 dùng chung một luật)."""
	kinds, max_bytes = RULES[field]
	if len(content) > max_bytes:
		return None, _too_big_message(field)
	kind = sniff(content)
	if kind not in kinds:
		return content, _wrong_type_message(field)
	return content, _pdf_problem(content) if kind == "pdf" else _image_problem(content, kind)


def _too_big_message(field):
	if field == "ifu":
		return _(
			"The IFU file is larger than {0} MB and cannot be uploaded. You can save the instrument without an IFU."
		).format(IFU_MAX_BYTES // MIB)
	return _(
		"The instrument photo is larger than {0} MB and cannot be uploaded. Reduce the photo size and upload it again."
	).format(IMAGE_MAX_BYTES // MIB)


def _wrong_type_message(field):
	if field == "ifu":
		return _(
			"The IFU file must be a PDF, JPEG or PNG file (checked by its content, not by its name). Convert the file and upload it again."
		)
	return _(
		"The instrument photo must be a JPEG, PNG or WebP image (checked by its content, not by its name). SVG, HTML and HEIC files are not accepted: convert the photo to JPEG and upload it again."
	)


def _pixels_message():
	return _(
		"The image has more than {0} megapixels and cannot be uploaded. Reduce the resolution and upload it again."
	).format(IMAGE_MAX_PIXELS // 1_000_000)


def _unreadable_message():
	return _("The file is damaged or cannot be read. Upload another file.")


def _reject(file_doc, message):
	"""Xóa blob vừa ghi (khi không bản ghi File nào khác dùng chung) rồi báo lỗi; rollback của Frappe dọn nốt."""
	_discard_blob(file_doc)
	frappe.throw(message, title=_("File not accepted"))


def _discard_blob(file_doc):
	if not file_doc.flags.new_file or not file_doc.file_url or file_doc.is_remote_file:
		return
	if frappe.db.exists("File", {"file_url": file_doc.file_url}):
		return  # blob đã có sẵn của bản ghi khác (Frappe dùng lại theo content_hash)
	path = file_doc.get_full_path()
	if os.path.isfile(path):
		os.remove(path)


def _local_path(file_doc):
	"""Đường dẫn thật của blob, chỉ trong thư mục files công khai/riêng tư của site (chống path traversal)."""
	path = os.path.realpath(file_doc.get_full_path())
	roots = [
		os.path.realpath(frappe.get_site_path(*parts))
		for parts in (("private", "files"), ("public", "files"))
	]
	if not any(os.path.commonpath((root, path)) == root for root in roots) or not os.path.isfile(path):
		_reject(file_doc, _unreadable_message())
	return path


def _pdf_problem(content):
	try:
		unsafe = pdf_has_active_content(content)
	except Exception:
		return _unreadable_message()
	if unsafe:
		return _("This PDF contains scripts, embedded files or form actions and cannot be uploaded.")
	return None


# Tên PDF (làm khóa hoặc giá trị; pypdf đã giải mã ``#xx``) coi là nội dung chủ động: JavaScript, mở chương trình,
# file nhúng (``/EmbeddedFiles`` trong Names, ``/EF`` của Filespec, stream ``/Type /EmbeddedFile``), RichMedia
# (Flash/video nhúng), biểu mẫu XFA, mở file khác (``/GoToR``, ``/GoToE``), gửi/nhập dữ liệu biểu mẫu
# (``/SubmitForm``, ``/ImportData``). ``/URI`` (liên kết web, IFU của hãng thường có) **vẫn nhận**: người dùng phải
# bấm vào và trình xem PDF hỏi trước khi mở trang.
PDF_ACTIVE_KEYS = frozenset(
	(
		"/JS",
		"/JavaScript",
		"/Launch",
		"/EmbeddedFile",
		"/EmbeddedFiles",
		"/EF",
		"/RichMedia",
		"/XFA",
		"/GoToR",
		"/GoToE",
		"/SubmitForm",
		"/ImportData",
	)
)
PDF_MAX_NODES = 500_000


def pdf_has_active_content(content: bytes) -> bool:
	"""PDF có nội dung chủ động (một tên trong ``PDF_ACTIVE_KEYS`` làm khóa hoặc giá trị) ở bất kỳ đâu.

	Duyệt toàn bộ đồ thị đối tượng từ trailer, **giải tham chiếu gián tiếp**, kể cả đối tượng nằm trong object stream
	(``frappe.utils.pdf.pdf_contains_js`` bỏ qua ``/Root`` gián tiếp nên lọt ``/OpenAction`` JavaScript ở catalog). PDF mã hóa chỉ đọc được khi mật khẩu
	người dùng rỗng; không đọc được hoặc quá nhiều đối tượng → ``ValueError`` (coi là file hỏng).
	"""
	from pypdf import PdfReader
	from pypdf.generic import IndirectObject

	reader = PdfReader(io.BytesIO(content))
	if reader.is_encrypted and not reader.decrypt(""):
		raise ValueError("encrypted")
	stack, seen, visited = [reader.trailer], set(), 0
	while stack:
		node = stack.pop()
		if isinstance(node, IndirectObject):
			key = (node.idnum, node.generation)
			if key in seen:
				continue
			seen.add(key)
			node = node.get_object()
		visited += 1
		if visited > PDF_MAX_NODES:
			raise ValueError("too many objects")
		if isinstance(node, dict):
			for name, value in node.items():
				if name in PDF_ACTIVE_KEYS or (isinstance(value, str) and value in PDF_ACTIVE_KEYS):
					return True
				stack.append(value)
		elif isinstance(node, list):
			stack.extend(node)
	return False


def open_image(content, kind=None):
	"""Mở ảnh JPEG/PNG/WebP từ bytes với giới hạn điểm ảnh (chống bom giải nén); lỗi → ``ValueError``.

	Chỉ đọc phần đầu (kích thước) trước khi kiểm; ``DecompressionBombWarning``/``Error`` của Pillow cũng là lỗi.
	"""
	formats = [PILLOW_FORMATS[kind]] if kind else list(PILLOW_FORMATS.values())
	with warnings.catch_warnings():
		warnings.simplefilter("error", Image.DecompressionBombWarning)
		try:
			image = Image.open(io.BytesIO(content), formats=formats)
		except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
			raise ValueError("pixels") from error
		except Exception as error:
			raise ValueError("unreadable") from error
	width, height = image.size
	if width * height > IMAGE_MAX_PIXELS:
		raise ValueError("pixels")
	return image


def _image_problem(content, kind):
	try:
		image = open_image(content, kind)
		image.verify()
	except ValueError as error:
		return _pixels_message() if str(error) == "pixels" else _unreadable_message()
	except Exception:
		return _unreadable_message()
	return None


def _force_private(file_doc, content):
	"""Frappe đã ghi blob theo ``is_private`` người gửi chọn; công khai thì ghi lại vào thư mục riêng tư.

	Bản công khai vừa ghi (``flags.new_file``, không bản ghi File nào khác dùng chung URL) bị xóa **trước** khi ghi
	bản riêng tư, theo đường dẫn đã kiểm ở ``_local_path``: ghi lại lỗi giữa chừng cũng không để lại blob công khai mồ
	côi (nội dung vẫn còn trong bộ nhớ).
	"""
	if cint(file_doc.is_private):
		return
	public_path = _local_path(file_doc)
	shared = frappe.db.exists("File", {"file_url": file_doc.file_url})
	if file_doc.flags.new_file and not shared and os.path.isfile(public_path):
		os.remove(public_path)
	file_doc.is_private = 1
	file_doc.file_url = None
	file_doc.save_file(content=content)


# --- Lớp 2: Instrument.validate -------------------------------------------------------------------------------


def validate_fields(doc) -> None:
	"""``image``/``ifu`` rỗng, hoặc URL của File riêng tư đính vào chính dụng cụ đúng trường; khác → lỗi."""
	before = None if doc.is_new() else doc.get_doc_before_save()
	names = [name for name in (doc.name, doc.get("__temporary_name")) if name]
	for field in MEDIA_FIELDS:
		value = (doc.get(field) or "").strip()
		doc.set(field, value or None)
		if not value or (before and (before.get(field) or "") == value):
			continue
		file_name = _own_private_file(value, field, names)
		if not file_name:
			frappe.throw(
				_(
					"{0} must be a private file uploaded to this instrument (no external links or files of other records)."
				).format(_(doc.meta.get_label(field), context=DOCTYPE)),
				title=_("File not accepted"),
			)
		# phòng thủ nhiều lớp: File có thể bị gắn ở DB, bỏ qua hook File → đọc lại blob và kiểm nội dung
		problem = inspect_blob(_safe_path(frappe.get_doc("File", file_name)), field)[1]
		if problem:
			frappe.throw(problem, title=_("File not accepted"))


def _own_private_file(url, field, names):
	"""Tên File riêng tư có URL ``url`` đính vào dụng cụ (``names``) đúng trường ``field``; không có → None."""
	if not url.startswith(PRIVATE_PREFIX) or any(part in url for part in ("..", "\\", "?", "#", "\x00")):
		return None
	if not names:
		return None
	return frappe.db.get_value(
		"File",
		{
			"file_url": url,
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": ["in", names],
			"attached_to_field": field,
			"is_private": 1,
		},
		"name",
	)


def _file_of(url, instrument_names):
	if not url:
		return None
	name = frappe.db.get_value(
		"File",
		{"file_url": url, "attached_to_doctype": DOCTYPE, "attached_to_name": ["in", instrument_names]},
		"name",
	)
	return frappe.get_doc("File", name) if name else None


def refresh_thumbnail(doc) -> str | None:
	"""Ảnh đổi → File thumbnail mới (xoay theo EXIF, 320 px, JPEG q80, không EXIF) gán ``image_thumbnail``.

	Ảnh không đổi → giữ thumbnail. Ảnh đổi hoặc bị xóa → bản ghi File của thumbnail **cũ** (đính vào chính dụng cụ ở
	trường ``image_thumbnail``) bị xóa trong cùng giao dịch, blob của nó xóa **sau khi commit** nếu không còn bản ghi
	File hay dụng cụ nào trỏ tới (rollback giữ nguyên cả hai). Thumbnail là dữ liệu dẫn xuất, không phải chứng từ;
	lần đổi ``image_thumbnail`` vẫn vào Audit Log của dụng cụ. Trả URL thumbnail.
	"""
	before = None if doc.is_new() else doc.get_doc_before_save()
	if before and (before.get("image") or None) == (doc.image or None):
		return doc.image_thumbnail or None
	names = [name for name in (doc.name, doc.get("__temporary_name")) if name]
	old_rows = _thumbnail_rows(before.get(THUMB_FIELD) if before else None, names)
	url = _build_thumbnail(doc, names)
	_drop_thumbnail_rows(old_rows)
	return url


def _build_thumbnail(doc, names):
	if not doc.image:
		doc.image_thumbnail = None
		return None
	source = _file_of(doc.image, names)
	if not source:
		doc.image_thumbnail = None
		return None
	with open(_safe_path(source), "rb") as handle:
		content = handle.read(IMAGE_MAX_BYTES + 1)
	try:
		thumbnail = make_thumbnail(content)
	except Exception:
		frappe.throw(_unreadable_message(), title=_("File not accepted"))
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.name.lower()}-thumb.jpg",
			"content": thumbnail,
			"is_private": 1,
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": doc.name,
			"attached_to_field": THUMB_FIELD,
		}
	)
	file_doc.flags.tc_thumbnail = True
	file_doc.insert(ignore_permissions=True)
	doc.image_thumbnail = file_doc.file_url
	return doc.image_thumbnail


def _thumbnail_rows(url, names):
	"""Tên các bản ghi File thumbnail có URL ``url`` đính vào dụng cụ (``names``), lấy trước khi sinh thumbnail mới."""
	if not url or not names:
		return []
	return frappe.get_all(
		"File",
		filters={
			"file_url": url,
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": ["in", names],
			"attached_to_field": THUMB_FIELD,
		},
		pluck="name",
	)


def _drop_thumbnail_rows(rows):
	"""Xóa bản ghi File thumbnail cũ (trong giao dịch); blob xóa sau commit nếu không còn ai trỏ tới."""
	if not rows:
		return
	urls = set(frappe.get_all("File", filters={"name": ["in", rows]}, pluck="file_url"))
	frappe.db.delete("File", {"name": ["in", rows]})
	for url in urls:
		frappe.db.after_commit.add(lambda url=url: _remove_orphan_blob(url))


def _remove_orphan_blob(url):
	"""Sau commit: xóa blob riêng tư ``url`` khi không bản ghi File nào và không dụng cụ nào còn trỏ tới."""
	if not url or not url.startswith(PRIVATE_PREFIX):
		return
	if frappe.db.exists("File", {"file_url": url}):
		return
	if frappe.db.exists(DOCTYPE, {THUMB_FIELD: url}) or frappe.db.exists(DOCTYPE, {"image": url}):
		return
	root = os.path.realpath(frappe.get_site_path("private", "files"))
	path = os.path.realpath(os.path.join(root, url[len(PRIVATE_PREFIX) :]))
	if os.path.commonpath((root, path)) == root and path != root and os.path.isfile(path):
		os.remove(path)


def _safe_path(file_doc):
	"""Đường dẫn thật của blob riêng tư, chỉ trong ``private/files`` của site và phải tồn tại; khác → lỗi."""
	path = os.path.realpath(file_doc.get_full_path())
	root = os.path.realpath(frappe.get_site_path("private", "files"))
	if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
		frappe.throw(_unreadable_message(), title=_("File not accepted"))
	return path


def make_thumbnail(content: bytes) -> bytes:
	"""JPEG q80 cạnh dài ``THUMB_MAX_SIDE``, đúng hướng theo EXIF, không mang EXIF/ICC/metadata."""
	image = open_image(content)
	if image.format == "JPEG":
		image.draft("RGB", (THUMB_MAX_SIDE * 2, THUMB_MAX_SIDE * 2))
	image = ImageOps.exif_transpose(image)
	if image.mode.startswith("I;16") or image.mode == "I":
		# PNG xám 16 bit (0-65535): convert("RGB") của Pillow cắt ở 255 (gần như trắng hết) → co về 8 bit theo tỉ lệ
		image = image.convert("I").point(lambda value: value * (1 / 257)).convert("L")
	if image.mode in ("RGBA", "LA", "PA", "P") or "transparency" in image.info:
		image = image.convert("RGBA")
		background = Image.new("RGB", image.size, (255, 255, 255))
		background.paste(image, mask=image.getchannel("A"))
		image = background
	else:
		image = image.convert("RGB")
	image.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.Resampling.LANCZOS)
	clean = Image.new("RGB", image.size)
	clean.paste(image)
	buffer = io.BytesIO()
	clean.save(buffer, format="JPEG", quality=THUMB_QUALITY, optimize=True)
	return buffer.getvalue()


def image_info(instrument: str) -> dict:
	"""``{instrument, image_url, thumbnail_url, etag, has_image}``; dụng cụ không có → ``DoesNotExistError``.

	``etag`` = ``content_hash`` của File thumbnail (không có thumbnail thì của File ảnh gốc, không có ảnh → None).
	"""
	row = frappe.db.get_value(DOCTYPE, instrument, ["name", "image", "image_thumbnail"], as_dict=True)
	if not row:
		raise frappe.DoesNotExistError(_("Instrument {0} not found.").format(instrument))
	etag = None
	for url in (row.image_thumbnail, row.image):
		if url and not etag:
			etag = frappe.db.get_value(
				"File",
				{"file_url": url, "attached_to_doctype": DOCTYPE, "attached_to_name": row.name},
				"content_hash",
			)
	return {
		"instrument": row.name,
		"image_url": row.image or None,
		"thumbnail_url": row.image_thumbnail or None,
		"etag": etag or None,
		"has_image": bool(row.image),
	}
