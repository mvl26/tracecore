"""Ảnh thực tế và IFU của dụng cụ, ảnh bộ đã xếp của loại bộ, thumbnail cho trạm (FR-M1-01.5/.6, FR-M1-03,
A-06 I11/I12, A-07 S6, architecture R-08).

Luật tra theo đích ``(DocType, trường)`` trong ``TARGETS`` (``Rule``: định dạng theo nội dung, số byte tối đa, trường
thumbnail do server ghi). Đích hiện có: ``Instrument.image`` (ảnh, thumbnail ``image_thumbnail``), ``Instrument.ifu``
(PDF/ảnh, không thumbnail) và ba ảnh bộ đã xếp ``Instrument Set Type.tray_image``/``tray_image_2``/``tray_image_3``
(cùng luật ảnh dụng cụ, thumbnail ``tray_thumbnail``/``_2``/``_3``; FEAT-015 S6). File đính vào DocType/trường khác
(đính kèm sidebar, app khác) không bị đụng tới. Hằng ``DOCTYPE``/``MEDIA_FIELDS``/``THUMB_FIELD``/``RULES`` là bí danh
của Instrument (FEAT-014).

Kiểm hai lớp (mô tả theo Instrument; mọi đích trong ``TARGETS`` đi qua đúng các lớp này):

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

Thumbnail: 320 px cạnh dài, xoay theo EXIF rồi bỏ EXIF, JPEG q80, File riêng tư đính vào chính bản ghi ở trường
thumbnail; ``etag`` = ``content_hash`` của File thumbnail (đổi ảnh → đổi etag) để Service Worker cache theo phiên bản
(FEAT-009). Ba ảnh bộ đã xếp cùng luật file nên đổi chỗ được cho nhau (nút đổi thứ tự trên form đổi giá trị): File
của ảnh nào trong ba trường cũng nhận ở trường khác, thumbnail đi theo ảnh. Ảnh in cho phiếu kiểm đếm
(``print_image_data_uri``) dựng trong bộ nhớ từ ảnh gốc riêng tư (1200 px, JPEG q85, ``data:`` URI).
"""

import base64
import io
import os
import warnings
from typing import NamedTuple
from urllib.parse import unquote

import frappe
from frappe import _
from frappe.core.doctype.file.file import File
from frappe.core.doctype.file.utils import decode_file_content
from frappe.utils import cint
from PIL import Image, ImageOps

IFU_MAX_BYTES = 20 * 1024 * 1024
IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000
THUMB_MAX_SIDE = 320
THUMB_QUALITY = 80
PRINT_MAX_SIDE = 1200
PRINT_QUALITY = 85
PRIVATE_PREFIX = "/private/files/"
PUBLIC_PREFIX = "/files/"
IMAGE_KINDS = ("jpeg", "png", "webp")


class Rule(NamedTuple):
	"""Luật file của một đích: định dạng nhận (theo nội dung), số byte tối đa, trường thumbnail (None = không có)."""

	kinds: tuple[str, ...]
	max_bytes: int
	thumb_field: str | None


SET_TYPE = "Instrument Set Type"
TRAY_FIELDS = ("tray_image", "tray_image_2", "tray_image_3")  # ảnh bộ đã xếp 1..3 (FEAT-015 S6)

# (DocType, trường) → luật; chỉ các đích này bị kiểm (lớp File ghi đè không đụng File của DocType/trường khác)
TARGETS: dict[tuple[str, str], Rule] = {
	("Instrument", "image"): Rule(IMAGE_KINDS, IMAGE_MAX_BYTES, "image_thumbnail"),
	("Instrument", "ifu"): Rule(("pdf", "jpeg", "png"), IFU_MAX_BYTES, None),
	(SET_TYPE, "tray_image"): Rule(IMAGE_KINDS, IMAGE_MAX_BYTES, "tray_thumbnail"),
	(SET_TYPE, "tray_image_2"): Rule(IMAGE_KINDS, IMAGE_MAX_BYTES, "tray_thumbnail_2"),
	(SET_TYPE, "tray_image_3"): Rule(IMAGE_KINDS, IMAGE_MAX_BYTES, "tray_thumbnail_3"),
}
# (DocType, trường thumbnail) → trường ảnh nguồn
THUMB_SOURCES = {
	(doctype, rule.thumb_field): field for (doctype, field), rule in TARGETS.items() if rule.thumb_field
}

