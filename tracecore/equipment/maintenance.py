"""Bảo trì, kiểm định, hiệu chuẩn và sự cố thiết bị (M5, FEAT-039; FR-M5-03 .1-.3, FR-M5-04 .1-.4; UC-22; BRU-EQP-002; A-42).

Các hàm của controller `Maintenance Record`: `before_submit` chặn đóng hồ sơ thiếu chứng nhận, hạn hiệu lực hoặc kết quả
kiểm tra sau sửa (FR-M5-03.3, FR-M5-04.4); `on_submit` cập nhật hạn trên `Equipment`, mở lại máy đang khóa vì quá hạn khi
hạn mới còn hiệu lực và tạo hồ sơ Nháp kế tiếp theo chu kỳ (FR-M5-03.2). Sự cố: lưu Nháp đưa máy sang Sửa chữa và đánh
dấu mẻ/lô đang mở qua hook M2 (FR-M5-04, .2); ghi sổ hoặc bỏ bản Nháp đưa máy ra khỏi Sửa chữa khi không còn sự cố mở nào
khác. Trạng thái máy chỉ đổi qua `equipment.status.set_status`.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, date_diff, get_datetime, getdate, now_datetime, today

from tracecore.core import extension
from tracecore.equipment.status import set_status

DOCTYPE = "Maintenance Record"
INCIDENT_HOOK = "tracecore_equipment_incident"
# nhắc kế hoạch trước 30 và 7 ngày tới R02 và R10 (A-42 M1: chuông Desk; email/SMS/leo thang thuộc FEAT-010)
RECIPIENT_ROLES = ("TC R02", "TC R10")
REMIND_WINDOWS = (30, 7)
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


def check_incident_target(doc):
	"""Không ghi sự cố cho máy đã ngừng sử dụng."""
	if (
		doc.record_type == "Incident"
		and doc.is_new()
		and frappe.db.get_value("Equipment", doc.equipment, "status") == "Retired"
	):
		frappe.throw(
			_("Equipment {0} is retired; an incident cannot be recorded for it.").format(doc.equipment)
		)


def prepare_incident(doc):
	"""``before_insert`` của sự cố: nhớ trạng thái máy trước đó và đánh dấu mẻ/lô đang mở qua hook M2 (FR-M5-04.2).

	Máy đã ở Sửa chữa (sự cố khác còn mở) thì trạng thái trước là Sẵn sàng.
	"""
	status = frappe.db.get_value("Equipment", doc.equipment, "status")
	doc.status_before = status if status != "Repair" else "Ready"
	flagged_at = now_datetime()
	for flagged in extension.run(INCIDENT_HOOK, doc.equipment, doc.name):
		for item in flagged:
			doc.append("affected_loads", {**item, "flagged_at": flagged_at})


def open_incident(doc):
	"""``after_insert`` của sự cố: máy sang Sửa chữa; từ lúc này không chọn được máy khi tạo lô/mẻ (FR-M5-04.1)."""
	set_status(doc.equipment, "Repair")


def _end_repair(equipment, status, exclude):
	"""Đưa máy khỏi Sửa chữa về `status` khi không còn sự cố mở nào khác (Nháp, chưa bỏ); máy đã đổi trạng thái giữ nguyên."""
	if frappe.db.count(
		DOCTYPE,
		{
			"equipment": equipment,
			"record_type": "Incident",
			"docstatus": 0,
			"abandoned": 0,
			"name": ["!=", exclude],
		},
	):
		return
	if frappe.db.get_value("Equipment", equipment, "status") != "Repair":
		return
	fields = {"lock_reason": None} if status == "Ready" else {}
	_save_machine(equipment, status=status, **fields)


def close_incident(doc):
	"""Ghi sổ sự cố: máy về Sẵn sàng (FR-M5-04)."""
	_end_repair(doc.equipment, "Ready", doc.name)


def abandon(doc, reason):
	"""Bỏ bản Nháp (Frappe không hủy được Nháp, chứng từ không xóa): ghi lý do, sự cố trả máy về trạng thái trước đó."""
	text = (reason or "").strip()
	if not text:
		frappe.throw(_("A reason is required to abandon a record."))
	if doc.docstatus != 0 or doc.abandoned:
		frappe.throw(_("Only a draft record that is not already abandoned can be abandoned."))
	doc.abandoned = 1
	doc.abandon_reason = text
	doc.save(ignore_permissions=True)
	if doc.record_type == "Incident":
		_end_repair(doc.equipment, doc.status_before or "Ready", doc.name)


def before_submit(doc):
	"""Chặn đóng hồ sơ đã bỏ, kiểm định/hiệu chuẩn thiếu chứng nhận hoặc hạn hiệu lực (FR-M5-03.3, UC-22 E1), sự cố thiếu
	kết quả kiểm tra sau sửa (FR-M5-04.4, UC-22 E2)."""
	if doc.abandoned:
		frappe.throw(_("An abandoned record cannot be closed."))
	if doc.record_type == "Incident" and not (doc.post_repair_check or "").strip():
		frappe.throw(_("The post-repair check result is required to close an incident."))
	if doc.record_type in CERTIFIED_TYPES:
		if not doc.certificate:
			frappe.throw(_("A certificate is required to close an inspection or calibration record."))
		if not doc.valid_until:
			frappe.throw(_("Valid Until is required to close an inspection or calibration record."))
	doc.performed_on = doc.performed_on or today()
	if doc.valid_until and getdate(doc.valid_until) < getdate(doc.performed_on):
		frappe.throw(_("Valid Until cannot be before Performed On."))


def on_submit(doc):
	"""Ghi sổ: sự cố đưa máy về Sẵn sàng; hồ sơ khác lập hồ sơ kế tiếp theo chu kỳ rồi cập nhật hạn hiệu lực của máy."""
	if doc.record_type == "Incident":
		return close_incident(doc)
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


# --- Việc định kỳ ----------------------------------------------------------------------------------------------------


def _recipients():
	users = []
	for role in RECIPIENT_ROLES:
		holders = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
		if not holders:
			continue
		for user in frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1}, pluck="name"):
			if user not in users:
				users.append(user)
	return users


def _notify(users, subject, doctype, name):
	"""Thông báo chuông Desk (Notification Log); email/SMS và leo thang thuộc FEAT-010 (A-42 M1)."""
	for user in users:
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"subject": subject,
				"document_type": doctype,
				"document_name": name,
			}
		).insert(ignore_permissions=True)


def lock_overdue():
	"""Việc 00:00 (FR-M5-03.1, BRU-EQP-002): máy Sẵn sàng có kiểm định/hiệu chuẩn đã quá ngày → Khóa; trả tên các máy bị khóa.

	Máy đang được R02 mở khóa tạm (``unlock_until`` chưa hết) bỏ qua tới lần chạy sau khi hết hạn mở. Bảo trì phòng ngừa
	quá hạn không khóa (chỉ nhắc). Báo R02 và R10 bằng chuông Desk.
	"""
	day = today()
	now = now_datetime()
	rows = frappe.get_all(
		"Equipment",
		filters={"status": "Ready"},
		or_filters=[["inspection_due", "<", day], ["calibration_due", "<", day]],
		fields=["name", "inspection_due", "calibration_due", "unlock_until"],
		order_by="name asc",
	)
	locked = []
	users = _recipients()
	for row in rows:
		if row.unlock_until and get_datetime(row.unlock_until) > now:
			continue
		reason = expired_reason(row)
		if not reason:
			continue
		_save_machine(row.name, status="Locked", lock_reason=reason)
		locked.append(row.name)
		_notify(
			users,
			_("Equipment {0} is locked: {1}").format(row.name, _(reason, context="Equipment")),
			"Equipment",
			row.name,
		)
	return locked


def remind_due():
	"""Việc hằng ngày (FR-M5-03, UC-22 bước 1): hồ sơ kế hoạch còn Nháp đến hạn trong 30 ngày → nhắc R02 và R10.

	Mốc 30 ngày rồi mốc 7 ngày, mỗi mốc một lần (``reminded_30``/``reminded_7``); hồ sơ lần đầu được thấy trong 7 ngày hoặc đã
	quá ngày kế hoạch chỉ nhắc một lần. Bỏ qua sự cố, hồ sơ đã bỏ, chưa có ngày kế hoạch.
	"""
	day = getdate(today())
	users = _recipients()
	for row in frappe.get_all(
		DOCTYPE,
		# "is set" tách riêng vì Frappe bọc so sánh bằng ifnull: ngày trống sẽ lọt vào điều kiện "<="
		filters=[
			["docstatus", "=", 0],
			["abandoned", "=", 0],
			["record_type", "!=", "Incident"],
			["planned_date", "is", "set"],
			["planned_date", "<=", add_days(day, max(REMIND_WINDOWS))],
		],
		fields=["name", "equipment", "record_type", "planned_date", "reminded_30", "reminded_7"],
		order_by="planned_date asc, name asc",
	):
		window = (
			min(REMIND_WINDOWS)
			if date_diff(row.planned_date, day) <= min(REMIND_WINDOWS)
			else max(REMIND_WINDOWS)
		)
		if row.get(f"reminded_{window}"):
			continue
		_notify(
			users,
			_("{0} of equipment {1} is planned for {2}").format(
				_(row.record_type, context=DOCTYPE),
				row.equipment,
				frappe.format(row.planned_date, {"fieldtype": "Date"}),
			),
			DOCTYPE,
			row.name,
		)
		# mốc 7 ngày bao luôn mốc 30 ngày
		flags = {"reminded_30": 1} if window == max(REMIND_WINDOWS) else {"reminded_30": 1, "reminded_7": 1}
		frappe.db.set_value(DOCTYPE, row.name, flags, update_modified=False)
