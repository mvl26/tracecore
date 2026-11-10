"""IC Chemical Consumption by Department — báo cáo hóa chất KSNK quý (FEAT-066; FR-M12-12, FR-M12-12.2; QĐ 38; UC-46).

Lít theo 5 loại hóa chất × khoa của một quý (hoặc một tháng), dòng Toàn viện; bỏ bộ (tháng, khoa, item) đang "Chờ xác
nhận" nguồn. Tổng quý = tổng 3 tháng vì cùng cộng từ bảng tháng (``chemicals.summary``). Lít dung dịch VST nhanh /
1.000 ngày nằm viện khi M13 có mẫu số, không thì ghi "Chưa có mẫu số". Xuất Excel/PDF bằng nút có sẵn của Frappe.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from tracecore.compliance_audit import chemicals

TYPE_FIELDS = {
	"Hand Rub": "hand_rub",
	"Soap": "soap",
	"Surface Disinfectant": "surface",
	"Instrument Disinfectant": "instrument",
	"Other": "other",
}
TYPE_LABELS = {
	"Hand Rub": "Hand Rub (L)",
	"Soap": "Soap (L)",
	"Surface Disinfectant": "Surface Disinfectant (L)",
	"Instrument Disinfectant": "Instrument Disinfectant (L)",
	"Other": "Other (L)",
}


def _columns():
	columns = [{"fieldname": "department", "label": _("Department"), "fieldtype": "Link", "options": "Department", "width": 200}]
	columns += [
		{"fieldname": field, "label": _(TYPE_LABELS[kind]), "fieldtype": "Float", "precision": 1, "width": 130}
		for kind, field in TYPE_FIELDS.items()
	]
	columns += [
		{"fieldname": "patient_days", "label": _("Patient Days"), "fieldtype": "Int", "width": 110},
		{
			"fieldname": "hand_rub_per_1000",
			"label": _("Hand Rub per 1,000 Patient Days (L)"),
			"fieldtype": "Float",
			"precision": 1,
			"width": 160,
		},
		{"fieldname": "note", "label": _("Note"), "fieldtype": "Data", "width": 280},
	]
	return columns


def _note(entry):
	notes = []
	if entry["patient_days"] is None:
		notes.append(_("No denominator yet"))
	if entry["awaiting"]:
		notes.append(_("{0} item(s) awaiting source confirmation, not counted").format(entry["awaiting"]))
	if entry["no_litre"]:
		notes.append(_("{0} record(s) without a litre conversion").format(entry["no_litre"]))
	return "; ".join(notes)


def _row(entry, department=None, is_total=False):
	row = {TYPE_FIELDS[kind]: entry["litres"][kind] for kind in TYPE_FIELDS}
	row.update(
		department=department,
		patient_days=entry["patient_days"],
		hand_rub_per_1000=entry["hand_rub_per_1000"],
		note=_note(entry),
	)
	if is_total:
		row["department"] = _("Whole hospital ({0} departments)").format(entry["departments"])
		row["is_total"] = 1
		row["bold"] = 1
	return row


def execute(filters=None):
	filters = frappe._dict(filters or {})
	now = getdate(today())
	year = cint(filters.year) or now.year
	quarter = cint(filters.quarter) or (now.month - 1) // 3 + 1
	summary = chemicals.summary(year, quarter, filters.department or None)
	data = [_row(entry, entry["department"]) for entry in summary["departments"]]
	data.append(_row(summary["total"], is_total=True))
	message = _("Quarter {0}/{1}; departments with duplicate sources are counted after a source is chosen.").format(
		quarter, year
	)
	return _columns(), data, message