# bí danh FEAT-014 (Instrument)
DOCTYPE = "Instrument"
THUMB_FIELD = "image_thumbnail"
MEDIA_FIELDS = ("image", "ifu")
RULES = {
	field: (rule.kinds, rule.max_bytes) for (doctype, field), rule in TARGETS.items() if doctype == DOCTYPE
}
PILLOW_FORMATS = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
MIB = 1024 * 1024


def media_fields(doctype) -> tuple[str, ...]:
	"""Trường ảnh/file có luật của ``doctype`` theo thứ tự khai báo trong ``TARGETS``."""
	return tuple(field for (target, field) in TARGETS if target == doctype)


def thumb_fields(doctype) -> tuple[str, ...]:
	"""Trường thumbnail (chỉ server ghi) của ``doctype``."""
	return tuple(field for (target, field) in THUMB_SOURCES if target == doctype)


def _sibling_fields(doctype, field) -> tuple[str, ...]:
	"""Các trường của ``doctype`` cùng luật file với ``field`` (ba ảnh khay đổi chỗ được; ảnh ≠ IFU của dụng cụ)."""
	rule = TARGETS[(doctype, field)]
	return tuple(
		other
		for (target, other), other_rule in TARGETS.items()
		if target == doctype and (other_rule.kinds, other_rule.max_bytes) == (rule.kinds, rule.max_bytes)
	)


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
	"""Kiểm File đính vào một đích của ``TARGETS`` (ảnh/IFU dụng cụ, ảnh khay loại bộ) hoặc trường thumbnail của đích
	trước khi Frappe đọc hoặc ghi blob.

	- Trường thumbnail (``image_thumbnail``, ``tray_thumbnail*``) không do server sinh (thiếu ``flags.tc_thumbnail``) → từ chối ngay, chưa ghi blob nào.
	- File mang nội dung (``content``, kể cả base64 ``decode``): kiểm nội dung trong bộ nhớ. Không đổi
	  ``content``/``decode`` của File: Frappe tự giải mã lại khi ghi.
	- File trỏ ``file_url`` có sẵn trên site (chọn từ Library, hoặc blob cũ không có bản ghi File): đọc blob như lớp 1
	  (``inspect_blob``: kiểm cỡ bằng ``getsize`` trước, đọc tối đa giới hạn + 1 byte), vì ``File.before_insert`` của
	  Frappe sẽ đọc lại blob đó (bỏ EXIF ``.jpg``, đọc ``.pdf``) trước mọi hook.
	- File ngoài (``http…``) và bản sao đính kèm (``copy_from_existing_file``, Frappe không đọc blob) để ``check_upload``
	  xử lý như cũ.

	Ghi chú (Minor 3, không sửa được an toàn): ``frappe.core.doctype.file.utils.attach_files_to_document`` (on_update
	của mọi DocType) tự tạo File cho URL trong trường Attach chưa có File đính kèm và nuốt mọi lỗi khi insert (ghi
	Error Log, thông báo của ``frappe.throw`` vẫn hiện). Giá trị mới của ``image``/``ifu`` luôn là File riêng tư đính
	vào chính dụng cụ (``validate_fields``) và ``image_thumbnail`` là File server tạo, nên hàm đó gặp File có sẵn và bỏ
	qua. Chỉ URL cũ trước FEAT-014 không có File đính kèm mới đi vào nhánh tạo File: File đó qua đúng các lớp kiểm này;
	bị từ chối thì File không được tạo (dụng cụ vẫn lưu, URL cũ giữ nguyên, Error Log ghi lại) — không có blob nào
	được nhận mà chưa kiểm. Muốn báo lỗi thay vì nuốt phải vá Frappe, ngoài phạm vi.
	"""
	target = _media_target(file_doc)
	if not target:
		return
	if target in THUMB_SOURCES:
		if not file_doc.flags.tc_thumbnail:
			frappe.throw(_thumbnail_upload_message(), title=_("File not accepted"))
		return
	if file_doc.flags.copy_from_existing_file:
		return
	content = file_doc.get("content")
	if not content:
		_precheck_existing_blob(file_doc, target)
		return
	if file_doc.get("decode"):
		try:
			content = decode_file_content(content)
		except Exception:
			frappe.throw(_unreadable_message(), title=_("File not accepted"))
	if isinstance(content, str):
		content = content.encode()
	problem = inspect_content(content, target[1], target[0])[1]
	if problem:
		frappe.throw(problem, title=_("File not accepted"))


