"""In nhãn: dialect máy in, render mẫu nhãn, chọn máy in theo loại nhãn, đổi cuộn, hàng đợi Print Job (core.print, ADR-006).

- **Dialect** (D7): mỗi ngôn ngữ máy in là một lớp trong `DIALECTS` (hiện chỉ ZPL). Thêm TSPL (máy TSC) = thêm một
  lớp + option `language` của Printer/Label Template, không đổi dữ liệu hay nơi gọi.
- **Render**: mẫu Jinja do R10 sửa (Label Template) chạy trong sandbox riêng, không có API `frappe`; mọi chuỗi đưa
  vào đã bỏ ký tự điều khiển của dialect; chữ in qua `text()` giữ dấu hoặc bỏ dấu theo `Printer.supports_unicode`.
- **Nhãn đối tượng** (FEAT-005, A-05 R2): `render_object` in nhãn QR mã trần cho thiết bị, trạm, cuộn nhãn, thẻ
  nhân viên, kệ bằng mẫu active của loại đối tượng (`OBJECT_LABELS`); QR qua hàm `qr()` của dialect.
- **Chọn máy in** (BRU-REP-011): theo trạm và phương pháp của cuộn nhãn đang lắp (`Printer.label_type_loaded`).
- **Đổi cuộn** (`set_roll`): cập nhật loại nhãn đang lắp và đưa các Print Job `Waiting` khớp phương pháp vào hàng đợi.
"""

import io
import unicodedata

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime
from jinja2 import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

from tracecore.core import code_registry, gs1, qr
from tracecore.core.errors import Block, BlockedError

LABEL_WIDTH_DOTS = 590  # 50 mm ở 300 dpi
LABEL_HEIGHT_DOTS = 354  # 30 mm ở 300 dpi
DM_ORIGIN = (30, 40)
ACK_STATUSES = ("Printed", "Failed")
OUTPUT_MODES = ("Printer", "File")
NEW_JOB_STATUSES = ("Queued", "Waiting")

MM_PER_INCH = 25.4
DEFAULT_DPI = 300
DEFAULT_WIDTH_MM = 60
DEFAULT_HEIGHT_MM = 40
DEFAULT_LANGUAGE = "ZPL"
# Đối tượng có nhãn QR mã trần (A-05 R2); nhãn gói ("Pack") đi đường `render_pack`
OBJECT_LABELS = ("Equipment", "Station", "Roll", "Employee Card", "Location")
# Loại mã (`gs1.parse_scan`) in được cho từng đối tượng; thẻ nhân viên còn nhận thẻ có sẵn đã đăng ký (sổ CARD)
OBJECT_SCAN_TYPES = dict(
	zip(OBJECT_LABELS, ("equipment", "station", "roll", "employee", "location"), strict=True)
)
OBJECT_CODE_MAX_LENGTH = 40


# ---------------------------------------------------------------------------------------------------------
# Dialect máy in
# ---------------------------------------------------------------------------------------------------------


class Dialect:
	"""Một ngôn ngữ máy in: sinh DataMatrix, bỏ ký tự điều khiển trong dữ liệu, kiểm đầu ra."""

	name = ""

	def datamatrix(self, payload, x, y, module=6):
		raise NotImplementedError

	def qr(self, payload, x, y, magnification=6):
		raise NotImplementedError

	def sanitize(self, text):
		raise NotImplementedError

	def problem(self, output):
		"""Lý do `output` không phải lệnh hợp lệ của dialect (đã qua `_()`), hoặc None nếu hợp lệ."""
		raise NotImplementedError

	def validate(self, output):
		reason = self.problem(output)
		if reason:
			frappe.throw(reason)


