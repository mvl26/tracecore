"""Dữ liệu chu trình tự động từ station agent (FEAT-024, A-39, ADR-007; FR-M2-24, EI-SW-001, UC-06 bước 4, UC-09 A3).

Agent đọc CSV/API của máy kết nối được và gửi từng chu trình. Server gắn chu trình vào lô rửa / mẻ tiệt khuẩn còn mở
của đúng máy: theo mã lô/mẻ đặt làm tên chu trình trên máy (khớp chính xác), không có thì theo giờ bắt đầu ±30 phút
(khớp mờ → Cần xem xét). Tham số đánh giá theo `Program Parameter` như nhập tay; thiếu → chưa đủ dữ liệu, người vận
hành chuyển nhập tay có lý do (FR-M2-10.4). Không khớp → từ chối, không lưu: agent giữ chu trình và gửi lại.
"""

import json
from datetime import timedelta, timezone

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, get_datetime

from tracecore.core import client_time
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import sterilizing, washing

MATCH_WINDOW = timedelta(minutes=30)
WASH = "Wash Batch"
LOAD = "Sterilization Load"
RESULTS = ("Pass", "Fail")
# trạng thái chứng từ còn nhận dữ liệu máy
OPEN_STATUSES = {WASH: ("Running",), LOAD: ("Running", sterilizing.CYCLE_COMPLETE)}
MISSING_ENDED_AT = "ended_at"


def _blocked(code, title, reason, action, items=None):
	return BlockedError(Block(code, title, reason, action, items=items))


def _doctype_of(equipment_type):
	if equipment_type in washing.WASH_EQUIPMENT_TYPES:
		return WASH
	if equipment_type in sterilizing.STERILIZER_TYPES:
		return LOAD
	return None


def _machine(station, equipment):
	row = frappe.db.get_value(
		"Equipment",
		equipment,
		["name", "equipment_type", "is_connected", "zone_in", "zone_out"],
		as_dict=True,
	)
	doctype = _doctype_of(row.equipment_type) if row else None
	if not row or not doctype:
		raise _blocked(
			"EQUIPMENT_NOT_FOUND",
			_("Machine not found"),
			_("Equipment {0} is not a washer or a sterilizer.").format(equipment or "-"),
			_("Check the machine code in the agent configuration."),
		)
	if not cint(row.is_connected):
		raise _blocked(
			"MACHINE_NOT_CONNECTED",
			_("Machine is not connected"),
			_("Equipment {0} is not declared as a connected machine.").format(row.name),
			_("Ask R10 to mark the machine as connected, or enter the cycle data by hand."),
		)
	zone = frappe.db.get_value("Zone Station", station, "parent_zone")
	if not zone or zone not in (row.zone_in, row.zone_out):
		raise _blocked(
			"MACHINE_NOT_AT_STATION",
			_("Machine is not at this station"),
			_("Equipment {0} is not in the zone of station {1}.").format(row.name, station),
			_("Configure the machine on the agent of a station in the same zone."),
		)
	return row, doctype


def _cycle(value):
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			value = None
	if not isinstance(value, dict) or not cstr(value.get("cycle_ref")).strip():
		frappe.throw(_("Machine cycle must be an object with a cycle_ref."))
	return value


def _machine_time(value):
	"""Giờ máy (ISO, có hoặc không múi giờ) → giờ hệ thống không múi giờ; sai định dạng → None."""
	if not value:
		return None
	try:
		moment = get_datetime(value)
	except Exception:
		return None
	if moment is None:
		return None
	if moment.tzinfo:
		return client_time.to_system_time(moment.astimezone(timezone.utc).replace(tzinfo=None))
	return moment


def _open_docs(doctype, equipment):
	return frappe.get_all(
		doctype,
		filters={"equipment": equipment, "status": ("in", OPEN_STATUSES[doctype]), "docstatus": ("<", 2)},
		fields=["name", "started_at"],
	)


def _match(doctype, equipment, cycle, started):
	"""(tên chứng từ, cách khớp): ``load_id`` trùng → chính xác; không thì giờ bắt đầu ±30 phút → mờ."""
	candidates = _open_docs(doctype, equipment)
	load_id = cstr(cycle.get("load_id")).strip().upper()
	for row in candidates:
		if load_id and row.name.upper() == load_id:
			return row.name, "load_id"
	if started:
		near = [
			row
			for row in candidates
			if row.started_at and abs(get_datetime(row.started_at) - started) <= MATCH_WINDOW
		]
		if near:
			near.sort(key=lambda row: abs(get_datetime(row.started_at) - started))
			return near[0].name, "time"
	raise _blocked(
		"MACHINE_CYCLE_UNMATCHED",
		_("Machine cycle not matched"),
		_("Cycle {0} of equipment {1} matches no open batch or load.").format(
			cycle.get("cycle_ref"), equipment
		),
		_(
			"Name the cycle on the machine with the batch or load code; the agent sends the cycle again later."
		),
	)


