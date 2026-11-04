"""Dữ liệu chu trình mặc định theo chương trình và chặn Đạt khi ngoài dải (A-89, #1815; D4), dùng chung T2 và T5.

Máy không đẩy dữ liệu thì form điền sẵn từ `Process Program`: `Program Parameter.default_value` nếu có, không thì nhiệt độ,
áp suất, thời lượng của chương trình theo tên tham số, chỉ khi giá trị nằm trong dải của tham số đó. Chương trình có nhiệt
độ/áp suất mà không có dòng tham số tương ứng thì thêm một ô tùy chọn. Server tự so giá trị lưu với mặc định để đánh dấu
trường đã sửa, không tin kiosk.
"""

import unicodedata

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, flt, get_datetime

from tracecore.core import audit
from tracecore.core.errors import Block, BlockedError

MANUAL = "Manual"
MANUAL_DEFAULT = "Manual Default"
ENDED_AT, STARTED_AT = "ended_at", "started_at"
PROGRAM, MIDPOINT = "program", "midpoint"  # nguồn giá trị điền sẵn (A-115)
# trường đầu chương trình -> từ khóa trong tên tham số (không dấu, xem `_folded`)
HEADER_FIELDS = (
	("temperature", ("nhiet do", "temperature")),
	("pressure", ("ap suat", "ap luc", "pressure")),
	("duration_min", ("thoi gian", "duration", "hold time")),
)
OWN_FIELDS = (("temperature", "Temperature", "°C"), ("pressure", "Pressure", "bar"))


def _folded(name):
	"""Tên tham số viết thường, bỏ dấu tiếng Việt, để so từ khóa."""
	decomposed = unicodedata.normalize("NFD", name.casefold().replace(chr(0x111), "d"))
	return "".join(char for char in decomposed if not unicodedata.combining(char))


def _number(value):
	try:
		return flt(str(value).strip().replace(",", "."), 6) if str(value or "").strip() else None
	except ValueError:
		return None


def _inside(value, low, high):
	low, high = flt(low), flt(high)
	return not ((low and value < low) or (high and value > high))


def _midpoint(low, high):
	"""Điểm giữa dải khi đủ hai cận khác 0 (A-115), không thì None."""
	low, high = flt(low), flt(high)
	return flt((low + high) / 2, 6) if low and high and low <= high else None


def _program(program):
	return (
		frappe.db.get_value(
			"Process Program", program, ["temperature", "pressure", "duration_min", "chemical"], as_dict=True
		)
		or frappe._dict()
	)


def _header_default(name, row, header):
	lowered = _folded(name)
	for field, words in HEADER_FIELDS:
		value = flt(header.get(field))
		if value and any(word in lowered for word in words):
			return value if _inside(value, row.min_value, row.max_value) else None
	return None


def parameter_schema(program):
	"""`param_schema` của chương trình kèm ``default_value`` đã tính (số hoặc None), thêm ô nhiệt độ/áp suất nếu thiếu dòng."""
	header = _program(program)
	rows = frappe.get_all(
		"Program Parameter",
		filters={"parent": program, "parenttype": "Process Program"},
		fields=["parameter_name", "unit", "min_value", "max_value", "required", "default_value"],
		order_by="idx asc",
	)
	covered = set()
	for row in rows:
		lowered = _folded(row.parameter_name)
		covered.update(field for field, words in HEADER_FIELDS if any(word in lowered for word in words))
		own = _number(row.default_value)
		value = own if own is not None else _header_default(row.parameter_name, row, header)
		row.default_source = PROGRAM if value is not None else None
		if value is None:  # A-115: không có mặc định thì lấy điểm giữa dải
			value = _midpoint(row.min_value, row.max_value)
			row.default_source = MIDPOINT if value is not None else None
		row.default_value = value
	for field, label, unit in OWN_FIELDS:
		value = flt(header.get(field))
		if value and field not in covered:
			rows.append(
				frappe._dict(
					parameter_name=_(label),
					unit=unit,
					min_value=0,
					max_value=0,
					required=0,
					default_value=value,
					default_source=PROGRAM,
				)
			)
	return rows