class ZplDialect(Dialect):
	name = "ZPL"
	# ^ và ~ mở lệnh ZPL; CR/LF/Tab đổi thành dấu cách để một chuỗi không tách thành nhiều dòng lệnh
	_STRIP = str.maketrans({"^": None, "~": None, "\r": " ", "\n": " ", "\t": " "})

	def datamatrix(self, payload, x, y, module=6):
		if not payload:
			frappe.throw(_("The label has no DataMatrix payload."))
		try:
			return gs1.zpl_datamatrix(payload, x, y, module)
		except gs1.GS1Error as error:
			frappe.throw(_("The label data cannot be encoded as DataMatrix: {0}").format(error))

	def qr(self, payload, x, y, magnification=6):
		try:
			return qr.zpl_qr(payload, x, y, magnification)
		except qr.QRError as error:
			frappe.throw(_("The label data cannot be encoded as QR: {0}").format(error))

	def sanitize(self, text):
		return ("" if text is None else str(text)).translate(self._STRIP)

	def problem(self, output):
		output = output.strip()
		if not (output.startswith("^XA") and output.endswith("^XZ")):
			return _("The rendered label is not valid {0}: it must start with ^XA and end with ^XZ.").format(
				self.name
			)
		return None


DIALECTS: dict[str, Dialect] = {dialect.name: dialect for dialect in (ZplDialect(),)}


def get_dialect(language):
	dialect = DIALECTS.get(language)
	if dialect is None:
		frappe.throw(_("Printer language {0} is not supported.").format(language))
	return dialect


# đ (U+0111) và Đ (U+0110) không phân rã khi NFKD; viết bằng mã điểm để không có chữ Việt ngoài _() (lint R3)
_FOLD_MAP = str.maketrans({0x0111: "d", 0x0110: "D"})


def fold(text):
	"""Bỏ dấu tiếng Việt cho máy in không hỗ trợ Unicode: NFKD bỏ dấu, đ/Đ → d/D, bỏ ký tự ngoài ASCII in được."""
	decomposed = unicodedata.normalize("NFKD", "" if text is None else str(text)).translate(_FOLD_MAP)
	return "".join(char for char in decomposed if " " <= char <= "~")


def mm_to_dots(mm, dpi):
	"""Milimét → dot ở độ phân giải `dpi` (làm tròn): 60 mm ở 300 dpi = 709 dot."""
	return int(flt(mm) * cint(dpi) / MM_PER_INCH + 0.5)


# ---------------------------------------------------------------------------------------------------------
# Render mẫu nhãn
# ---------------------------------------------------------------------------------------------------------

# Môi trường Jinja riêng thay cho jenv của Frappe: mẫu do R10 sửa không được gọi API `frappe` (DB, request…),
# và biến thiếu phải ra chuỗi rỗng chứ không in "{{ no such element }}" (DebugUndefined của Frappe) vào ZPL.
_JINJA = SandboxedEnvironment(autoescape=False)


class _Doc(dict):
	"""`doc` của mẫu: khóa thiếu trả chuỗi rỗng để nhãn không in "None"/lỗi."""

	def __missing__(self, key):
		return ""


def _clean(value, dialect):
	"""Bỏ ký tự điều khiển của dialect trong mọi chuỗi (kể cả lồng nhau); None → chuỗi rỗng."""
	if value is None:
		return ""
	if isinstance(value, str):
		return dialect.sanitize(value)
	if isinstance(value, dict):
		return _Doc({key: _clean(item, dialect) for key, item in value.items()})
	if isinstance(value, list | tuple):
		return [_clean(item, dialect) for item in value]
	return value


def check_template_syntax(body):
	"""Mẫu Jinja phải biên dịch được; lỗi cú pháp → ValidationError."""
	try:
		_JINJA.parse(body or "")
	except TemplateSyntaxError as error:
		frappe.throw(
			_("The template body has a syntax error on line {0}: {1}").format(error.lineno, error.message)
		)


def _render_failed(name, reason, cause=None):
	"""Ném ValidationError nói mẫu nào không dựng được và vì sao; `cause` (lỗi gốc) giữ làm __cause__."""
	if name:
		message = _("Label template {0} could not be rendered: {1}").format(name, reason)
	else:
		message = _("The label template could not be rendered: {0}").format(reason)
	try:
		frappe.throw(message)
	except frappe.ValidationError as error:
		raise error from cause


