"""Mã lệnh cho nút, tab và trạm ở màn trạm, in thành tờ A4 dán tại trạm (A-119, FEAT-083, FR-M9-23).

Quét mã lệnh ở ô quét của màn trạm = bấm đúng nút đó: mã trạm ``TR-###`` (nút trạm), ``CMD-TAB-<khóa màn>`` (tab của trạm),
``CMD-DO-<LỆNH>`` (nút thao tác của màn hiện tại). Chỉ nút **điều hướng và hoàn thành** có mã; hủy, bỏ phiếu, từ chối,
xóa, ghi đè cơ số, thu hồi và nút cần PIN/lý do không bao giờ có mã lệnh (vẫn bấm tay hoặc đi đường có PIN).
Bảng `COMMANDS` là nguồn duy nhất: máy chủ dựng tờ in từ đây và trả cho màn trạm danh sách bộ chọn nút (`selectors`), nên
tờ in và hành vi quét không thể lệch nhau. Không ghi sổ nghiệp vụ nào ở đây: nút được bấm vốn đã tự kiểm quyền và ghi sổ.
"""

import base64
import re

import frappe
from frappe import _
from frappe.utils import escape_html

from tracecore.core import label_pdf, qr, zones

DO_PREFIX = "CMD-DO-"
TAB_PREFIX = "CMD-TAB-"
STATION_CODE = re.compile(r"^TR-\d{3}$")
TAB_KEY = re.compile(r"^[A-Z0-9_-]+$")
ALL = "*"
# `HOAN-THANH-NAP` có sẵn ở T2/T5 (A-96): giữ làm bí danh của lệnh hoàn thành nạp
ALIASES = {"HOAN-THANH-NAP": ("do", "COMPLETE-LOAD")}

# khóa lệnh -> nhãn (chuỗi gốc, dịch khi dựng), bộ chọn nút CSS (thử lần lượt), chức năng trạm áp dụng
COMMANDS = {
	"SUBMIT-RECEIPT": {
		"label": "Submit receipt",
		"selectors": ['[data-action="submit"]'],
		"functions": ("RECEIVE",),
	},
	"CONFIRM-SET": {
		"label": "Confirm set",
		"selectors": ['[data-action="confirm-set"]'],
		"functions": ("RECEIVE",),
	},
	"MODE-LOAD": {
		"label": "Load batch",
		"selectors": ['[data-action="t2-mode"][data-mode="load"]'],
		"functions": ("WASH_LOAD",),
	},
	"MODE-UNLOAD": {
		"label": "Unload batch",
		"selectors": ['[data-action="t2-mode"][data-mode="unload"]'],
		"functions": ("WASH_UNLOAD",),
	},
	"COMPLETE-LOAD": {
		"label": "Complete loading",
		"selectors": ['[data-action="t2-complete"]', '[data-action="t5-complete"]'],
		"functions": ("WASH_LOAD", "STERI_LOAD"),
	},
	"SAVE-DATA": {
		"label": "Confirm cycle data",
		"selectors": ['[data-action="t2-save-data"]', '[data-action="t5-save-data"]'],
		"functions": ("WASH_UNLOAD", "STERI_LOAD"),
	},
	"RECORD-RESULT": {
		"label": "Record cycle result",
		"selectors": ['[data-action="t2-record"]', '[data-action="t5b-record-result"]'],
		"functions": ("WASH_UNLOAD", "STERI_UNLOAD"),
	},
	"RECORD-COUNT": {
		"label": "Record the count",
		"selectors": ['[data-action="t3-submit"]'],
		"functions": ("ASSEMBLE",),
	},
	"CONFIRM-ALL": {
		"label": "Confirm all lines",
		"selectors": ['[data-action="confirm-all"]'],
		"functions": ("PACK",),
	},
	"CONFIRM-PACK": {
		"label": "Confirm pack",
		"selectors": ['[data-action="confirm-pack"]'],
		"functions": ("PACK",),
	},
	"PRINT-LABEL": {
		"label": "Print label",
		"selectors": ['[data-action="t2-label-pdf"]', '[data-action="t4-label-pdf"]'],
		"functions": ("WASH_LOAD", "PACK"),
	},
	"FINISH-CHECK": {
		"label": "Finish checking",
		"selectors": ['[data-action="t5b-finish"]'],
		"functions": ("STERI_UNLOAD",),
	},
	"RELEASE": {
		"label": "Release the load",
		"selectors": ['[data-action="t5b-release"]'],
		"functions": ("STERI_UNLOAD",),
	},
	"CONFIRM-USE": {
		"label": "Confirm use of this pack",
		"selectors": ['[data-action="confirm"]'],
		"functions": ("USE",),
	},
	"NEW-ISSUE": {
		"label": "New issue note",
		"selectors": ['[data-action="new-issue"]'],
		"functions": ("ISSUE",),
	},
	"PRINT-ISSUE": {
		"label": "Print issue note",
		"selectors": ['[data-action="print"]'],
		"functions": ("ISSUE",),
	},
	"MANUAL-PICK": {
		"label": "Choose by hand",
		"selectors": ['[data-action="manual-pick"]'],
		"functions": (ALL,),
	},
	"RESCAN-CARD": {
		"label": "Scan another card",
		"selectors": ['[data-action="rescan-card"]'],
		"functions": (ALL,),
	},
	"HELP": {
		"label": "Help",
		"selectors": ['[data-action="open-help"]'],
		"functions": (ALL,),
	},
}