def defaults_of(doc):
	"""``{"values": {tên: số}, "started_at", "ended_at", "chemical", "chemical_name"}`` theo chương trình của lô/mẻ `doc`."""
	header = _program(doc.program)
	schema = [row for row in parameter_schema(doc.program) if row.default_value is not None]
	values = {row.parameter_name: row.default_value for row in schema}
	sources = {row.parameter_name: row.default_source for row in schema}
	started = doc.started_at or doc.load_completed_at
	ended = None
	if started and cint(header.get("duration_min")):
		ended = add_to_date(get_datetime(started), minutes=cint(header.duration_min))
	elif doc.get("unload_scan_at"):
		ended = doc.unload_scan_at
	return {
		"values": values,
		"sources": sources,
		STARTED_AT: str(started) if started else None,
		ENDED_AT: str(ended) if ended else None,
		"chemical": header.get("chemical"),
		"chemical_name": frappe.db.get_value("Item", header.chemical, "item_name")
		if header.get("chemical")
		else None,
	}


def prefill(doc):
	"""Giá trị điền sẵn của form, hoặc None khi đã có dữ liệu máy hay dữ liệu đã lưu (dữ liệu đó thắng)."""
	return None if doc.data_source else defaults_of(doc)


def _minute(value):
	return get_datetime(value).strftime("%Y-%m-%d %H:%M") if value else None


def trace(doc, parameters, started, ended):
	"""Đánh dấu từng dòng `parameters` (``default_value``, ``edited``); trả ``(nguồn dữ liệu, {"defaults", "edited_fields"})``."""
	defaults = defaults_of(doc)
	values = defaults["values"]
	edited, kept = [], []
	given = {row["parameter_name"] for row in parameters}
	for row in parameters:
		default = values.get(row["parameter_name"])
		row["default_value"] = default
		row["edited"] = default is not None and flt(row["value"], 6) != flt(default, 6)
		if row["edited"]:
			edited.append(row["parameter_name"])
		elif default is not None:
			kept.append(row["parameter_name"])  # A-115: giữ nguyên giá trị điền sẵn
	edited += [name for name in values if name not in given]  # đã xóa giá trị điền sẵn
	for field, actual in ((STARTED_AT, started), (ENDED_AT, ended)):
		if defaults[field]:
			(kept if _minute(defaults[field]) == _minute(actual) else edited).append(field)
	source = MANUAL_DEFAULT if values else MANUAL
	return source, {"defaults": defaults, "edited_fields": edited, "kept_fields": kept}


def audit_confirmation(ref_doctype, name, source, trace, station=None, client_ts=None):
	"""Ghi Audit Log trường đã sửa và trường giữ nguyên giá trị điền sẵn khi người vận hành xác nhận (A-115)."""
	if source != MANUAL_DEFAULT:
		return
	audit.log(
		"Update",
		ref_doctype,
		name,
		new={
			"event": "CycleDataConfirmed",
			"edited_fields": trace["edited_fields"],
			"kept_fields": trace["kept_fields"],
			"sources": trace["defaults"]["sources"],
		},
		reason="CycleDataConfirmed",
		station=station,
		client_ts=client_ts,
	)


def outside_names(rows):
	return [row.get("parameter_name") for row in rows or [] if row.get("outside_range")]


def check_inside_range(rows, label, name):
	"""Chặn kết luận Đạt khi có tham số ngoài dải của chương trình (A-89); Không đạt vẫn ghi được."""
	names = outside_names(rows)
	if names:
		raise BlockedError(
			Block(
				"CYCLE_DATA_OUT_OF_RANGE",
				_("A Pass cannot be recorded"),
				_("{0} {1} has values outside the program range: {2}.").format(label, name, ", ".join(names)),
				_("Correct the data if it was entered wrong; otherwise record Fail."),
				items=names,
			)
		)