def render(
	template,
	doc,
	unicode=False,
	*,
	dpi=DEFAULT_DPI,
	width_mm=DEFAULT_WIDTH_MM,
	height_mm=DEFAULT_HEIGHT_MM,
	language=DEFAULT_LANGUAGE,
	name=None,
):
	"""Render mẫu `template` (Jinja) với `doc` thành lệnh máy in của `language`.

	Ngữ cảnh mẫu: ``doc`` (mọi chuỗi đã `sanitize`), ``text(giá trị)`` (giữ dấu nếu `unicode`, ngược lại `fold`),
	``datamatrix(payload, x, y, module)`` và ``qr(payload, x, y, magnification)`` của dialect, ``dpi``,
	``width_dots``, ``height_dots`` (từ mm và dpi).
	Kết quả là một dòng (bỏ xuống dòng giữa các lệnh) và phải hợp lệ theo `Dialect.problem`.

	Mọi lỗi đều là ValidationError (không bao giờ lỗi thô của Jinja/Python): lỗi lúc chạy mẫu (chia cho 0, cộng
	chuỗi với số, thiếu thuộc tính…) và đầu ra sai khung được bọc kèm tên mẫu `name` và lý do, lỗi gốc là __cause__;
	ValidationError sẵn có (dữ liệu DataMatrix sai…) giữ nguyên.
	"""
	dialect = get_dialect(language)

	def text(value=None):
		clean = dialect.sanitize(value)
		return unicodedata.normalize("NFC", clean) if unicode else fold(clean)

	context = {
		"doc": _clean(doc or {}, dialect),
		"text": text,
		"datamatrix": dialect.datamatrix,
		"qr": dialect.qr,
		"dpi": cint(dpi),
		"width_dots": mm_to_dots(width_mm, dpi),
		"height_dots": mm_to_dots(height_mm, dpi),
	}
	try:
		rendered = _JINJA.from_string(template or "").render(context)
	except frappe.ValidationError:
		raise
	except Exception as error:
		_render_failed(name, f"{type(error).__name__}: {error}", cause=error)
	output = "".join(line.strip() for line in rendered.splitlines())
	reason = dialect.problem(output)
	if reason:
		_render_failed(name, reason)
	return output


# ---------------------------------------------------------------------------------------------------------
# Mẫu nhãn và chọn máy in
# ---------------------------------------------------------------------------------------------------------

TEMPLATE_FIELDS = ["name", "label_object", "body", "width_mm", "height_mm", "dpi", "language"]
PRINTER_FIELDS = ["name", "host", "port", "language", "supports_unicode", "label_type_loaded"]


def method_filter(method):
	"""Bộ lọc cột `method`: nhãn đối tượng không có phương pháp (NULL hoặc chuỗi rỗng)."""
	return method if method else ["is", "not set"]


def active_template(label_object, method, language=DEFAULT_LANGUAGE):
	"""Label Template active của (đối tượng, phương pháp, ngôn ngữ) hoặc None; nhãn đối tượng: `method` = None."""
	return (
		frappe.db.get_value(
			"Label Template",
			{
				"label_object": label_object,
				"method": method_filter(method),
				"language": language,
				"is_active": 1,
			},
			TEMPLATE_FIELDS,
			as_dict=True,
		)
		or None
	)


def pack_template(method, language=DEFAULT_LANGUAGE):
	"""Nội dung mẫu nhãn gói active theo phương pháp, hoặc None nếu chưa có mẫu."""
	template = active_template("Pack", method, language)
	return template.body if template else None


def _render_template_row(template, doc, unicode):
	return render(
		template.body,
		doc,
		unicode,
		dpi=template.dpi,
		width_mm=template.width_mm,
		height_mm=template.height_mm,
		language=template.language,
		name=template.name,
	)