def _parameters(program, given_rows):
	"""(tham số đã đánh giá, tham số bắt buộc thiếu, có giá trị ngoài dải) theo `Program Parameter`."""
	given = {}
	for row in given_rows or []:
		if isinstance(row, dict) and row.get("parameter_name"):
			given[cstr(row["parameter_name"]).strip()] = row.get("value")
	parameters, missing, review = [], [], False
	for schema in washing._parameters(program):
		value = washing._number(given.get(schema.parameter_name))
		if value is None:
			if cint(schema.required):
				missing.append(schema.parameter_name)
			continue
		outside = washing._outside(value, schema.min_value, schema.max_value)
		review = review or outside
		parameters.append(
			{
				"parameter_name": schema.parameter_name,
				"unit": schema.unit,
				"value": value,
				"min_value": flt(schema.min_value),
				"max_value": flt(schema.max_value),
				"outside_range": outside,
			}
		)
	return parameters, missing, review


def _previous(doc, doctype, cycle_ref):
	"""Kết quả lần gửi trước cùng ``cycle_ref`` (agent gửi lại) hoặc None."""
	if doc.data_source != "Auto":
		return None
	raw = doc.machine_data if doctype == WASH else doc.machine_alerts
	data = frappe.parse_json(raw) if raw else {}
	source = (data or {}).get("source") or {}
	if source.get("cycle_ref") != cycle_ref:
		return None
	return {
		"doctype": doctype,
		"name": doc.name,
		"matched_by": source.get("matched_by"),
		"data_complete": cint(doc.data_complete),
		"needs_review": cint(doc.needs_review),
		"missing": (data or {}).get("missing") or [],
		"duplicate": True,
	}


def ingest(station, equipment, cycle):
	"""Gắn một chu trình máy vào lô/mẻ mở; trả ``{doctype, name, matched_by, data_complete, needs_review, missing,
	duplicate}``. Từ chối: EQUIPMENT_NOT_FOUND, MACHINE_NOT_CONNECTED, MACHINE_NOT_AT_STATION, MACHINE_CYCLE_UNMATCHED,
	MACHINE_DATA_EXISTS (đã có dữ liệu nhập tay đủ)."""
	cycle = _cycle(cycle)
	machine, doctype = _machine(station, equipment)
	cycle_ref = cstr(cycle["cycle_ref"]).strip()
	started = _machine_time(cycle.get("started_at"))
	name, matched_by = _match(doctype, machine.name, cycle, started)
	doc = frappe.get_doc(doctype, name, for_update=True)
	previous = _previous(doc, doctype, cycle_ref)
	if previous:
		return previous
	if doc.data_source == "Manual" and cint(doc.data_complete):
		raise _blocked(
			"MACHINE_DATA_EXISTS",
			_("Cycle data already entered"),
			_("{0} {1} already has confirmed cycle data entered by hand.").format(_(doctype), doc.name),
			_("Keep the manual data; check the machine cycle with R02 if it differs."),
		)
	parameters, missing, review = _parameters(doc.program, cycle.get("parameters"))
	ended = _machine_time(cycle.get("ended_at"))
	started = started or get_datetime(doc.started_at)
	if not ended or ended < started:
		missing.append(MISSING_ENDED_AT)
	review = review or matched_by == "time"
	alerts = [cstr(text) for text in cycle.get("alerts") or [] if cstr(text).strip()]
	result = cycle.get("result") if cycle.get("result") in RESULTS else None
	source = {"driver": cycle.get("driver"), "cycle_ref": cycle_ref, "matched_by": matched_by}
	complete = 0 if missing else 1
	common = {
		"started_at": started,
		"ended_at": ended,
		"data_source": "Auto",
		"data_complete": complete,
		"needs_review": 1 if review else 0,
		"manual_confirmed_by": None,
		"manual_confirmed_at": None,
	}
	if doctype == WASH:
		doc.update(
			{
				**common,
				"machine_data": frappe.as_json(
					{
						"parameters": parameters,
						"alerts": alerts or None,
						"reported_result": result,
						"missing": missing,
						"source": source,
					}
				),
			}
		)
		doc.flags.tc_washing = True
	else:
		doc.update(
			{
				**common,
				"params": frappe.as_json(parameters),
				# `text` như nhập tay để màn T5/T5b hiện cảnh báo máy (FR-M2-24.4)
				"machine_alerts": frappe.as_json(
					{"text": "; ".join(alerts) or None, "items": alerts, "missing": missing, "source": source}
				),
				"manual_reason": None,
			}
		)
		if complete:
			doc.status = sterilizing.CYCLE_COMPLETE
			if result:
				doc.update({"cycle_result": result, "result_source": "Auto"})
		doc.flags.tc_sterilizing = True
	doc.save(ignore_permissions=True)
	return {
		"doctype": doctype,
		"name": doc.name,
		"matched_by": matched_by,
		"data_complete": complete,
		"needs_review": cint(doc.needs_review),
		"missing": missing,
		"duplicate": False,
	}
