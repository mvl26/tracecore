"""Step gate engine (DT-STEPGATE, ADR-005): nơi DUY NHẤT đổi trạng thái và trường vòng đời của Set Unit.

Mỗi chu trình tái xử lý của một bộ (`Set Unit.current_cycle_no`) có tối đa năm cổng T1..T5, mỗi cổng là một
`Step Gate Result` tên ``{set_unit}-C{cycle_no}-{step}``. Cổng sau chỉ mở khi cổng liền trước Đạt; Không đạt
đưa bộ về Xử lý lại và đặt các cổng sau của chu trình về Chưa; đủ năm cổng Đạt thì bộ Vô khuẩn.

Trường vòng đời (`status`, `cycles_used`, `current_station`, `active_cycle_id`, `current_cycle_no`) được Set Unit
chặn ghi trừ khi có cờ ``doc.flags.tc_step_gate`` — cờ này chỉ được đặt trong file này (lint R2).
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tracecore.core.errors import Block

STEPS = ("T1", "T2", "T3", "T4", "T5")
# Trạng thái Set Unit mà trạm chấp nhận; bước khác bổ sung ở FEAT của bước đó.
STATION_STATUSES = {"T4": ("Processing", "Reprocess")}

PENDING = "Pending"
RESULTS = ("Pass", "Fail")


def result_name(set_unit, cycle_no, step):
	"""Tên Step Gate Result: duy nhất theo (bộ, chu trình, bước)."""
	return f"{set_unit}-C{cycle_no}-{step}"


def _check_step(step):
	if step not in STEPS:
		frappe.throw(_("Unknown step {0}.").format(step))


def _set_unit(set_unit, for_update=False):
	"""Set Unit; for_update khóa dòng để hai request ghi cổng cho cùng bộ chạy lần lượt."""
	return frappe.get_doc("Set Unit", set_unit, for_update=for_update)


def _state(set_unit):
	"""(status, current_cycle_no) của bộ; bộ không có → DoesNotExistError."""
	row = frappe.db.get_value("Set Unit", set_unit, ["status", "current_cycle_no"])
	if not row:
		frappe.throw(_("Set Unit {0} not found.").format(set_unit), frappe.DoesNotExistError)
	return row[0], cint(row[1])


def _require_cycle(set_unit, cycle_no):
	if not cycle_no:
		frappe.throw(_("No cycle has been started for Set Unit {0}.").format(set_unit))
	return cycle_no


def _save_lifecycle(unit, **fields):
	for fieldname, value in fields.items():
		unit.set(fieldname, value)
	unit.flags.tc_step_gate = True
	unit.save(ignore_permissions=True)


def _results(set_unit, cycle_no):
	"""{bước: (result, redo_count)} của chu trình; bước chưa có dòng thì vắng mặt."""
	rows = frappe.get_all(
		"Step Gate Result",
		filters={"set_unit": set_unit, "cycle_no": cycle_no},
		fields=["step", "result", "redo_count"],
	)
	return {row.step: (row.result, cint(row.redo_count)) for row in rows}


def start_cycle(set_unit):
	"""Mở chu trình mới (stub của T1): ``current_cycle_no + 1``, Set Unit sang Processing, bỏ Cycle ID cũ."""
	unit = _set_unit(set_unit, for_update=True)
	cycle_no = cint(unit.current_cycle_no) + 1
	_save_lifecycle(unit, current_cycle_no=cycle_no, status="Processing", active_cycle_id=None)
	return cycle_no


def check(set_unit, step):
	"""Lý do chặn bộ vào bước `step`, hoặc None nếu được vào (FR-M2-00.1, FR-M2-25, BRU-FLOW-002/004).

	Thứ tự: trạng thái Set Unit hợp với trạm → cổng liền trước của chu trình hiện hành phải Đạt.
	"""
	_check_step(step)
	status, cycle_no = _state(set_unit)
	allowed = STATION_STATUSES.get(step)
	if allowed and status not in allowed:
		return Block(
			"STATUS_INVALID_FOR_STATION",
			_("Set status does not match this station"),
			_("Set {0} is {1}; station {2} accepts only sets that are {3}.").format(
				set_unit,
				_(status, context="Set Unit"),
				step,
				", ".join(_(s, context="Set Unit") for s in allowed),
			),
			_("Check the set status, then take the set to the station that matches it."),
		)
	index = STEPS.index(step)
	if index == 0:
		return None
	previous = STEPS[index - 1]
	result = _results(set_unit, cycle_no).get(previous, (PENDING, 0))[0]
	if result != "Pass":
		return Block(
			"GATE_PREV_NOT_PASSED",
			_("Previous step has not passed"),
			_("Step {0} has not passed in cycle {1}.").format(previous, cycle_no),
			_("Send the set back to step {0} and complete it before continuing.").format(previous),
			redo_step=previous,
		)
	return None


def record(set_unit, step, result, ref_doctype=None, ref_name=None, station=None):
	"""Ghi kết quả một cổng của chu trình hiện hành; trả tên Step Gate Result.

	Upsert theo tên ``{set_unit}-C{cycle_no}-{step}``. Không đạt: ``redo_count + 1``, các bước sau đã có kết quả
	về Chưa (giữ dòng và ``redo_count``), bộ sang Reprocess. Đạt khi bộ đang Reprocess: về Processing. Đủ năm
	cổng Đạt: Sterile.
	"""
	_check_step(step)
	if result not in RESULTS:
		frappe.throw(_("Invalid gate result: {0}").format(result))
	unit = _set_unit(set_unit, for_update=True)
	cycle_no = _require_cycle(unit.name, cint(unit.current_cycle_no))

	name = result_name(unit.name, cycle_no, step)
	exists = frappe.db.exists("Step Gate Result", name)
	row = (
		frappe.get_doc("Step Gate Result", name)
		if exists
		else frappe.get_doc(
			{
				"doctype": "Step Gate Result",
				"set_unit": unit.name,
				"cycle_no": cycle_no,
				"step": step,
				"redo_count": 0,
			}
		)
	)
	if result == "Fail":
		row.redo_count = cint(row.redo_count) + 1
	row.update(
		{
			"result": result,
			"ref_doctype": ref_doctype,
			"ref_name": ref_name,
			"station": station,
			"recorded_by": frappe.session.user,
			"recorded_at": now_datetime(),
		}
	)
	if exists:
		row.save(ignore_permissions=True)
	else:
		row.insert(ignore_permissions=True)

	if result == "Fail":
		_reset_later_steps(unit.name, cycle_no, step)
	_update_status(unit, cycle_no, result)
	return row.name


def _reset_later_steps(set_unit, cycle_no, step):
	later = STEPS[STEPS.index(step) + 1 :]
	names = frappe.get_all(
		"Step Gate Result",
		filters={
			"set_unit": set_unit,
			"cycle_no": cycle_no,
			"step": ("in", later),
			"result": ("!=", PENDING),
		},
		pluck="name",
		order_by="step",
	)
	for name in names:
		stale = frappe.get_doc("Step Gate Result", name)
		stale.result = PENDING
		stale.save(ignore_permissions=True)


def _update_status(unit, cycle_no, result):
	results = _results(unit.name, cycle_no)
	if all(results.get(step, (PENDING, 0))[0] == "Pass" for step in STEPS):
		status = "Sterile"
	elif result == "Fail":
		status = "Reprocess"
	elif unit.status == "Reprocess":
		status = "Processing"
	else:
		status = unit.status
	if status != unit.status:
		_save_lifecycle(unit, status=status)


def gates(set_unit):
	"""Kết quả năm cổng của chu trình hiện hành: ``[{"step", "result", "redo_count"}]``, thiếu = Pending."""
	_status, cycle_no = _state(set_unit)
	results = _results(set_unit, _require_cycle(set_unit, cycle_no))
	return [
		{"step": step, "result": results[step][0], "redo_count": results[step][1]}
		if step in results
		else {"step": step, "result": PENDING, "redo_count": 0}
		for step in STEPS
	]


def bind_cycle(set_unit, cycle_id, station):
	"""Gắn Cycle ID hiện hành (và trạm, nếu có) vào bộ; `station` None thì giữ trạm hiện tại."""
	if not cycle_id:
		frappe.throw(_("Cycle ID is required."))
	unit = _set_unit(set_unit, for_update=True)
	_require_cycle(unit.name, cint(unit.current_cycle_no))
	fields = {"active_cycle_id": cycle_id}
	if station:
		fields["current_station"] = station
	_save_lifecycle(unit, **fields)


def release_cycle(set_unit):
	"""Bỏ Cycle ID hiện hành của bộ (hủy mã); giữ trạm hiện tại. Không có Cycle ID thì không làm gì."""
	unit = _set_unit(set_unit, for_update=True)
	if unit.active_cycle_id:
		_save_lifecycle(unit, active_cycle_id=None)