def render_pack(method, doc, language=DEFAULT_LANGUAGE, unicode=False):
	"""Render nhãn gói bằng mẫu active (kích thước và dpi lấy từ chính mẫu); chưa có mẫu → None."""
	template = active_template("Pack", method, language)
	return _render_template_row(template, doc, unicode) if template else None


def _check_object_label(label_object):
	if label_object not in OBJECT_LABELS:
		frappe.throw(_("Label object {0} has no QR label.").format(label_object))


def object_code_problem(label_object, code):
	"""Lý do (đã dịch) `code` không in được thành nhãn QR của `label_object`, hoặc None nếu in được.

	Mã đi nguyên vào QR nên phải là ASCII in được, 1-40 ký tự, không khoảng trắng, không ``^``/``~``, và đúng định
	dạng của loại đối tượng (thiết bị ``TB-``, trạm ``TR-``…; thẻ nhân viên ``NV-`` hoặc thẻ bệnh viện đã đăng ký) để
	mã của loại này không bị in thành nhãn loại khác. Mã sai bị từ chối thay vì lặng lẽ sửa.
	"""
	_check_object_label(label_object)
	if (
		not isinstance(code, str)
		or not 0 < len(code) <= OBJECT_CODE_MAX_LENGTH
		or not all("!" <= char <= "}" and char != "^" for char in code)
	):
		return _("Code {0} cannot be printed on a QR label.").format(repr(code))
	scanned = gs1.parse_scan(code)
	if scanned["raw"] == code and scanned["type"] == OBJECT_SCAN_TYPES[label_object]:
		return None
	card = {"name": code, "prefix": code_registry.CARD_PREFIX}
	if label_object == "Employee Card" and frappe.db.exists("Code Registry", card):
		return None
	return _("Code {0} is not a code of {1}.").format(code, _(label_object, context="Label Template"))


def object_context(label_object, code, title, subtitle=""):
	"""`doc` của mẫu nhãn QR đối tượng (``code, title, subtitle, payload, is_test``); mã qua `object_code_problem`."""
	problem = object_code_problem(label_object, code)
	if problem:
		frappe.throw(problem)
	return {
		"code": code,
		"title": "" if title is None else str(title),
		"subtitle": "" if subtitle is None else str(subtitle),
		"payload": code,
		"is_test": False,
	}


def render_object(label_object, code, title, subtitle="", printer=None, with_template=False):
	"""Render nhãn QR của một đối tượng bằng mẫu active của `label_object` theo ngôn ngữ máy in.

	`printer` (dict như `select_printer`, hoặc None) cho ``language`` (mặc định ZPL) và ``supports_unicode``
	(không có → bỏ dấu). Chưa có mẫu active → ValidationError đã dịch; mẫu lỗi → ValidationError nêu tên mẫu.
	`with_template` → trả ``(zpl, dòng mẫu đã dùng)`` để người gọi ghi Print Job mà không tra lại mẫu.
	"""
	doc = object_context(label_object, code, title, subtitle)
	printer = printer or {}
	language = printer.get("language") or DEFAULT_LANGUAGE
	get_dialect(language)
	template = active_template(label_object, None, language)
	if template is None:
		label = _(label_object, context="Label Template")
		frappe.throw(_("No active label template for {0} ({1}).").format(label, language))
	zpl = _render_template_row(template, doc, bool(cint(printer.get("supports_unicode"))))
	return (zpl, template) if with_template else zpl


def _active_printers(station):
	"""Máy in active của trạm theo tên Printer, kèm `method` của loại nhãn đang lắp."""
	printers = frappe.get_all(
		"Printer", filters={"station": station, "is_active": 1}, fields=PRINTER_FIELDS, order_by="name asc"
	)
	label_types = {printer.label_type_loaded for printer in printers if printer.label_type_loaded}
	methods = (
		dict(
			frappe.get_all(
				"Item",
				filters={"name": ["in", list(label_types)]},
				fields=["name", "tc_compatible_method"],
				as_list=True,
			)
		)
		if label_types
		else {}
	)
	for printer in printers:
		printer["method"] = methods.get(printer.label_type_loaded)
	return printers