def parse(raw):
	"""``("do", khóa)`` | ``("tab", khóa)`` | ``("station", mã trạm)`` của chuỗi quét, hoặc None khi không phải mã lệnh."""
	if not isinstance(raw, str):
		return None
	code = raw.strip().upper()
	if code in ALIASES:
		return ALIASES[code]
	if STATION_CODE.match(code):
		return ("station", code)
	if code.startswith(DO_PREFIX):
		key = code[len(DO_PREFIX) :]
		return ("do", key) if key in COMMANDS else None
	if code.startswith(TAB_PREFIX):
		key = code[len(TAB_PREFIX) :]
		return ("tab", key) if key and TAB_KEY.match(key) else None
	return None


def applies(command, functions):
	return ALL in command["functions"] or bool(set(command["functions"]) & set(functions))


def selectors_for(station):
	"""``{khóa lệnh: [bộ chọn nút]}`` của các lệnh áp dụng cho trạm `station` (màn trạm dùng để bấm đúng nút)."""
	functions = zones.station_functions(station)
	return {key: list(cmd["selectors"]) for key, cmd in COMMANDS.items() if applies(cmd, functions)}


# A-127: lệnh xác nhận/hoàn thành hiện QR ngay cạnh nút trên màn trạm; lệnh điều hướng khác chỉ có trên tờ A4
SCREEN_QR = (
	"SUBMIT-RECEIPT",
	"CONFIRM-SET",
	"COMPLETE-LOAD",
	"SAVE-DATA",
	"RECORD-RESULT",
	"RECORD-COUNT",
	"CONFIRM-ALL",
	"CONFIRM-PACK",
	"FINISH-CHECK",
	"RELEASE",
	"CONFIRM-USE",
)


# A-128: mã QR của mọi nút ở màn trạm (khớp `tcButtonCode` ở public/js/tc_scan_burst.js)
BUTTON_CODE = re.compile(r"^CMD-BTN-[A-Z0-9][A-Z0-9_-]{0,47}(?:\.[1-9][0-9]?)?$")
QR_BATCH_LIMIT = 80


def _png_uri(code):
	png = qr.qr_png(code, module_px=4, margin_px=12)
	return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def qr_images(codes):
	"""``{mã: ảnh QR PNG data URI}`` cho mã nút đúng dạng (A-128): ``CMD-DO-<lệnh có thật>`` hoặc ``CMD-BTN-…``.

	Mã sai dạng bị bỏ (không báo lỗi: màn trạm chỉ không hiện QR cho nút đó); tối đa ``QR_BATCH_LIMIT`` mã mỗi lần.
	"""
	images = {}
	for code in codes or []:
		if len(images) >= QR_BATCH_LIMIT:
			break
		if not isinstance(code, str) or code in images:
			continue
		valid = BUTTON_CODE.match(code) or (code.startswith(DO_PREFIX) and code[len(DO_PREFIX) :] in COMMANDS)
		if valid:
			images[code] = _png_uri(code)
	return images