def _precheck_existing_blob(file_doc, target):
	"""File mới trỏ ``file_url`` cục bộ có sẵn: kiểm blob trước khi Frappe đọc nó; File ngoài/không URL → bỏ qua."""
	if not file_doc.file_url or file_doc.is_remote_file:
		return
	# Frappe bỏ mã hóa %xx của file_url ngay đầu before_insert; làm trước để đọc đúng blob đó. Chưa có file_name
	# (Frappe đặt sau) nên không dùng get_full_path: tự dựng đường dẫn trong thư mục files của site.
	url = file_doc.file_url = unquote(file_doc.file_url)
	for prefix, parts in ((PRIVATE_PREFIX, ("private", "files")), (PUBLIC_PREFIX, ("public", "files"))):
		if url.startswith(prefix):
			root = os.path.realpath(frappe.get_site_path(*parts))
			path = os.path.realpath(os.path.join(root, url[len(prefix) :]))
			break
	else:
		return  # URL không phải file của site: File.validate_file_url của Frappe từ chối
	if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
		frappe.throw(_unreadable_message(), title=_("File not accepted"))
	problem = inspect_blob(path, target[1], target[0])[1]
	if problem:
		frappe.throw(problem, title=_("File not accepted"))


def _thumbnail_upload_message():
	return _("The image thumbnail is generated by TraceCore and cannot be uploaded.")


# --- Lớp 1: File.before_insert / File.validate --------------------------------------------------------------


def check_upload(file_doc, method=None) -> None:
	"""Hook ``File.before_insert``: kiểm File đính vào một đích của ``TARGETS`` (hoặc trường thumbnail của đích)."""
	target = _media_target(file_doc)
	if not target:
		return
	content = _check_media_file(file_doc, target)
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
	target = _media_target(file_doc)
	if not target or (file_doc.flags.in_insert and file_doc.flags.tc_media_checked):
		return
	reattached = bool(file_doc.flags.in_insert) or any(
		file_doc.has_value_changed(name) for name in REATTACH_FIELDS
	)
	if not cint(file_doc.is_private) and (reattached or file_doc.has_value_changed("is_private")):
		frappe.throw(_must_stay_private_message(target[0]), title=_("File not accepted"))
	if reattached:
		_check_media_file(file_doc, target)


def _media_target(file_doc):
	"""``(DocType, trường)`` mà File đính vào nếu là đích của ``TARGETS`` hoặc trường thumbnail của đích; khác
	(sidebar, DocType/trường khác, thư mục) → None."""
	if not file_doc.attached_to_doctype or file_doc.is_folder:
		return None
	target = (file_doc.attached_to_doctype, file_doc.attached_to_field)
	return target if target in TARGETS or target in THUMB_SOURCES else None