def select_printer(station, method):
	"""Máy in active của trạm đang lắp nhãn đúng `method` (BRU-REP-011); nhiều máy → theo tên Printer.

	Trả `{"name", "host", "port", "language", "supports_unicode", "label_type"}` hoặc None.
	"""
	for printer in _active_printers(station):
		if printer.method == method:
			return {
				"name": printer.name,
				"host": printer.host or "",
				"port": cint(printer.port),
				"language": printer.language,
				"supports_unicode": cint(printer.supports_unicode),
				"label_type": printer.label_type_loaded,
			}
	return None


def station_printers(station):
	"""Máy in active của trạm cho cấu hình Station Agent: `name, host, port, language, label_type, method`."""
	return [
		{
			"name": printer.name,
			"host": printer.host or "",
			"port": cint(printer.port),
			"language": printer.language,
			"label_type": printer.label_type_loaded,
			"method": printer.method,
		}
		for printer in _active_printers(station)
	]


# ---------------------------------------------------------------------------------------------------------
# Đổi cuộn nhãn
# ---------------------------------------------------------------------------------------------------------


def _roll_not_found(roll_code):
	return BlockedError(
		Block(
			"ROLL_NOT_FOUND",
			_("Label roll not found"),
			_("Roll code {0} has not been issued or has been disabled.").format(roll_code),
			_("Rescan the code on the label roll or call R02."),
		)
	)


def _roll_not_label(roll_code):
	return BlockedError(
		Block(
			"ROLL_NOT_LABEL",
			_("Not a label roll"),
			_("Roll code {0} does not belong to a label item with a compatible method.").format(roll_code),
			_("Scan the code on a label roll or call R02."),
		)
	)


def _roll_label(roll_code):
	"""(Item nhãn, phương pháp) của cuộn; mã chưa cấp/đã vô hiệu → ROLL_NOT_FOUND; không phải nhãn → ROLL_NOT_LABEL."""
	if not roll_code or frappe.db.get_value("Code Registry", roll_code, "status") != "Active":
		raise _roll_not_found(roll_code)
	item = code_registry.roll_label_item(roll_code)
	group, method = (
		frappe.db.get_value("Item", item, ["tc_item_group_cssd", "tc_compatible_method"]) if item else None
	) or (None, None)
	if group != "Label" or not method:
		raise _roll_not_label(roll_code)
	return item, method


def _job_data(job):
	# cột `data` là JSON hợp lệ (MariaDB kiểm), nhưng không chắc là object
	data = frappe.parse_json(job.data) if job.data else {}
	return data if isinstance(data, dict) else {}


def _job_render_error(template, error):
	"""Lý do (đã dịch) một job không dựng được nhãn, luôn có tên mẫu."""
	text = str(error)
	if template.name in text:
		return text
	return _("Label template {0} could not be rendered: {1}").format(template.name, text)


def _release_waiting_jobs(printer, method):
	"""Render các Print Job `Waiting` cùng trạm khớp `method` bằng mẫu active + cờ Unicode của máy in, chuyển Queued.

	Trả ``(released, failed)``. Job nào render lỗi (ValidationError) thì giữ ``Waiting``, ghi `error` và Error Log,
	rồi làm tiếp các job khác: một nhãn lỗi không được hoàn tác việc đổi cuộn (FR-M2-08.8, BRU-REP-011).
	"""
	template = active_template("Pack", method, printer.language)
	if template is None:
		return [], []
	names = frappe.get_all(
		"Print Job",
		filters={"station": printer.station, "status": "Waiting"},
		pluck="name",
		order_by="creation asc, name asc",
	)
	released, failed = [], []
	for name in names:
		job = frappe.get_doc("Print Job", name, for_update=True)
		data = _job_data(job)
		if job.status != "Waiting" or data.get("method") != method or data.get("label_object") != "Pack":
			continue
		logged = len(frappe.local.message_log)
		try:
			zpl = _render_template_row(template, data.get("label_context"), bool(printer.supports_unicode))
		except frappe.ValidationError as error:
			del frappe.local.message_log[logged:]  # lỗi đi vào failed_jobs, không để msgprint lên kiosk
			reason = _job_render_error(template, error)
			job.update({"error": reason})
			job.save(ignore_permissions=True)
			frappe.log_error(title=_("Waiting label could not be rendered"), message=f"{job.name}: {reason}")
			failed.append({"print_job": str(job.name), "error": reason})
			continue
		job.update({"payload": zpl, "printer": printer.name, "template": template.name, "status": "Queued"})
		job.save(ignore_permissions=True)
		released.append({"print_job": str(job.name), "zpl": zpl, "printer": printer.name})
	return released, failed


