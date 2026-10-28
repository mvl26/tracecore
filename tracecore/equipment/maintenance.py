"""Bảo trì, kiểm định, hiệu chuẩn và sự cố thiết bị (M5, FEAT-039; FR-M5-03 .1-.3; UC-22; BRU-EQP-002; A-42).

Các hàm của controller `Maintenance Record`: `before_submit` chặn đóng hồ sơ thiếu chứng nhận hoặc hạn hiệu lực
(FR-M5-03.3); `on_submit` cập nhật hạn trên `Equipment`, mở lại máy đang khóa vì quá hạn khi hạn mới còn hiệu lực và tạo
hồ sơ Nháp kế tiếp theo chu kỳ (FR-M5-03.2). Trạng thái máy chỉ đổi qua `equipment.status.set_status`.
"""

import frappe
from frappe import _
from frappe.utils import add_months, cint, getdate, today

from tracecore.equipment.status import set_status

DOCTYPE = "Maintenance Record"
# loại hồ sơ → hạn hiệu lực trên Equipment (A-42 M4); sự cố không có hạn
DUE_FIELDS = {
	"Inspection": "inspection_due",
	"Calibration": "calibration_due",
	"Preventive": "maintenance_due",
}
CERTIFIED_TYPES = ("Inspection", "Calibration")
# hạn quá ngày → lý do khóa của máy (A-42 M5); bảo trì phòng ngừa quá hạn chỉ nhắc, không khóa
EXPIRY_REASONS = {
	"inspection_due": "Inspection Expired",
	"calibration_due": "Calibration Expired",
}
# trường chép sang hồ sơ kế tiếp
NEXT_FIELDS = ("equipment", "record_type", "cycle_months", "vendor", "contract_no", "sla_hours")


def expired_reason(row):
	"""Lý do khóa vì hạn đã qua của máy (``row`` có ``inspection_due``/``calibration_due``), hoặc None; kiểm định ưu tiên."""
	for field, reason in EXPIRY_REASONS.items():
		due = row.get(field)
		if due and getdate(due) < getdate(today()):
			return reason
	return None


def _save_machine(equipment, status=None, **fields):
	"""Lưu hạn/lý do khóa của máy (cờ ``tc_equipment``), rồi đổi trạng thái qua ``set_status``."""
	if fields:
		doc = frappe.get_doc("Equipment", equipment, for_update=True)
		doc.update(fields)
		doc.flags.tc_equipment = True
		doc.save(ignore_permissions=True)
	if status:
		set_status(equipment, status)


def settle_expiry_lock(equipment):
	"""Máy đang Khóa vì quá hạn: đổi lý do theo hạn còn quá, hoặc mở lại khi mọi hạn đã còn hiệu lực.

	Máy khóa vì test hằng ngày, đang sửa chữa hoặc ngừng sử dụng giữ nguyên.
	"""
	row = frappe.db.get_value(
		"Equipment",
		equipment,
		["status", "lock_reason", "inspection_due", "calibration_due"],
		as_dict=True,
	)
	if not row or row.status != "Locked" or row.lock_reason not in EXPIRY_REASONS.values():
		return
	reason = expired_reason(row)
	if reason == row.lock_reason:
		return
	if reason:
		_save_machine(equipment, lock_reason=reason)
	else:
		_save_machine(equipment, status="Ready", lock_reason=None)


def apply_validity(equipment, field, due):
	"""Đặt hạn hiệu lực mới của máy rồi mở lại/đổi lý do khóa nếu máy đang khóa vì quá hạn."""
	_save_machine(equipment, **{field: due})
	settle_expiry_lock(equipment)


def before_submit(doc):
	"""Chặn đóng hồ sơ kiểm định/hiệu chuẩn thiếu chứng nhận hoặc hạn hiệu lực (FR-M5-03.3, UC-22 E1)."""
	if doc.record_type in CERTIFIED_TYPES:
		if not doc.certificate:
			frappe.throw(_("A certificate is required to close an inspection or calibration record."))
		if not doc.valid_until:
			frappe.throw(_("Valid Until is required to close an inspection or calibration record."))
	doc.performed_on = doc.performed_on or today()
	if doc.valid_until and getdate(doc.valid_until) < getdate(doc.performed_on):
		frappe.throw(_("Valid Until cannot be before Performed On."))


def on_submit(doc):
	"""Ghi sổ: lập hồ sơ kế tiếp theo chu kỳ rồi cập nhật hạn hiệu lực của máy."""
	next_name = plan_next(doc)
	field = DUE_FIELDS.get(doc.record_type)
	if not field:
		return
	due = doc.valid_until
	if not due and doc.record_type == "Preventive" and next_name:
		due = frappe.db.get_value(DOCTYPE, next_name, "planned_date")
	if due:
		apply_validity(doc.equipment, field, due)


def plan_next(doc):
	"""Hồ sơ Nháp kế tiếp theo chu kỳ (FR-M5-03.2); trả tên hồ sơ hoặc None (một lần, hoặc sự cố).

	Hồ sơ sửa lại (amend) dùng lại bản Nháp kế tiếp của hồ sơ cũ thay vì thêm bản thứ hai.
	"""
	if doc.record_type == "Incident" or cint(doc.cycle_months) <= 0:
		return None
	planned = add_months(doc.performed_on, cint(doc.cycle_months))
	name = None
	if doc.amended_from:
		old_next = frappe.db.get_value(DOCTYPE, doc.amended_from, "next_record")
		if old_next and frappe.db.get_value(DOCTYPE, old_next, "docstatus") == 0:
			row = frappe.get_doc(DOCTYPE, old_next)
			row.planned_date = planned
			row.reminded_30 = row.reminded_7 = 0
			row.save(ignore_permissions=True)
			name = old_next
	if not name:
		row = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				**{field: doc.get(field) for field in NEXT_FIELDS},
				"planned_date": planned,
			}
		)
		row.insert(ignore_permissions=True)
		name = row.name
	frappe.db.set_value(DOCTYPE, doc.name, "next_record", name, update_modified=False)
	doc.next_record = name
	return name