def screen_qr(station):
	"""``{khóa lệnh: ảnh QR PNG data URI của "CMD-DO-<khóa>"}`` cho lệnh ``SCREEN_QR`` áp dụng cho trạm `station` (A-127)."""
	if not isinstance(station, str) or not frappe.db.exists("Zone Station", {"name": station, "is_zone": 0}):
		return {}
	functions = zones.station_functions(station)
	return {key: _png_uri(f"{DO_PREFIX}{key}") for key in SCREEN_QR if applies(COMMANDS[key], functions)}


def _stations():
	rows = frappe.get_all(
		"Zone Station",
		filters={"is_zone": 0, "is_active": 1},
		fields=["name", "zone_station_name", "station_no"],
		order_by="station_no asc, name asc",
	)
	return [row for row in rows if zones.station_screen_tabs(zones.station_functions(row.name))]


def for_station(station):
	"""``{"stations", "tabs", "actions"}``: mỗi mục ``{"code", "label"}`` của tờ mã lệnh trạm `station`."""
	if not isinstance(station, str) or not frappe.db.exists("Zone Station", {"name": station, "is_zone": 0}):
		return {"stations": [], "tabs": [], "actions": []}
	functions = zones.station_functions(station)
	stations = [
		{
			"code": row.name,
			"label": f"T{row.station_no} {_(row.zone_station_name)}"
			if row.station_no
			else _(row.zone_station_name),
		}
		for row in _stations()
	]
	tabs = [
		{"code": f"{TAB_PREFIX}{tab['key'].upper()}", "label": tab["label"]}
		for tab in zones.station_screen_tabs(functions)
	]
	actions = [
		{"code": f"{DO_PREFIX}{key}", "label": _(command["label"])}
		for key, command in COMMANDS.items()
		if applies(command, functions)
	]
	return {"stations": stations, "tabs": tabs, "actions": actions}


def _cell(row):
	image = base64.b64encode(qr.qr_png(row["code"])).decode("ascii")
	return (
		'<div class="cell">'
		f'<img src="data:image/png;base64,{image}" alt="{escape_html(row["code"])}">'
		f'<div class="name">{escape_html(row["label"])}</div>'
		f'<div class="code">{escape_html(row["code"])}</div>'
		"</div>"
	)


def sheet_html(station):
	sheet = for_station(station)
	name = frappe.db.get_value("Zone Station", station, "zone_station_name") or station
	headings = (
		("stations", _("Change station")),
		("tabs", _("Tabs of this station")),
		("actions", _("Actions")),
	)
	body = "".join(
		f"<h2>{escape_html(heading)}</h2><div class=\"grid\">{''.join(_cell(row) for row in sheet[key])}</div>"
		for key, heading in headings
		if sheet[key]
	)
	title = _("Command sheet: {0} ({1})").format(_(name), station)
	return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ font-family: Arial, "Segoe UI", sans-serif; color: #1a1a1a; }}
h1 {{ font-size: 16pt; margin: 0 0 4mm; }}
h2 {{ font-size: 12pt; margin: 6mm 0 2mm; border-bottom: 0.3mm solid #1a1a1a; }}
.grid {{ width: 100%; }}
.cell {{ display: inline-block; width: 31%; margin: 0 1% 4mm 0; vertical-align: top; text-align: center;
	page-break-inside: avoid; }}
.cell img {{ width: 30mm; height: 30mm; }}
.name {{ font-size: 10pt; font-weight: bold; }}
.code {{ font-family: "Courier New", monospace; font-size: 8pt; }}
</style></head><body><h1>{escape_html(title)}</h1>{body}</body></html>"""


def sheet_pdf(station):
	"""Bytes PDF A4 tờ mã lệnh của trạm `station` (A-119); lỗi công cụ PDF → `BlockedError(LABEL_PDF_FAILED)`."""
	from frappe.utils.pdf import get_pdf

	html = sheet_html(station)
	logged = len(frappe.local.message_log)
	try:
		return get_pdf(
			html,
			{
				"page-size": "A4",
				"margin-top": "12mm",
				"margin-bottom": "12mm",
				"margin-left": "12mm",
				"margin-right": "12mm",
			},
		)
	except label_pdf._FAILURES as error:
		del frappe.local.message_log[logged:]
		raise label_pdf._failed(station, error) from error