def _check_media_file(file_doc, target):
	"""Kiểm blob của File theo đích; lỗi → ``_reject``. Trả nội dung đã đọc (thumbnail của server → None)."""
	if target in THUMB_SOURCES:
		if not file_doc.flags.tc_thumbnail:
			_reject(file_doc, _thumbnail_upload_message())
		return None
	doctype, field = target
	if file_doc.is_remote_file:
		_reject(file_doc, _remote_message(doctype))
	content, problem = inspect_blob(_local_path(file_doc), field, doctype)
	if problem:
		_reject(file_doc, problem)
	return content


def inspect_blob(path, field, doctype=DOCTYPE) -> tuple[bytes | None, str | None]:
	"""Đọc blob ở ``path`` (đã kiểm an toàn) theo luật của ``(doctype, field)``: ``(nội dung, None)`` hoặc
	``(…, thông báo lỗi)``.

	Cỡ file kiểm bằng ``getsize`` trước khi đọc; định dạng theo magic bytes; PDF không có nội dung chủ động; ảnh mở
	được trong giới hạn điểm ảnh.
	"""
	max_bytes = TARGETS[(doctype, field)].max_bytes
	if os.path.getsize(path) > max_bytes:
		return None, _too_big_message(doctype, field)
	with open(path, "rb") as handle:
		content = handle.read(max_bytes + 1)
	return inspect_content(content, field, doctype)


def inspect_content(content: bytes, field, doctype=DOCTYPE) -> tuple[bytes | None, str | None]:
	"""Như ``inspect_blob`` nhưng trên bytes đã có trong bộ nhớ (lớp 0 và lớp 1 dùng chung một luật)."""
	kinds, max_bytes, _thumb = TARGETS[(doctype, field)]
	if len(content) > max_bytes:
		return None, _too_big_message(doctype, field)
	kind = sniff(content)
	if kind not in kinds:
		return content, _wrong_type_message(doctype, field)
	return content, _pdf_problem(content) if kind == "pdf" else _image_problem(content, kind)


