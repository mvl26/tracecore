"""In nhãn: render ZPL + ảnh xem trước, hàng đợi Print Job (core.print, ADR-006).

Skeleton chỉ có nhãn thử (GIAI test + chữ); Label Template/Printer đến FEAT-002.
"""

import io

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tracecore.core import gs1

LABEL_WIDTH_DOTS = 590  # 50 mm ở 300 dpi
LABEL_HEIGHT_DOTS = 354  # 30 mm ở 300 dpi
DM_ORIGIN = (30, 40)
TEXT_X = 240
TEXT_ROWS = (60, 130, 200)
ACK_STATUSES = ("Printed", "Failed")
OUTPUT_MODES = ("Printer", "File")


def _zpl_text(value):
	return value.replace("^", "").replace("~", "")


def _preview_png(payload, lines):
	from PIL import Image, ImageDraw, ImageFont

	canvas = Image.new("RGB", (LABEL_WIDTH_DOTS, LABEL_HEIGHT_DOTS), "white")
	symbol = Image.open(io.BytesIO(gs1.encode_datamatrix_png(payload, module_px=6, margin_px=12)))
	canvas.paste(symbol, DM_ORIGIN)
	draw = ImageDraw.Draw(canvas)
	font = ImageFont.load_default(size=26)
	for y, line in zip(TEXT_ROWS, lines, strict=False):
		draw.text((TEXT_X, y), line, fill="black", font=font)
	buffer = io.BytesIO()
	canvas.save(buffer, format="PNG")
	return buffer.getvalue()


def render_test_label(station):
	"""Nhãn thử 50×30 mm: DataMatrix GIAI test (không ghi Code Registry) + chữ ASCII."""
	giai = gs1.make_giai(gs1.configured_company_prefix(), "TEST" + now_datetime().strftime("%y%m%d%H%M%S"))
	hri = gs1.giai_hri(giai)
	payload = gs1.giai_payload(giai)
	lines = ["TraceCore TEST", hri, f"Station {station}"]
	parts = ["^XA", "^CI28", f"^PW{LABEL_WIDTH_DOTS}", f"^LL{LABEL_HEIGHT_DOTS}"]
	parts.append(gs1.zpl_datamatrix(payload, *DM_ORIGIN))
	parts += [f"^FO{TEXT_X},{y}^A0N,30,30^FD{_zpl_text(line)}^FS" for y, line in zip(TEXT_ROWS, lines, strict=False)]
	parts.append("^XZ")
	return {"giai": giai, "hri": hri, "zpl": "".join(parts), "preview_png": _preview_png(payload, lines)}


def create_job(station, zpl, data=None, template="test-label", printer=None):
	doc = frappe.get_doc(
		{
			"doctype": "Print Job",
			"station": station,
			"printer": printer,
			"template": template,
			"payload": zpl,
			"data": frappe.as_json(data) if data is not None else None,
			"status": "Queued",
			"attempts": 0,
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
