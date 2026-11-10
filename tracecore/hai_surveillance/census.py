"""Mẫu số ngày theo khoa `Ward Daily Census` (FEAT-062; FR-M13-02, .1, .2, FR-M13-04, BRU-HAI-002; UC-47; A-141).

- Một bản ghi mỗi (ngày, khoa): khóa DB duy nhất + kiểm ở ``validate``. Nhập tay trùng → ``CENSUS_DUPLICATE`` kèm bản
  đã có (UC-47 E2); sửa phải nêu tên bản ghi. Import (``upsert``) cập nhật bản có sẵn (FR-M13-02.2, A-141 Q2).
- Ba số thiết bị ≤ số người bệnh, chỉ rõ trường sai (FR-M13-02.1). Bản ``locked`` (kỳ đã khóa) không sửa được trừ khi
  hàm mở khóa kỳ (FEAT-063) đặt ``flags.tc_period_unlock``.
- ``denominators``: ngày nằm viện và ngày thiết bị cho tỷ suất theo nguồn khoa chọn (`Department.tc_device_day_source`).
- ``bundle_status``: kết quả phiếu gói dự phòng ghi sổ trong ngày của từng đợt (M12 qua Link `Audit Session.device_episode`).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, formatdate, getdate, today

from tracecore.core.errors import Block, BlockedError
from tracecore.hai_surveillance import episodes

DOCTYPE = "Ward Daily Census"
MANUAL, IMPORT = "Manual", "Import"
DEVICE_FIELDS = ("vent_count", "cvc_count", "urinary_catheter_count")
COUNT_FIELDS = ("patient_count", *DEVICE_FIELDS, "admissions")
VALUE_FIELDS = ("department", "census_date", *COUNT_FIELDS)
OUT_FIELDS = ("name", "census_date", "department", "source", "locked", *COUNT_FIELDS)
SOURCE_CENSUS, SOURCE_EPISODE = "Daily Census", "Device Episode"
DEVICE_OF_FIELD = {
	"vent_count": "Ventilator",
	"cvc_count": "Central Line",
	"urinary_catheter_count": "Urinary Catheter",
}
LABEL = {
	"patient_count": "Inpatients",
	"vent_count": "On Ventilator",
	"cvc_count": "Central Line",
	"urinary_catheter_count": "Urinary Catheter",
	"admissions": "Admissions",
}
RECENT_DAYS = 7


def blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


def find(department, census_date):
	return frappe.db.get_value(
		DOCTYPE, {"department": department, "census_date": getdate(census_date)}, "name"
	)


def _duplicate(name, census_date):
	return blocked(
		"CENSUS_DUPLICATE",
		_("Census already entered"),
		_("The census of {0} for this department already exists.").format(formatdate(census_date)),
		_("Open the existing census to change it."),
		object_type=DOCTYPE,
		object_name=name,
	)


# --- kiểm ---------------------------------------------------------------------------------------------------------


def validate(doc):
	"""Gọi từ ``WardDailyCensus.validate``."""
	if not doc.is_new() and cint(doc.get_db_value("locked")) and not doc.flags.tc_period_unlock:
		raise blocked(
			"CENSUS_PERIOD_LOCKED",
			_("Reporting period locked"),
			_("The census of {0} belongs to a locked reporting period.").format(formatdate(doc.census_date)),
			_("Ask the head of infection control to unlock the period with a reason."),
			object_type=DOCTYPE,
			object_name=doc.name,
		)
	if getdate(doc.census_date) > getdate(today()):
		raise blocked(
			"CENSUS_DATE_INVALID",
			_("Census date in the future"),
			_("The census date {0} is later than today.").format(formatdate(doc.census_date)),
			_("Choose today or an earlier day."),
			items=["census_date"],
		)
	for field in COUNT_FIELDS:
		value = doc.get(field)
		if value in (None, "") and field == "admissions":
			continue
		if value in (None, "") or cint(value) != value or cint(value) < 0:
			raise blocked(
				"CENSUS_COUNT_INVALID",
				_("Count not valid"),
				_("{0} must be a whole number of 0 or more.").format(_(LABEL[field])),
				_("Correct the {0} box and save again.").format(_(LABEL[field])),
				items=[field],
			)
	patients = cint(doc.patient_count)
	for field in DEVICE_FIELDS:
		if cint(doc.get(field)) > patients:
			raise blocked(
				"CENSUS_COUNT_INVALID",
				_("Census not saved"),
				_("Patients with {0} ({1}) cannot be more than inpatients ({2}).").format(
					_(LABEL[field]).lower(), cint(doc.get(field)), patients
				),
				_("Correct the {0} box and save again.").format(_(LABEL[field])),
				items=[field],
			)
	if not doc.flags.tc_skip_duplicate_check:
		other = find(doc.department, doc.census_date)
		if other and other != doc.name:
			raise _duplicate(other, doc.census_date)


def on_trash(doc):
	frappe.throw(_("Daily census is never deleted; correct the counts instead."))


# --- ghi ----------------------------------------------------------------------------------------------------------


def save(values, source=MANUAL, name=None, upsert=False, import_batch=None):
	"""Tạo/sửa mẫu số; trả doc. ``name``: sửa đúng bản đó (không đổi ngày/khoa); ``upsert``: (ngày, khoa) đã có thì
	cập nhật (import). Nguồn thành ``source`` của lần ghi cuối."""
	values = {key: values.get(key) for key in VALUE_FIELDS}
	values["census_date"] = getdate(values["census_date"]) if values.get("census_date") else None
	for field in COUNT_FIELDS:
		if values.get(field) not in (None, ""):
			try:
				values[field] = int(values[field])
			except (TypeError, ValueError):
				values[field] = -1  # validate báo CENSUS_COUNT_INVALID cho đúng ô
	existing = find(values["department"], values["census_date"]) if values["census_date"] else None
	if name:
		doc = frappe.get_doc(DOCTYPE, name)
		if existing != doc.name:
			raise _duplicate(existing or doc.name, values["census_date"] or doc.census_date)
	elif existing and upsert:
		doc = frappe.get_doc(DOCTYPE, existing)
	elif existing:
		raise _duplicate(existing, values["census_date"])
	else:
		doc = frappe.new_doc(DOCTYPE)
	doc.update(values)
	doc.source = source
	if import_batch:
		doc.import_batch = import_batch
	doc.save(ignore_permissions=True)
	return doc


def as_dict(doc):
	if not doc:
		return None
	row = {field: doc.get(field) for field in OUT_FIELDS}
	row["census_date"] = str(getdate(row["census_date"]))
	row["locked"] = cint(row["locked"])
	return row


def get(department, census_date):
	name = find(department, census_date)
	return as_dict(frappe.get_doc(DOCTYPE, name)) if name else None


def prefill(department, census_date):
	"""Số của ngày trước đó gần nhất (điền sẵn — ux SCR-55 "điền sẵn giá trị hôm qua")."""
	rows = frappe.get_all(
		DOCTYPE,
		filters={"department": department, "census_date": ["<", getdate(census_date)]},
		fields=list(OUT_FIELDS),
		order_by="census_date desc",
		limit=1,
	)
	if not rows or getdate(rows[0].census_date) < getdate(add_days(census_date, -RECENT_DAYS)):
		return None
	return {field: rows[0].get(field) for field in COUNT_FIELDS}


def recent(department, until, days=RECENT_DAYS):
	"""Mẫu số các ngày (until - days, until], mới trước."""
	rows = frappe.get_all(
		DOCTYPE,
		filters={
			"department": department,
			"census_date": ["between", [add_days(until, -days + 1), getdate(until)]],
		},
		fields=list(OUT_FIELDS),
		order_by="census_date desc",
	)
	return [as_dict(row) for row in rows]


# --- khoa nội trú, mẫu số tỷ suất ---------------------------------------------------------------------------------


def inpatient_wards():
	return frappe.get_all(
		"Department",
		filters={"tc_inpatient": 1, "disabled": 0, "is_group": 0},
		fields=["name", "department_name"],
		order_by="department_name asc",
	)


def device_day_source(department):
	return frappe.db.get_value("Department", department, "tc_device_day_source") or SOURCE_CENSUS


def denominators(department, from_date, to_date):
	"""Ngày nằm viện (tổng số người bệnh của mẫu số) và ngày thiết bị trong [from, to] theo nguồn của khoa
	(FR-M13-04, A-141 b) — dữ liệu cho tỷ suất FEAT-063."""
	sums = frappe.get_all(
		DOCTYPE,
		filters={
			"department": department,
			"census_date": ["between", [getdate(from_date), getdate(to_date)]],
		},
		fields=[f"sum({field}) as {field}" for field in ("patient_count", *DEVICE_FIELDS)],
	)[0]
	source = device_day_source(department)
	if source == SOURCE_EPISODE:
		days = episodes.days_between(department, from_date, to_date)
		device = {field: days[device] for field, device in DEVICE_OF_FIELD.items()}
	else:
		device = {field: cint(sums.get(field)) for field in DEVICE_FIELDS}
	return {
		"source": source,
		"patient_days": cint(sums.get("patient_count")),
		"vent_days": device["vent_count"],
		"cvc_days": device["cvc_count"],
		"urinary_catheter_days": device["urinary_catheter_count"],
	}