def _too_big_message(doctype, field):
	if doctype == SET_TYPE:
		return _(
			"The set photo is larger than {0} MB and cannot be uploaded. Reduce the photo size and upload it again."
		).format(TARGETS[(doctype, field)].max_bytes // MIB)
	if field == "ifu":
		return _(
			"The IFU file is larger than {0} MB and cannot be uploaded. You can save the instrument without an IFU."
		).format(IFU_MAX_BYTES // MIB)
	return _(
		"The instrument photo is larger than {0} MB and cannot be uploaded. Reduce the photo size and upload it again."
	).format(IMAGE_MAX_BYTES // MIB)


def _wrong_type_message(doctype, field):
	if doctype == SET_TYPE:
		return _(
			"The set photo must be a JPEG, PNG or WebP image (checked by its content, not by its name). SVG, HTML and HEIC files are not accepted: convert the photo to JPEG and upload it again."
		)
	if field == "ifu":
		return _(
			"The IFU file must be a PDF, JPEG or PNG file (checked by its content, not by its name). Convert the file and upload it again."
		)
	return _(
		"The instrument photo must be a JPEG, PNG or WebP image (checked by its content, not by its name). SVG, HTML and HEIC files are not accepted: convert the photo to JPEG and upload it again."
	)


def _remote_message(doctype):
	if doctype == SET_TYPE:
		return _("Set photos must be uploaded to TraceCore; links to other websites are not accepted.")
	return _(
		"Instrument photos and IFU files must be uploaded to TraceCore; links to other websites are not accepted."
	)


def _must_stay_private_message(doctype):
	if doctype == SET_TYPE:
		return _("Set photos must stay private.")
	return _("Instrument photos and IFU files must stay private.")


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


# --- Lớp 2: <DocType>.validate (Instrument, Instrument Set Type) ----------------------------------------------


def validate_fields(doc) -> None:
	"""Trường file của ``doc`` (theo ``TARGETS``) rỗng, hoặc URL của File riêng tư đính vào chính bản ghi ở trường
	cùng luật; khác → lỗi. Trường thumbnail chỉ server ghi (``refresh_thumbnail``): đổi tay → lỗi."""
	before = None if doc.is_new() else doc.get_doc_before_save()
	names = [name for name in (doc.name, doc.get("__temporary_name")) if name]
	for field in media_fields(doc.doctype):
		value = (doc.get(field) or "").strip()
		doc.set(field, value or None)
		if not value or (before and (before.get(field) or "") == value):
			continue
		file_name = _own_private_file(doc.doctype, value, _sibling_fields(doc.doctype, field), names)
		if not file_name:
			frappe.throw(_own_file_message(doc, field), title=_("File not accepted"))
		# phòng thủ nhiều lớp: File có thể bị gắn ở DB, bỏ qua hook File → đọc lại blob và kiểm nội dung
		problem = inspect_blob(_safe_path(frappe.get_doc("File", file_name)), field, doc.doctype)[1]
		if problem:
			frappe.throw(problem, title=_("File not accepted"))
	_guard_thumbnail_fields(doc, before)


def _own_file_message(doc, field):
	label = _(doc.meta.get_label(field), context=doc.doctype)
	if doc.doctype == SET_TYPE:
		return _(
			"{0} must be a private file uploaded to this set type (no external links or files of other records)."
		).format(label)
	return _(
		"{0} must be a private file uploaded to this instrument (no external links or files of other records)."
	).format(label)


def _guard_thumbnail_fields(doc, before):
	"""Trường thumbnail chỉ ``refresh_thumbnail`` ghi (cờ ``flags.tc_thumbnail`` của File); giá trị khác bản đã lưu → lỗi."""
	for field in thumb_fields(doc.doctype):
		old = before.get(field) if before else None
		if (doc.get(field) or "") != (old or ""):
			frappe.throw(
				_("The photo thumbnail is generated by TraceCore from the photo and cannot be edited."),
				title=_("File not accepted"),
			)


def _own_private_file(doctype, url, fields, names):
	"""Tên File riêng tư có URL ``url`` đính vào bản ghi ``names`` của ``doctype`` ở một trong ``fields``; không có → None."""
	if not url.startswith(PRIVATE_PREFIX) or any(part in url for part in ("..", "\\", "?", "#", "\x00")):
		return None
	if not names:
		return None
	return frappe.db.get_value(
		"File",
		{
			"file_url": url,
			"attached_to_doctype": doctype,
			"attached_to_name": ["in", names],
			"attached_to_field": ["in", list(fields)],
			"is_private": 1,
		},
		"name",
	)


def _file_of(doctype, url, names):
	if not url:
		return None
	name = frappe.db.get_value(
		"File",
		{"file_url": url, "attached_to_doctype": doctype, "attached_to_name": ["in", names]},
		"name",
	)
	return frappe.get_doc("File", name) if name else None


def refresh_thumbnail(doc) -> dict[str, str | None]:
	"""Mỗi ảnh đổi → File thumbnail mới (xoay theo EXIF, 320 px, JPEG q80, không EXIF) gán trường thumbnail của nó.

	Ảnh không đổi → giữ thumbnail. Ảnh đổi hoặc bị xóa → bản ghi File của thumbnail **cũ** (đính vào chính bản ghi ở
	trường thumbnail đó) bị xóa trong cùng giao dịch, blob của nó xóa **sau khi commit** nếu không còn bản ghi File
	hay bản ghi đích nào trỏ tới (rollback giữ nguyên cả hai). Đổi chỗ ảnh (ảnh khay 1 ↔ 3) → thumbnail sinh lại theo
	ảnh mới của từng trường (cùng nội dung nên Frappe dùng lại blob theo ``content_hash``). Thumbnail là dữ liệu dẫn
	xuất, không phải chứng từ; lần đổi vẫn vào Audit Log của bản ghi. Trả ``{trường thumbnail: URL | None}``.
	"""
	before = None if doc.is_new() else doc.get_doc_before_save()
	names = [name for name in (doc.name, doc.get("__temporary_name")) if name]
	result, changed = {}, []
	for field in media_fields(doc.doctype):
		thumb = TARGETS[(doc.doctype, field)].thumb_field
		if not thumb:
			continue
		if before and (before.get(field) or None) == (doc.get(field) or None):
			result[thumb] = doc.get(thumb) or None
		else:
			changed.append((field, thumb))
	# lấy mọi thumbnail cũ trước khi sinh mới: thumbnail mới có thể dùng lại blob (URL) của thumbnail cũ trường khác
	old_rows = [
		row
		for _field, thumb in changed
		for row in _thumbnail_rows(doc.doctype, thumb, before.get(thumb) if before else None, names)
	]
	for field, thumb in changed:
		result[thumb] = _build_thumbnail(doc, field, thumb, names)
	_drop_thumbnail_rows(old_rows)
	return result


def _build_thumbnail(doc, field, thumb, names):
	source = _file_of(doc.doctype, doc.get(field), names) if doc.get(field) else None
	if not source:
		doc.set(thumb, None)
		return None
	with open(_safe_path(source), "rb") as handle:
		content = handle.read(TARGETS[(doc.doctype, field)].max_bytes + 1)
	try:
		thumbnail = make_thumbnail(content)
	except Exception:
		frappe.throw(_unreadable_message(), title=_("File not accepted"))
	suffix = "thumb" if doc.doctype == DOCTYPE else thumb.replace("_", "-")
	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.name.lower()}-{suffix}.jpg",
			"content": thumbnail,
			"is_private": 1,
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"attached_to_field": thumb,
		}
	)
	file_doc.flags.tc_thumbnail = True
	file_doc.insert(ignore_permissions=True)
	doc.set(thumb, file_doc.file_url)
	return file_doc.file_url


