"""Pack Trace (SCR-14, FEAT-028, FR-M2-19): chuỗi sự kiện T1→T8 theo mã BN, Set ID, Cycle ID, mẻ, máy, người, ngày.

Mỗi dòng là một sự kiện; xuất PDF bằng nút in báo cáo chuẩn của Desk. Mã bệnh nhân chỉ ở dạng che.
"""

import frappe
from frappe import _

from tracecore.reprocessing import trace

CRITERIA = ("patient_code", "set_id", "cycle_id", "load", "equipment", "user", "from_date", "to_date")


# (fieldname, nhãn gốc, kiểu, rộng, options); nhãn dịch với ngữ cảnh "Pack Trace" để không đè bản dịch app khác
COLUMNS = (
	("cycle_id", "Cycle ID", "Link", 160, "Pack"),
	("set_id", "Set ID", "Link", 190, "Set Unit"),
	("label", "Station Step", "Data", 130, None),
	("at", "Time", "Datetime", 150, None),
	("user_name", "Person", "Data", 150, None),
	("station", "Station", "Link", 90, "Zone Station"),
	("equipment", "Equipment", "Link", 100, "Equipment"),
	("result", "Result", "Data", 80, None),
	("wash_indicator", "Wash Indicator", "Data", 320, None),
	("indicator_photo", "Indicator Photo", "Data", 180, None),
	("department", "Department", "Link", 150, "Department"),
	("patient_code_masked", "Patient Code (masked)", "Data", 130, None),
	("ref_doctype", "Document Type", "Link", 130, "DocType"),
	("ref_name", "Document", "Dynamic Link", 150, "ref_doctype"),
)


def _columns():
	return [
		{
			"fieldname": fieldname,
			"label": _(label, context="Pack Trace"),
			"fieldtype": fieldtype,
			"width": width,
			"options": options,
		}
		for fieldname, label, fieldtype, width, options in COLUMNS
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	criteria = {key: filters.get(key) for key in CRITERIA if filters.get(key)}
	if not criteria:
		return _columns(), [], _("Enter at least one search criterion.")
	result = trace.query(**criteria)
	rows = []
	for chain in result["chains"]:
		for event in chain["events"]:
			indicator = event.get("indicator")
			rows.append(
				{
					"cycle_id": chain["cycle_id"],
					"set_id": chain["set_id"],
					"label": event["label"],
					"at": event["at"],
					"user_name": event.get("user_name") or event.get("user"),
					"station": event.get("station"),
					"equipment": event.get("equipment"),
					"result": _(event["result"]) if event.get("result") else None,
					"wash_indicator": trace.wash_indicator_line(indicator),
					"indicator_photo": indicator["photo"] if indicator else None,
					"department": event.get("department"),
					"patient_code_masked": event.get("patient_code_masked"),
					"ref_doctype": event.get("ref_doctype"),
					"ref_name": event.get("ref_name"),
				}
			)
	return _columns(), rows, result["suggestion"]
