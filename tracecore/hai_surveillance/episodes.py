"""Đợt thiết bị xâm lấn `Device Episode` (FEAT-062; FR-M13-04, .1, .2, FR-M12-07, BRU-HAI-005, ADR-010; A-141 a).

- Mã người bệnh: trường Password + hash + bản che qua `core.patient_code`; không trường họ tên; danh sách chỉ mã che.
- Số ngày thiết bị = (ngày rút hoặc hôm nay) − ngày đặt + 1 (đếm cả hai đầu; ảnh SCR-55: đặt 29/10, hôm nay 02/11 → 5).
- Một người bệnh (hash) không có hai đợt cùng loại thiết bị đang mở tại một khoa.
- ``bundle_status``: phiếu gói dự phòng ghi sổ trong ngày của đợt (M12 trỏ về qua Link `Audit Session.device_episode`).
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, formatdate, getdate, today

from tracecore.core import patient_code
from tracecore.core.errors import Block, BlockedError

DOCTYPE = "Device Episode"
OPEN, CLOSED = "Open", "Closed"
DEVICE_TYPES = ("Ventilator", "Central Line", "Urinary Catheter")
# loại gói dự phòng (`Audit Template.bundle_type`) ứng với từng loại thiết bị (A-141 e)
BUNDLE_OF_DEVICE = {"Ventilator": "VAP", "Central Line": "CLABSI", "Urinary Catheter": "CAUTI"}
VALUE_FIELDS = ("department", "device_type", "patient_code", "birth_year", "sex", "inserted_on", "removed_on")
LIST_FIELDS = (
	"name",
	"department",
	"device_type",
	"patient_code_masked",
	"birth_year",
	"sex",
	"inserted_on",
	"removed_on",
	"status",
	"device_days",
)
MIN_BIRTH_YEAR = 1900


def blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


def _date_invalid(reason, action, field):
	return blocked("DEVICE_EPISODE_DATE_INVALID", _("Date not valid"), reason, action, items=[field])


def device_days(inserted_on, removed_on=None, on=None):
	end = getdate(removed_on or on or today())
	return max(date_diff(end, getdate(inserted_on)) + 1, 0)


# --- kiểm ---------------------------------------------------------------------------------------------------------


def validate(doc):
	"""Gọi từ ``DeviceEpisode.validate``."""
	patient_code.apply(doc)
	now = getdate(today())
	if doc.device_type not in DEVICE_TYPES:
		raise blocked(
			"DEVICE_EPISODE_TYPE_INVALID",
			_("Device not valid"),
			_("Device {0} is not a tracked invasive device.").format(doc.device_type or "-"),
			_("Choose ventilator, central line or urinary catheter."),
			items=["device_type"],
		)
	if not doc.inserted_on or getdate(doc.inserted_on) > now:
		raise _date_invalid(
			_("The insertion date must be today or earlier."), _("Correct the insertion date."), "inserted_on"
		)
	if doc.removed_on:
		if getdate(doc.removed_on) > now:
			raise _date_invalid(
				_("The removal date {0} is later than today.").format(formatdate(doc.removed_on)),
				_("Correct the removal date."),
				"removed_on",
			)
		if getdate(doc.removed_on) < getdate(doc.inserted_on):
			raise _date_invalid(
				_("The removal date {0} is before the insertion date {1}.").format(
					formatdate(doc.removed_on), formatdate(doc.inserted_on)
				),
				_("Enter a removal date on or after the insertion date."),
				"removed_on",
			)
	if doc.birth_year and not MIN_BIRTH_YEAR <= cint(doc.birth_year) <= now.year:
		raise _date_invalid(
			_("Birth year {0} is not valid.").format(doc.birth_year), _("Correct the birth year."), "birth_year"
		)
	doc.status = CLOSED if doc.removed_on else OPEN
	doc.device_days = device_days(doc.inserted_on, doc.removed_on) if doc.removed_on else None
	if doc.status == OPEN and doc.patient_code_hash:
		other = frappe.db.get_value(
			DOCTYPE,
			{
				"patient_code_hash": doc.patient_code_hash,
				"device_type": doc.device_type,
				"department": doc.department,
				"status": OPEN,
				"name": ["!=", doc.name or ""],
			},
			"name",
		)
		if other:
			raise blocked(
				"DEVICE_EPISODE_OPEN",
				_("Episode already open"),
				_("This patient already has an open {0} episode ({1}) in this department.").format(
					_(doc.device_type).lower(), other
				),
				_("Close the open episode first, or use it."),
				object_type=DOCTYPE,
				object_name=other,
			)


def on_trash(doc):
	frappe.throw(_("Device episodes are never deleted; close the episode instead."))


# --- ghi ----------------------------------------------------------------------------------------------------------


def open_episode(values):
	doc = frappe.new_doc(DOCTYPE)
	doc.update({key: values.get(key) for key in VALUE_FIELDS if values.get(key) not in (None, "")})
	doc.insert(ignore_permissions=True)
	return doc


def close_episode(name, removed_on):
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.status == CLOSED:
		raise blocked(
			"DEVICE_EPISODE_CLOSED",
			_("Episode already closed"),
			_("Episode {0} was closed on {1}.").format(doc.name, formatdate(doc.removed_on)),
			_("Open a new episode if the device was inserted again."),
			object_type=DOCTYPE,
			object_name=doc.name,
		)
	doc.removed_on = getdate(removed_on) if removed_on else None
	if not doc.removed_on:
		raise _date_invalid(_("The removal date is required."), _("Enter the removal date."), "removed_on")
	doc.save(ignore_permissions=True)
	return doc


# --- đọc ----------------------------------------------------------------------------------------------------------


def as_dict(doc, on=None):
	row = {field: doc.get(field) for field in LIST_FIELDS}
	for field in ("inserted_on", "removed_on"):
		row[field] = str(getdate(row[field])) if row[field] else None
	row["device_days"] = device_days(doc.inserted_on, doc.removed_on, on)
	return row


def bundle_templates(on):
	"""{bundle_type: tên phiên bản mẫu gói đã duyệt đang hiệu lực} (đọc qua Link, không import M12)."""
	rows = frappe.get_all(
		"Audit Template",
		filters={
			"docstatus": 1,
			"audit_type": "Prevention Bundle",
			"bundle_type": ["in", list(BUNDLE_OF_DEVICE.values())],
			"effective_from": ["<=", getdate(on)],
		},
		fields=["name", "bundle_type"],
		order_by="version_no desc, effective_from desc",
	)
	result = {}
	for row in rows:
		result.setdefault(row.bundle_type, row.name)
	return result


def bundle_status(names, on):
	"""{đợt: "Pass" | "Fail"} theo phiếu gói ghi sổ mới nhất trong ngày ``on``; đợt chưa chấm không có khóa."""
	if not names:
		return {}
	rows = frappe.get_all(
		"Audit Session",
		filters={"docstatus": 1, "device_episode": ["in", list(names)], "audit_date": getdate(on)},
		fields=["device_episode", "result"],
		order_by="modified desc",
	)
	status = {}
	for row in rows:
		status.setdefault(row.device_episode, row.result)
	return status


def open_list(departments, on=None):
	"""Đợt đang mở của các khoa (mã che), kèm số ngày, kết quả gói hôm nay và mẫu gói để chấm."""
	on = getdate(on or today())
	rows = frappe.get_all(
		DOCTYPE,
		filters={"department": ["in", list(departments) or [""]], "status": OPEN},
		fields=list(LIST_FIELDS),
		order_by="inserted_on asc, name asc",
	)
	status = bundle_status([row.name for row in rows], on)
	templates = bundle_templates(on)
	result = []
	for row in rows:
		item = as_dict(row, on)
		item["bundle_result"] = status.get(row.name)
		item["bundle_template"] = templates.get(BUNDLE_OF_DEVICE[row.device_type])
		result.append(item)
	return result


def days_between(department, from_date, to_date):
	"""Tổng ngày thiết bị theo loại trong [from, to] (phần giao của từng đợt với khoảng)."""
	start, end = getdate(from_date), getdate(to_date)
	rows = frappe.get_all(
		DOCTYPE,
		filters={"department": department, "inserted_on": ["<=", end]},
		or_filters={"removed_on": [">=", start], "status": OPEN},
		fields=["device_type", "inserted_on", "removed_on"],
	)
	days = dict.fromkeys(DEVICE_TYPES, 0)
	for row in rows:
		first = max(getdate(row.inserted_on), start)
		last = min(getdate(row.removed_on) if row.removed_on else getdate(today()), end)
		if last >= first:
			days[row.device_type] += date_diff(last, first) + 1
	return days