def _thumbnail_rows(doctype, thumb, url, names):
	"""Tên các bản ghi File thumbnail có URL ``url`` đính vào bản ghi ``names`` ở trường ``thumb``, lấy trước khi
	sinh thumbnail mới."""
	if not url or not names:
		return []
	return frappe.get_all(
		"File",
		filters={
			"file_url": url,
			"attached_to_doctype": doctype,
			"attached_to_name": ["in", names],
			"attached_to_field": thumb,
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
	"""Sau commit: xóa blob riêng tư ``url`` khi không bản ghi File nào và không trường ảnh/thumbnail nào của các
	đích (``TARGETS``) còn trỏ tới."""
	if not url or not url.startswith(PRIVATE_PREFIX):
		return
	if frappe.db.exists("File", {"file_url": url}):
		return
	for (doctype, field), rule in TARGETS.items():
		for name in (field, rule.thumb_field):
			if name and frappe.db.exists(doctype, {name: url}):
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
	return render_jpeg(content, THUMB_MAX_SIDE, THUMB_QUALITY)


def render_jpeg(content: bytes, max_side: int, quality: int) -> bytes:
	"""Ảnh JPEG/PNG/WebP → JPEG ``quality`` cạnh dài ≤ ``max_side`` (không phóng to), đúng hướng theo EXIF, nền trắng
	cho vùng trong suốt, không mang EXIF/ICC/metadata. Ảnh hỏng/quá giới hạn điểm ảnh → ``ValueError``."""
	image = open_image(content)
	if image.format == "JPEG":
		image.draft("RGB", (max_side * 2, max_side * 2))
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
	image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
	clean = Image.new("RGB", image.size)
	clean.paste(image)
	buffer = io.BytesIO()
	clean.save(buffer, format="JPEG", quality=quality, optimize=True)
	return buffer.getvalue()


def _etag(doctype, name, urls):
	"""``content_hash`` của File đầu tiên (theo thứ tự ``urls``) đính vào bản ghi; không có → None."""
	for url in urls:
		if not url:
			continue
		etag = frappe.db.get_value(
			"File",
			{"file_url": url, "attached_to_doctype": doctype, "attached_to_name": name},
			"content_hash",
		)
		if etag:
			return etag
	return None


def image_info(instrument: str) -> dict:
	"""``{instrument, image_url, thumbnail_url, etag, has_image}``; dụng cụ không có → ``DoesNotExistError``.

	``etag`` = ``content_hash`` của File thumbnail (không có thumbnail thì của File ảnh gốc, không có ảnh → None).
	"""
	row = frappe.db.get_value(DOCTYPE, instrument, ["name", "image", "image_thumbnail"], as_dict=True)
	if not row:
		raise frappe.DoesNotExistError(_("Instrument {0} not found.").format(instrument))
	return {
		"instrument": row.name,
		"image_url": row.image or None,
		"thumbnail_url": row.image_thumbnail or None,
		"etag": _etag(DOCTYPE, row.name, (row.image_thumbnail, row.image)),
		"has_image": bool(row.image),
	}


def set_type_photos(set_type: str) -> list[dict]:
	"""Ảnh bộ đã xếp của loại bộ: ``[{position, image_url, thumbnail_url, etag}]`` chỉ ảnh có giá trị, theo thứ tự
	1..3 (``position`` giữ số ảnh, vd ảnh 2 trống → 1, 3). ``etag`` như ``image_info``. Không có → ``DoesNotExistError``.
	"""
	thumbs = [TARGETS[(SET_TYPE, field)].thumb_field for field in TRAY_FIELDS]
	row = frappe.db.get_value(SET_TYPE, set_type, ["name", *TRAY_FIELDS, *thumbs], as_dict=True)
	if not row:
		raise frappe.DoesNotExistError(_("Set type {0} not found.").format(set_type))
	photos = []
	for position, (field, thumb) in enumerate(zip(TRAY_FIELDS, thumbs, strict=True), 1):
		if not row.get(field):
			continue
		photos.append(
			{
				"position": position,
				"image_url": row.get(field),
				"thumbnail_url": row.get(thumb) or None,
				"etag": _etag(SET_TYPE, row.name, (row.get(thumb), row.get(field))),
			}
		)
	return photos


def print_image_data_uri(file_url: str, max_side: int = PRINT_MAX_SIDE) -> str | None:
	"""Ảnh in (phiếu kiểm đếm, AC-3): ``data:image/jpeg;base64,…`` dựng trong bộ nhớ từ File **riêng tư** của site.

	Đúng hướng theo EXIF, cạnh dài ≤ ``max_side`` (không phóng to), JPEG q85, không EXIF. Chỉ URL ``/private/files/…``
	có bản ghi File riêng tư, blob nằm trong ``private/files`` của site, ≤ 5 MiB và là ảnh JPEG/PNG/WebP hợp lệ; khác
	(URL ngoài, file công khai, thoát thư mục, không phải ảnh, hỏng) → None. Không đọc mạng, không ghi File.
	"""
	if not isinstance(file_url, str) or not file_url.startswith(PRIVATE_PREFIX):
		return None
	if any(part in file_url for part in ("..", "\\", "?", "#", "\x00")):
		return None
	if not frappe.db.exists("File", {"file_url": file_url, "is_private": 1}):
		return None
	root = os.path.realpath(frappe.get_site_path("private", "files"))
	path = os.path.realpath(os.path.join(root, file_url[len(PRIVATE_PREFIX) :]))
	if os.path.commonpath((root, path)) != root or not os.path.isfile(path):
		return None
	if os.path.getsize(path) > IMAGE_MAX_BYTES:
		return None
	with open(path, "rb") as handle:
		content = handle.read(IMAGE_MAX_BYTES + 1)
	if sniff(content) not in IMAGE_KINDS:
		return None
	try:
		data = render_jpeg(content, max_side, PRINT_QUALITY)
	except Exception:
		return None
	return "data:image/jpeg;base64," + base64.b64encode(data).decode()
