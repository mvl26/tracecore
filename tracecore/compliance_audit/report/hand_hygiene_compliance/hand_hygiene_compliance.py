"""Hand Hygiene Compliance (FEAT-061; FR-M12-05, FR-M12-11, FR-M12-14, BRU-AUD-002).

Tỷ lệ tuân thủ vệ sinh tay theo cơ hội, nhóm theo khoa / nghề nghiệp / thời điểm / tháng (``hand_hygiene.breakdown``),
chỉ tính phiếu đã ghi sổ; tỷ lệ đúng kỹ thuật tách riêng. Xuất Excel/PDF bằng nút có sẵn của Frappe. R08/R12 chỉ nhận
khoa của mình.
"""

import frappe
from frappe import _
from frappe.utils import get_first_day, getdate, today

from tracecore.compliance_audit import hand_hygiene

GROUP_LABELS = {
	"department": "Department",
	"profession": "Observed Profession",
	"moment": "Moment",
	"month": "Month",
}


def _columns(group_by):
	return [
		{"fieldname": "group", "label": _(GROUP_LABELS[group_by]), "fieldtype": "Data", "width": 200},
		{"fieldname": "audits", "label": _("Audits"), "fieldtype": "Int", "width": 80},
		{"fieldname": "opportunities", "label": _("Opportunities"), "fieldtype": "Int", "width": 110},
		{"fieldname": "actioned", "label": _("With Action"), "fieldtype": "Int", "width": 110},
		{"fieldname": "compliance_rate", "label": _("Compliance Rate"), "fieldtype": "Percent", "width": 120},
		{"fieldname": "technique_ok", "label": _("Correct Technique"), "fieldtype": "Int", "width": 130},
		{"fieldname": "technique_rate", "label": _("Technique Rate"), "fieldtype": "Percent", "width": 120},
		{"fieldname": "result", "label": _("Result"), "fieldtype": "Data", "width": 260},
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.from_date = getdate(filters.from_date or get_first_day(today()))
	filters.to_date = getdate(filters.to_date or today())
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date must be before To Date."))
	group_by = filters.group_by if filters.group_by in GROUP_LABELS else "department"
	data = [
		{
			"group": row.key,
			"audits": row.sessions,
			"opportunities": row.total,
			"actioned": row.actioned,
			"compliance_rate": row.rate,
			"technique_ok": row.technique_ok,
			"technique_rate": row.technique_rate,
			"result": row.rate_label,
		}
		for row in hand_hygiene.breakdown(filters, group_by)
	]
	return _columns(group_by), data
