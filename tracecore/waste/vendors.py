"""Đơn vị xử lý chất thải (FEAT-049, UC-36 A1, A2, E4, FR-M10-05, .1-.4, BRU-WST-003, BRU-CST-002, A-62).

Giấy phép và hợp đồng xét theo ngày nên phiếu luôn đúng kể cả khi job hằng ngày chưa chạy; `status` chỉ để lọc danh
sách. Đơn giá: hợp đồng còn hiệu lực của đúng loại, không có thì đơn giá mặc định của loại (FR-M10-05.4).
"""

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, formatdate, getdate, today

from tracecore.core import notification
from tracecore.waste import types

DOCTYPE = "Waste Treatment Vendor"
ACTIVE, EXPIRED = "Active", "Expired"
EXPIRY_NOTICE_DAYS = (60, 30, 7)
EXPIRING_EVENT = "WASTE_VENDOR_EXPIRING"
PENDING_EVENT = "WASTE_DOCUMENT_PENDING"
DOCUMENT_DAYS = 7


def validate(doc):
	"""FR-M10-05.1: thiếu giấy phép, hiệu lực hoặc loại được phép thì từ chối."""
	if not (doc.license_no or "").strip() or not doc.license_valid_to or not doc.permitted_types:
		frappe.throw(
			_("Enter the license number, its validity and the waste types allowed."), frappe.MandatoryError
		)
	allowed = [row.waste_type for row in doc.permitted_types]
	if len(allowed) != len(set(allowed)):
		frappe.throw(_("A waste type is listed twice."))
	for row in doc.contracts:
		if row.waste_type not in allowed:
			frappe.throw(
				_("Contract {0} covers {1}, which is not an allowed waste type.").format(
					row.contract_no, row.waste_type
				)
			)
		if getdate(row.valid_to) < getdate(row.valid_from):
			frappe.throw(_("Contract {0} ends before it starts.").format(row.contract_no))
		if flt(row.rate_per_kg) < 0:
			frappe.throw(_("Rate per kg cannot be negative."))
	doc.status = ACTIVE if getdate(doc.license_valid_to) >= getdate(today()) else EXPIRED


def _contracts(vendor, waste_type, on_date):
	return frappe.get_all(
		"Vendor Contract",
		filters={
			"parent": vendor,
			"parenttype": DOCTYPE,
			"waste_type": waste_type,
			"valid_from": ["<=", getdate(on_date)],
			"valid_to": [">=", getdate(on_date)],
		},
		fields=["contract_no", "rate_per_kg", "valid_from"],
		order_by="valid_from desc",
		limit=1,
	)


def permitted(vendor, waste_type, on_date=None):
	"""BRU-WST-003: giấy phép còn hiệu lực, loại được phép và có hợp đồng còn hiệu lực cho đúng loại đó."""
	on_date = on_date or today()
	license_to = frappe.db.get_value(DOCTYPE, vendor, "license_valid_to") if vendor else None
	if not license_to or getdate(license_to) < getdate(on_date):
		return False
	if not frappe.db.exists(
		"Vendor Permitted Waste Type", {"parent": vendor, "parenttype": DOCTYPE, "waste_type": waste_type}
	):
		return False
	return bool(_contracts(vendor, waste_type, on_date))


def permitted_types(vendor, on_date=None):
	rows = frappe.get_all(
		"Vendor Permitted Waste Type", filters={"parent": vendor, "parenttype": DOCTYPE}, pluck="waste_type"
	)
	return [waste_type for waste_type in rows if permitted(vendor, waste_type, on_date)]


def selectable():
	"""Đơn vị chọn được khi bàn giao, kèm loại còn hiệu lực (UC-36 bước 1)."""
	rows = []
	for row in frappe.get_all(
		DOCTYPE, fields=["name", "vendor_name", "license_valid_to"], order_by="vendor_name asc"
	):
		waste_types = permitted_types(row.name)
		if waste_types:
			rows.append({**row, "waste_types": waste_types})
	return rows


def rate_for(vendor, waste_type, on_date):
	"""Đơn giá/kg hiệu lực vào ngày: hợp đồng > 0, không thì đơn giá mặc định của loại (FR-M10-05.4)."""
	rows = _contracts(vendor, waste_type, on_date)
	if rows and flt(rows[0].rate_per_kg) > 0:
		return flt(rows[0].rate_per_kg)
	return types.rate_on(waste_type, on_date)


def expiring_on(day, vendor):
	"""[(loại, số ngày còn lại)] nếu `day` đúng là mốc 60/30/7 ngày của giấy phép hoặc hợp đồng (FR-M10-05.2)."""
	doc = frappe.get_doc(DOCTYPE, vendor)
	hits = []
	left = date_diff(doc.license_valid_to, day)
	if left in EXPIRY_NOTICE_DAYS:
		hits.append(("license", left))
	for valid_to in {row.valid_to for row in doc.contracts}:
		left = date_diff(valid_to, day)
		if left in EXPIRY_NOTICE_DAYS:
			hits.append(("contract", left))
	return hits


def _notify_expiring(vendor, day):
	for kind, left in expiring_on(day, vendor):
		marker = _("{0}: {1} ends in {2} days ({3}).").format(
			vendor,
			_("the environmental license") if kind == "license" else _("a contract"),
			left,
			formatdate(add_days(day, left)),
		)
		if frappe.db.exists(
			"Notification Delivery", {"event_code": EXPIRING_EVENT, "ref_name": vendor, "message": marker}
		):
			continue
		notification.emit(
			EXPIRING_EVENT,
			frappe._dict(doctype=DOCTYPE, name=vendor),
			subject=_("Waste vendor {0} is close to expiry").format(vendor),
			message=marker,
		)


def remind_pending_documents(day=None):
	"""UC-36 A4: phiếu chờ chứng từ CTNH quá 7 ngày → nhắc R07/R09 một lần; trả các phiếu vừa nhắc."""
	limit = add_days(day or today(), -DOCUMENT_DAYS)
	names = frappe.get_all(
		"Waste Handover",
		filters={
			"docstatus": 1,
			"document_pending": 1,
			"document_pending_reminded": 0,
			"handover_at": ["<", limit],
		},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value("Waste Handover", name, "document_pending_reminded", 1, update_modified=False)
		notification.emit(
			PENDING_EVENT,
			frappe._dict(doctype="Waste Handover", name=name),
			subject=_("Handover {0} is still waiting for its hazardous waste document").format(name),
		)
	return names


def run_daily():
	"""Job hằng ngày: hết hiệu lực thì chuyển trạng thái (FR-M10-05.3), báo trước 60/30/7 ngày, nhắc chứng từ chờ."""
	day = today()
	for row in frappe.get_all(DOCTYPE, fields=["name", "status", "license_valid_to"]):
		status = ACTIVE if getdate(row.license_valid_to) >= getdate(day) else EXPIRED
		if status != row.status:
			frappe.db.set_value(DOCTYPE, row.name, "status", status)
		_notify_expiring(row.name, day)
	remind_pending_documents(day)
