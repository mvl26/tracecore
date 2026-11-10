"""RPC tracecore.v1.hai.* — mẫu số ngày và đợt thiết bị (FEAT-062; FR-M13-02, FR-M13-04, FR-M12-07; UC-47; SCR-55;
NFR-AVAIL-05, NFR-SEC-09; ADR-003, ADR-010; A-141 f).

- Trạm/PDA (Station Function ``CENSUS``): ``context`` (POST, cũng là snapshot đọc offline), ``census_upsert`` và
  ``device_episode`` (POST, phiên thẻ, ``@idempotent``, phát lại offline ``X-TC-Replay``).
- Cổng khoa (đăng nhập): ``portal_context`` (GET), ``census_upsert_portal``, ``device_episode_portal`` (POST,
  ``@idempotent``). R08/R12 chỉ khoa có User Permission Department; R01, R11 mọi khoa nội trú.

Từ chối nghiệp vụ trả body ``{"ok": false, "error": {...}}`` (``reject_block``). Response chỉ chứa mã người bệnh che
(Idempotency Key lưu response; `Sync Conflict` bỏ ``patient_code``). PDA có khóa công khai của site gửi
``patient_code_enc`` thay mã rõ (như báo phơi nhiễm, FEAT-071).
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate

from tracecore.core import crypto
from tracecore.core.client_time import parse_client_ts, to_system_time
from tracecore.core.errors import Block, BlockedError
from tracecore.core.idempotency import idempotent
from tracecore.hai_surveillance import census, episodes, permissions
from tracecore.v1._common import BadRequestError, reject_block, require_any_role, run_at_step, station_session

FUNCTION = "CENSUS"
# tham số RPC `census` (tên bản ghi) che tên module trong thân hàm: dùng hằng này
CENSUS_DOCTYPE = census.DOCTYPE
STATION_ROLES = ("TC R01", "TC R08", "TC R11", "TC R12", "System Manager")
PORTAL_ROLES = STATION_ROLES
ACTIONS = ("open", "close")


def _on(timestamp):
	return getdate(to_system_time(timestamp))


def _int(value, name):
	if value in (None, ""):
		return None
	try:
		return int(value)
	except (TypeError, ValueError):
		raise BadRequestError(_("{0} must be a whole number.").format(name)) from None


def _departments():
	"""Khoa người gọi được thấy: R08/R12 theo User Permission; vai trò rộng → khoa nội trú."""
	allowed = permissions.allowed_departments()
	if allowed is None:
		return [{"name": row.name, "label": row.department_name or row.name} for row in census.inpatient_wards()]
	rows = frappe.get_all(
		"Department",
		filters={"name": ["in", allowed or [""]], "disabled": 0},
		fields=["name", "department_name"],
		order_by="department_name asc",
	)
	return [{"name": row.name, "label": row.department_name or row.name} for row in rows]


def _view(department, census_date, on):
	"""Dữ liệu SCR-55 cho một khoa: mẫu số ngày chọn, điền sẵn, 7 ngày gần nhất, đợt đang mở + gói hôm nay."""
	departments = _departments()
	names = [row["name"] for row in departments]
	if department and department not in names:
		raise frappe.PermissionError(_("You cannot open the census of this department."))
	department = department or (names[0] if names else None)
	census_date = getdate(census_date) if census_date else getdate(add_days(on, -1))
	current = census.get(department, census_date) if department else None
	return {
		"ok": True,
		"departments": departments,
		"department": department,
		"census_date": str(census_date),
		"today": str(getdate(on)),
		"census": current,
		"missing": bool(department) and current is None and census_date < getdate(on),
		"prefill": census.prefill(department, census_date) if department and not current else None,
		"recent": census.recent(department, getdate(on)) if department else [],
		"episodes": episodes.open_list([department], on) if department else [],
		"device_types": list(episodes.DEVICE_TYPES),
		"device_day_source": census.device_day_source(department) if department else None,
	}


def _census_values(department, census_date, patient_count, vent_count, cvc_count, urinary_catheter_count, admissions):
	return {
		"department": department,
		"census_date": census_date,
		"patient_count": _int(patient_count, "patient_count"),
		"vent_count": _int(vent_count, "vent_count"),
		"cvc_count": _int(cvc_count, "cvc_count"),
		"urinary_catheter_count": _int(urinary_catheter_count, "urinary_catheter_count"),
		"admissions": _int(admissions, "admissions"),
	}


def _save_census(values, name):
	permissions.require_department(values["department"])
	if name:
		permissions.require_department(frappe.db.get_value(census.DOCTYPE, name, "department"))
	doc = census.save(values, source=census.MANUAL, name=name or None)
	return {"ok": True, "census": census.as_dict(doc)}


def _decrypt(enc):
	try:
		return crypto.decrypt_patient_code(enc)
	except ValueError:
		raise BlockedError(
			Block(
				"PATIENT_CODE_UNREADABLE",
				_("Patient code cannot be read"),
				_("The encrypted patient code from the PDA could not be decrypted."),
				_("Enter the patient code again."),
			)
		) from None


def _episode(action, values, episode, removed_on, on):
	if action not in ACTIONS:
		raise BlockedError(
			Block(
				"DEVICE_EPISODE_TYPE_INVALID",
				_("Action not valid"),
				_("Device episode action must be open or close."),
				_("Choose Open episode or Close episode."),
			)
		)
	if action == "open":
		permissions.require_department(values.get("department"))
		doc = episodes.open_episode(values)
	else:
		department = frappe.db.get_value(episodes.DOCTYPE, episode, "department") if episode else None
		permissions.require_department(department)
		doc = episodes.close_episode(episode, removed_on)
	return {"ok": True, "episode": episodes.as_dict(doc, on)}


def _episode_values(department, device_type, code, birth_year, sex, inserted_on):
	return {
		"department": department,
		"device_type": device_type,
		"patient_code": (code or "").strip()[:64] or None,
		"birth_year": _int(birth_year, "birth_year"),
		"sex": sex or None,
		"inserted_on": inserted_on,
	}


# --- trạm / PDA ---------------------------------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*STATION_ROLES)
def context(station, department=None, census_date=None, client_ts=None, token=None):
	"""Dữ liệu SCR-55 PDA (cũng là snapshot đọc offline của trạm)."""
	require_any_role(*STATION_ROLES)
	timestamp = parse_client_ts(client_ts)
	return run_at_step(FUNCTION, station, timestamp, lambda: _view(department, census_date, _on(timestamp)))


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*STATION_ROLES, offline=True)
@idempotent
def census_upsert(
	station,
	department=None,
	census_date=None,
	patient_count=None,
	vent_count=None,
	cvc_count=None,
	urinary_catheter_count=None,
	admissions=None,
	census=None,
	client_ts=None,
	token=None,
):
	"""Ghi mẫu số ngày từ PDA (FR-M13-02); trùng (ngày, khoa) khi phát lại → từ chối, `Sync Conflict` giữ bản server."""
	require_any_role(*STATION_ROLES)
	timestamp = parse_client_ts(client_ts)
	values = _census_values(
		department, census_date, patient_count, vent_count, cvc_count, urinary_catheter_count, admissions
	)
	return run_at_step(
		FUNCTION, station, timestamp, lambda: _save_census(values, census), CENSUS_DOCTYPE, census
	)


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session(*STATION_ROLES, offline=True)
@idempotent
def device_episode(
	station,
	action=None,
	department=None,
	device_type=None,
	patient_code=None,
	patient_code_enc=None,
	birth_year=None,
	sex=None,
	inserted_on=None,
	episode=None,
	removed_on=None,
	client_ts=None,
	token=None,
):
	"""Mở/đóng đợt thiết bị từ PDA (FR-M13-04)."""
	require_any_role(*STATION_ROLES)
	timestamp = parse_client_ts(client_ts)

	def call():
		code = _decrypt(patient_code_enc) if patient_code_enc else patient_code
		values = _episode_values(department, device_type, code, birth_year, sex, inserted_on)
		return _episode(action, values, episode, removed_on, _on(timestamp))

	return run_at_step(FUNCTION, station, timestamp, call, episodes.DOCTYPE, episode)


# --- Cổng khoa ----------------------------------------------------------------------------------------------------


def _require_portal():
	if frappe.session.user == "Guest":
		raise frappe.PermissionError(_("Sign in to enter the daily census."))
	require_any_role(*PORTAL_ROLES)


@frappe.whitelist(methods=["GET"])
def portal_context(department=None, census_date=None):
	"""Dữ liệu trang Cổng khoa `/ksnk-khoa/mau-so` (SCR-55 DEPT)."""
	_require_portal()
	return _view(department, census_date, getdate())


@frappe.whitelist(methods=["POST"])
@idempotent
def census_upsert_portal(
	department=None,
	census_date=None,
	patient_count=None,
	vent_count=None,
	cvc_count=None,
	urinary_catheter_count=None,
	admissions=None,
	census=None,
	client_ts=None,
):
	_require_portal()
	timestamp = parse_client_ts(client_ts)
	values = _census_values(
		department, census_date, patient_count, vent_count, cvc_count, urinary_catheter_count, admissions
	)
	try:
		return _save_census(values, census)
	except BlockedError as error:
		return reject_block(error.block, CENSUS_DOCTYPE, census, client_ts=timestamp)


@frappe.whitelist(methods=["POST"])
@idempotent
def device_episode_portal(
	action=None,
	department=None,
	device_type=None,
	patient_code=None,
	birth_year=None,
	sex=None,
	inserted_on=None,
	episode=None,
	removed_on=None,
	client_ts=None,
):
	_require_portal()
	timestamp = parse_client_ts(client_ts)
	values = _episode_values(department, device_type, patient_code, birth_year, sex, inserted_on)
	try:
		return _episode(action, values, episode, removed_on, getdate())
	except BlockedError as error:
		return reject_block(error.block, episodes.DOCTYPE, episode, client_ts=timestamp)

