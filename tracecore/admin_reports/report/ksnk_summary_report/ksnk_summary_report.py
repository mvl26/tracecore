"""Báo cáo KSNK tổng hợp theo kỳ (FEAT-007, FR-M9-02, A-57 Q2): mỗi chỉ tiêu một dòng.

Dữ liệu ở `admin_reports.sterilization_log.ksnk_summary`; bản in PDF theo mẫu qua nút Xuất PDF (job nền).
"""

from frappe import _

from tracecore.admin_reports import sterilization_log


def _columns():
	return [
		{"fieldname": "section", "label": _("Section"), "fieldtype": "Data", "width": 200},
		{"fieldname": "item", "label": _("Item"), "fieldtype": "Data", "width": 220},
		{"fieldname": "value", "label": _("Count"), "fieldtype": "Int", "width": 90},
		{"fieldname": "detail", "label": _("Detail"), "fieldtype": "Data", "width": 260},
	]


def execute(filters=None):
	s = sterilization_log.ksnk_summary(filters)
	machines, other = _("Sterilization loads by machine"), _("Indicators, washing and packs")
	rows = []
	for row in s["equipment"]:
		rows.append(
			{
				"section": machines,
				"item": row["equipment_name"],
				"value": row["loads"],
				"detail": _("Passed {0}, failed {1}, failure rate {2} %").format(
					row["passed"], row["failed"], row["fail_rate"]
				),
			}
		)
	rows += [
		{"section": other, "item": _("Biological indicator tests"), "value": s["biological"]["tests"]},
		{"section": other, "item": _("Biological indicators positive"), "value": s["biological"]["positive"]},
		{
			"section": other,
			"item": _("Wash batches (passed / failed)"),
			"value": s["wash"]["batches"],
			"detail": f"{s['wash']['passed']} / {s['wash']['failed']}",
		},
		{"section": other, "item": _("Packs sterilized"), "value": s["packs_sterilized"]},
		{"section": other, "item": _("Recall orders"), "value": s["recalls"]},
	]
	issued = _("Packs issued by department")
	rows += [{"section": issued, "item": row["department"], "value": row["packs"]} for row in s["issued"]]
	incidents = _("Incidents and non-conformities")
	rows += [
		{"section": incidents, "item": _(row["incident_type"] or ""), "value": row["count"]}
		for row in s["incidents"]
	]
	return _columns(), rows
