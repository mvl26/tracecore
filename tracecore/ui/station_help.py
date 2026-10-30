"""Hướng dẫn theo trạm (FEAT-013, FR-M9-15, A-56 D2, D4, D5): nội dung là Frappe `Help Article` có sẵn.

Bài gắn trạm qua Custom Field `tc_station_key` (bước trạm T1…T8, T5b, LIN, WST hoặc General). Bước = mục `<li>` của danh
sách đầu tiên trong `content`, ảnh = `<img>` đầu tiên của mục; kiosk chỉ nhận chữ thuần và đường dẫn ảnh công khai,
không nhận HTML của bài. R10 sửa chữ và tải ảnh thật trên Desk; `ensure_station_help` chỉ tạo bài còn thiếu.
"""

import re

import frappe
from bs4 import BeautifulSoup
from frappe import _

CATEGORY = "TraceCore Stations"
GENERAL = "General"
STATION_KEYS = ("T1", "T2", "T3", "T4", "T5", "T5b", "T6", "T7", "T8", "LIN", "WST", GENERAL)
MIN_STEPS, MAX_STEPS = 3, 5
# ảnh bước chỉ là file công khai của site: kiosk chưa quét thẻ vẫn xem được, không dẫn ra ngoài
_PUBLIC_FILE = re.compile(r"^/files/[^/?#\\]+$")

# Bài mặc định (chuỗi nguồn tiếng Anh, dịch ở vi.csv); ảnh do R10 bổ sung
DEFAULT_STEPS = {
	"T1": (
		"Scan your employee card to open the station.",
		"Scan the Set ID on each returned set.",
		"Check the receipt details and mark missing or damaged instruments.",
		"Confirm to send the set to washing.",
	),
	"T2": (
		"Scan your employee card to open the station.",
		"Choose the washer and the wash program, then scan the chemical lot.",
		"Scan each set into the wash batch and start the batch.",
		"When the cycle ends, record the result before unloading.",
	),
	"T3": (
		"Scan the Set ID of the washed set.",
		"Count each instrument against the checklist and its photo.",
		"Mark missing or damaged instruments.",
		"Confirm the assembly result.",
	),
	"T4": (
		"Scan the Set ID of the assembled set.",
		"Check that every gate shows Pass.",
		"Print the pack label and stick it on the pack.",
		"Confirm to finish packing.",
	),
	"T5": (
		"Scan the sterilizer and choose the program.",
		"Scan each pack into the load.",
		"Start the load and keep the indicators with it.",
	),
	"T5b": (
		"Scan the finished load.",
		"Record the result of every indicator.",
		"Ask R02 to release the load with a PIN.",
	),
	"T6": (
		"Scan the pack from the released load.",
		"Scan the shelf location.",
		"Confirm to put the pack away.",
	),
	"T7": (
		"Choose the department request to fill.",
		"Scan each pack you hand over.",
		"Confirm and print the issue note.",
	),
	"T8": (
		"Scan the Cycle ID on the pack before use.",
		"Enter the patient code and the surgery code.",
		"Confirm the use of the pack.",
	),
	"LIN": (
		"Choose Collect or Laundry at the top of the screen.",
		"Weigh the linen and choose the linen type.",
		"Check the quantity and confirm.",
	),
	"WST": (
		"Scan the card of the person handing over the waste.",
		"Choose the waste type, then enter the number of bags and the weight.",
		"Confirm, then scan the card again to acknowledge the receipt.",
	),
	GENERAL: (
		"Scan your employee card to open the station.",
		"Scan the code in the box at the top of the screen.",
		"Read the result: a red message means stop and follow the action shown.",
		"Press Help and then Report a problem if the screen does not work as expected.",
	),
}


def _clean(text):
	return re.sub(r"\s+", " ", text or "").strip()


def _image(item):
	img = item.find("img")
	src = (img.get("src") or "").strip() if img else ""
	return src if _PUBLIC_FILE.match(src) and ".." not in src else None


def steps_from_html(html):
	"""Mục của danh sách `<ol>/<ul>` đầu tiên → ``[{"text", "image"}]``; chữ thuần, ảnh công khai hoặc None."""
	if not html:
		return []
	first = BeautifulSoup(html, "html.parser").find(["ol", "ul"])
	if not first:
		return []
	steps = []
	for item in first.find_all("li", recursive=False):
		steps.append({"text": _clean(item.get_text(" ")), "image": _image(item)})
	return steps


def validate_article(doc, method=None):
	"""Hook `validate` của Help Article: bài gắn trạm có 3 đến 5 bước và ảnh chỉ là file công khai `/files/…`."""
	if not doc.get("tc_station_key"):
		return
	soup = BeautifulSoup(doc.content or "", "html.parser")
	first = soup.find(["ol", "ul"])
	items = first.find_all("li", recursive=False) if first else []
	if not MIN_STEPS <= len(items) <= MAX_STEPS:
		frappe.throw(
			_("A station guide needs {0} to {1} numbered steps; this one has {2}.").format(
				MIN_STEPS, MAX_STEPS, len(items)
			)
		)
	for item in items:
		for img in item.find_all("img"):
			src = (img.get("src") or "").strip()
			if not _PUBLIC_FILE.match(src) or ".." in src:
				frappe.throw(_("Step images must be public files uploaded to this site (/files/…)."))


def station_key(station):
	step = frappe.db.get_value("Zone Station", station, "station_step") if station else None
	return step if step in STATION_KEYS else GENERAL


def article_for_key(key):
	row = frappe.db.get_value(
		"Help Article",
		{"tc_station_key": key, "published": 1},
		["name", "title", "content", "modified"],
		as_dict=True,
		order_by="modified desc",
	)
	if not row:
		return None
	return {
		"name": row.name,
		"key": key,
		"title": row.title,
		"steps": steps_from_html(row.content),
		"modified": str(row.modified),
	}


def article_for(station):
	"""Bài của bước trạm, không có thì bài General, không có nữa thì None."""
	key = station_key(station)
	return article_for_key(key) or (article_for_key(GENERAL) if key != GENERAL else None)


def ensure_category():
	if not frappe.db.exists("Help Category", CATEGORY):
		frappe.get_doc(
			{
				"doctype": "Help Category",
				"category_name": CATEGORY,
				"category_description": _("Step-by-step guides shown on TraceCore stations."),
			}
		).insert(ignore_permissions=True)
	return CATEGORY


def ensure_station_help():
	"""`after_migrate`: tạo bài mặc định cho khóa trạm còn thiếu; không ghi đè bài R10 đã sửa."""
	if not frappe.get_meta("Help Article").has_field("tc_station_key"):
		return
	category = ensure_category()
	for key in STATION_KEYS:
		if frappe.db.exists("Help Article", {"tc_station_key": key}):
			continue
		label = _("All stations") if key == GENERAL else key
		frappe.get_doc(
			{
				"doctype": "Help Article",
				"title": _("Station guide: {0}").format(label),
				"category": category,
				"published": 1,
				"tc_station_key": key,
				"content": "<ol>"
				+ "".join(f"<li>{frappe.utils.escape_html(_(step))}</li>" for step in DEFAULT_STEPS[key])
				+ "</ol>",
			}
		).insert(ignore_permissions=True)