def _count_waiting_jobs(station, method):
	"""Số Print Job `Waiting` của trạm chờ đúng loại nhãn `method` (nhãn gói)."""
	count = 0
	for name in frappe.get_all("Print Job", filters={"station": station, "status": "Waiting"}, pluck="name"):
		data = _job_data(frappe.get_doc("Print Job", name))
		if data.get("method") == method and data.get("label_object") == "Pack":
			count += 1
	return count


def set_roll(printer, roll_code, release=True):
	"""Đổi cuộn nhãn của máy in (FR-M2-08.2, AC-9) và phát hành các Print Job đang chờ đúng loại nhãn.

	Loại nhãn đang lắp = Item nhãn của cuộn. Mã chưa cấp/đã vô hiệu → `BlockedError(ROLL_NOT_FOUND)`; mã của Item
	không phải nhãn → `ROLL_NOT_LABEL`. Trả `{"printer", "label_type", "method", "released_jobs": [{"print_job",
	"zpl", "printer"}], "failed_jobs": [{"print_job", "error"}]}`; job `Waiting` khác phương pháp hoặc khác trạm giữ
	nguyên. Job render lỗi nằm trong `failed_jobs` và vẫn `Waiting`; việc đổi cuộn luôn được ghi nhận.

	Máy in không active vẫn ghi nhận đổi cuộn (có Audit Log) nhưng KHÔNG phát hành job: agent chỉ in tới máy in
	có trong `station_printers` (active), job đã `Queued` cho máy in ngoài danh sách sẽ bị từ chối và không bao giờ
	quay lại `Waiting`. `released_jobs` là `[]`; job còn `Waiting` chờ máy in active đổi cuộn đúng loại nhãn.

	``release=False`` (đường Desk, ruling F2): ghi nhận cuộn nhưng KHÔNG phát hành job, vì chỉ kiosk gửi được
	`released_jobs` tới Station Agent; job khớp giữ `Waiting` tới khi cuộn được quét ở màn T4. `jobs_waiting` luôn là
	số job `Waiting` của trạm khớp loại nhãn còn lại sau lần đổi cuộn.
	"""
	doc = frappe.get_doc("Printer", printer, for_update=True)
	item, method = _roll_label(roll_code)
	doc.update(
		{
			"label_type_loaded": item,
			"roll_code": roll_code,
			"roll_loaded_on": now_datetime(),
			"roll_loaded_by": frappe.session.user,
		}
	)
	doc.flags.tc_roll_change = True
	doc.save(ignore_permissions=True)
	released, failed = _release_waiting_jobs(doc, method) if release and doc.is_active else ([], [])
	return {
		"printer": doc.name,
		"label_type": item,
		"method": method,
		"released_jobs": released,
		"failed_jobs": failed,
		"jobs_waiting": _count_waiting_jobs(doc.station, method),
	}


# ---------------------------------------------------------------------------------------------------------
# Nhãn thử và hàng đợi Print Job
# ---------------------------------------------------------------------------------------------------------


