"""Luật Loại chất thải (FEAT-047, FR-M10-01, .1-.4, BRU-WST-001, BRU-WST-002, A-60 W6-W8)."""

import frappe
from frappe import _
from frappe.utils import cstr, flt, getdate

# Nhóm theo TT 20/2021/TT-BYT → mã màu (FR-M10-01.2)
GROUP_COLORS = {
	"Sharp Infectious": "Yellow",
	"Non-sharp Infectious": "Yellow",
	"High-risk Infectious": "Yellow",
	"Anatomical": "Yellow",
	"Hazardous Non-infectious": "Black",
	"General": "Green",
	"Recyclable": "White",
}
DEFAULT_STORAGE_HOURS = 48
DEFAULT_COLD_HOURS = 168


REQUIRED_FIELDS = ("waste_group", "packaging", "max_storage_hours")


def validate(doc):
	missing = [doc.meta.get_label(field) for field in REQUIRED_FIELDS if not doc.get(field)]
	if missing:
		frappe.throw(_("Enter the missing fields: {0}.").format(", ".join(_(label) for label in missing)))
	doc.color_code = GROUP_COLORS.get(doc.waste_group)
	if flt(doc.std_weight_kg) <= 0:
		frappe.throw(_("Standard weight per bag must be greater than 0."))
	if flt(doc.max_storage_hours) <= 0:
		frappe.throw(_("Maximum storage hours must be greater than 0."))
	_check_storage_override(doc)
	_check_rates(doc)


def _check_storage_override(doc):
	cold = doc.max_storage_cold_hours
	if doc.max_storage_hours == DEFAULT_STORAGE_HOURS and (not cold or cold == DEFAULT_COLD_HOURS):
		return
	if not cstr(doc.storage_override_reason).strip():
		frappe.throw(_("Enter the reason for a storage time other than the default."))


def _check_rates(doc):
	dates = [getdate(row.effective_from) for row in doc.rates]
	if len(dates) != len(set(dates)):
		frappe.throw(_("Two rates cannot start on the same date."))
	if any(flt(row.rate_per_kg) < 0 for row in doc.rates):
		frappe.throw(_("Rate per kg cannot be negative."))
	before = doc.get_doc_before_save()
	if not before:
		return
	# phiên bản cũ giữ nguyên, phiếu đã ghi sổ không tính lại (FR-M10-01.4)
	current = {(getdate(row.effective_from), flt(row.rate_per_kg)) for row in doc.rates}
	if any((getdate(row.effective_from), flt(row.rate_per_kg)) not in current for row in before.rates):
		frappe.throw(_("Existing rates are kept. Add a new rate with its effective date instead."))


def rate_on(waste_type, on_date):
	"""Đơn giá xử lý/kg hiệu lực vào ngày `on_date`; chưa có phiên bản nào thì 0."""
	rows = frappe.get_all(
		"Waste Type Rate",
		filters={
			"parent": waste_type,
			"parenttype": "Waste Type",
			"effective_from": ["<=", getdate(on_date)],
		},
		fields=["rate_per_kg"],
		order_by="effective_from desc",
		limit=1,
	)
	return flt(rows[0].rate_per_kg) if rows else 0