def label_layout(giai, station):
	"""Các dòng chữ của nhãn thử: (x, y, cỡ chữ theo dot, nội dung ASCII).

	Cột phải cạnh DataMatrix cho tiêu đề/trạm; chuỗi người đọc (8004)… chạy hết bề ngang ở đáy nhãn.
	"""
	return [
		(200, 50, 34, "TraceCore TEST"),
		(200, 110, 28, f"Station {station}"),
		(30, 290, 24, gs1.giai_hri(giai)),
	]


def _preview_png(payload, layout):
	from PIL import Image, ImageDraw, ImageFont

	canvas = Image.new("RGB", (LABEL_WIDTH_DOTS, LABEL_HEIGHT_DOTS), "white")
	symbol = Image.open(io.BytesIO(gs1.encode_datamatrix_png(payload, module_px=6, margin_px=12)))
	canvas.paste(symbol, DM_ORIGIN)
	draw = ImageDraw.Draw(canvas)
	for x, y, size, text in layout:
		draw.text((x, y), text, fill="black", font=ImageFont.load_default(size=size))
	buffer = io.BytesIO()
	canvas.save(buffer, format="PNG")
	return buffer.getvalue()


def render_test_label(station):
	"""Nhãn thử 50x30 mm: DataMatrix GIAI test (không ghi Code Registry) + chữ ASCII."""
	zpl_dialect = DIALECTS[DEFAULT_LANGUAGE]
	giai = gs1.make_giai(gs1.configured_company_prefix(), "TEST" + now_datetime().strftime("%y%m%d%H%M%S"))
	payload = gs1.giai_payload(giai)
	layout = label_layout(giai, station)
	parts = ["^XA", "^CI28", f"^PW{LABEL_WIDTH_DOTS}", f"^LL{LABEL_HEIGHT_DOTS}"]
	parts.append(zpl_dialect.datamatrix(payload, *DM_ORIGIN))
	parts += [
		f"^FO{x},{y}^A0N,{size},{size}^FD{zpl_dialect.sanitize(text)}^FS" for x, y, size, text in layout
	]
	parts.append("^XZ")
	return {
		"giai": giai,
		"hri": gs1.giai_hri(giai),
		"zpl": "".join(parts),
		"preview_png": _preview_png(payload, layout),
	}


def create_job(
	station,
	zpl,
	data=None,
	template="test-label",
	printer=None,
	status="Queued",
	ref_doctype=None,
	ref_name=None,
	reprint_reason=None,
):
	"""Tạo Print Job: `Queued` (có `zpl`) hoặc `Waiting` (chưa có máy in đúng loại nhãn, `zpl` = None).

	Job `Waiting` mang `data = {"method", "label_object", "label_context"}` để `set_roll` render khi có máy in.
	Trả tên job (chuỗi).
	"""
	if status not in NEW_JOB_STATUSES:
		frappe.throw(_("Invalid print status: {0}").format(status))
	doc = frappe.get_doc(
		{
			"doctype": "Print Job",
			"station": station,
			"printer": printer,
			"template": template,
			"payload": zpl,
			"data": frappe.as_json(data) if data is not None else None,
			"status": status,
			"attempts": 0,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"reprint_reason": reprint_reason,
		}
	).insert(ignore_permissions=True)
	return str(doc.name)


def ack(job, status, output_mode, output_ref=None, error=None):
	"""Agent báo kết quả một lệnh in (Printed/Failed) và nơi xuất (Printer/File)."""
	if status not in ACK_STATUSES:
		frappe.throw(_("Invalid print status: {0}").format(status))
	if output_mode not in OUTPUT_MODES:
		frappe.throw(_("Invalid print output mode: {0}").format(output_mode))
	doc = frappe.get_doc("Print Job", job)
	doc.update(
		{
			"status": status,
			"output_mode": output_mode,
			"output_ref": output_ref,
			"error": error,
			"attempts": cint(doc.attempts) + 1,
			"printed_at": now_datetime() if status == "Printed" else None,
		}
	)
	doc.save(ignore_permissions=True)
	return {"ok": True, "status": doc.status}
