"""Step gate engine (DT-STEPGATE, ADR-005): nơi DUY NHẤT đổi trạng thái và trường vòng đời của Set Unit.

Mỗi chu trình tái xử lý của một bộ (`Set Unit.current_cycle_no`) có tối đa năm cổng T1..T5, mỗi cổng là một
`Step Gate Result` tên ``{set_unit}-C{cycle_no}-{step}``. Cổng sau chỉ mở khi cổng liền trước Đạt; Không đạt
đưa bộ về Xử lý lại và đặt các cổng sau của chu trình về Chưa; đủ năm cổng Đạt thì bộ Vô khuẩn.

Trường vòng đời (`status`, `cycles_used`, `current_station`, `active_cycle_id`, `current_cycle_no`,
`cycle_bom_version`) được Set Unit chặn ghi trừ khi có cờ ``doc.flags.tc_step_gate`` — cờ này chỉ được đặt trong file
này (lint R2). `cycle_bom_version` (phiên bản BOM ghim cho chu trình, FEAT-015 S3) do ``start_cycle`` hỏi M1 qua hook
``tracecore_cycle_bom_version`` (core không import M1, ADR-001).

Đồng thời: các hàm ghi khóa dòng Set Unit (``FOR UPDATE``) nên request song song cùng bộ chạy lần lượt. MariaDB
chạy REPEATABLE READ: đọc thường dùng snapshot mở từ lần đọc đầu của transaction (trên đường RPC là
``@idempotent``), không thấy dòng request kia vừa commit. Vì vậy mọi thứ ``record`` dựa vào để quyết định (Set Unit,
dòng cổng, kết quả cả chu trình) đều đọc có khóa. Đọc có khóa theo TỪNG khóa chính (``name = …``), không dùng
``IN (…)`` hay lọc theo cột không chỉ mục: các dạng đó khóa khoảng hoặc cả bảng và làm hai bộ khác nhau chặn hoặc
deadlock lẫn nhau. ``gates`` và ``check`` mặc định chỉ để hiển thị/kiểm nhanh nên đọc thường; nơi kiểm rồi ghi ngay
trong cùng transaction (``packing.generate``) gọi ``check(…, for_update=True)`` sau khi đã khóa Set Unit.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tracecore.core import extension
from tracecore.core.errors import Block

STEPS = ("T1", "T2", "T3", "T4", "T5")
# Trạng thái Set Unit mà trạm chấp nhận; bước khác bổ sung ở FEAT của bước đó.
STATION_STATUSES = {"T2": ("Processing", "Reprocess"), "T4": ("Processing", "Reprocess")}

PENDING = "Pending"
RESULTS = ("Pass", "Fail")
END_OF_LIFE = "End of Life"
NOT_RETIRABLE = ("Disposed",)  # bộ đã thanh lý không quay lại Hết vòng đời


def result_name(set_unit, cycle_no, step):
	"""Tên Step Gate Result: duy nhất theo (bộ, chu trình, bước)."""
	return f"{set_unit}-C{cycle_no}-{step}"


def _check_step(step):
	if step not in STEPS:
		frappe.throw(_("Unknown step {0}.").format(step))


def _set_unit(set_unit, for_update=False):
	"""Set Unit; for_update khóa dòng để hai request ghi cổng cho cùng bộ chạy lần lượt."""
	return frappe.get_doc("Set Unit", set_unit, for_update=for_update)


def _state(set_unit, for_update=False):
	"""(status, current_cycle_no) của bộ; bộ không có → DoesNotExistError. for_update: đọc có khóa."""
	row = frappe.db.get_value("Set Unit", set_unit, ["status", "current_cycle_no"], for_update=for_update)
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


def _results(set_unit, cycle_no, for_update=False):
	"""{bước: (result, redo_count)} của chu trình; bước chưa có dòng thì vắng mặt.

	for_update: đọc có khóa từng dòng theo khóa chính (xem docstring module) để thấy bản mới nhất đã commit.
	"""
	if for_update:
		results = {}
		for step in STEPS:
			row = frappe.db.get_value(
				"Step Gate Result",
				result_name(set_unit, cycle_no, step),
				["result", "redo_count"],
				for_update=True,
			)
			if row:
				results[step] = (row[0], cint(row[1]))
		return results
	rows = frappe.get_all(
		"Step Gate Result",
		filters={"set_unit": set_unit, "cycle_no": cycle_no},
		fields=["step", "result", "redo_count"],
	)
	return {row.step: (row.result, cint(row.redo_count)) for row in rows}


CYCLE_BOM_VERSION_HOOK = "tracecore_cycle_bom_version"


def _first_int(results):
	"""Số nguyên đầu tiên trong kết quả hook (bỏ bool và kiểu khác); không có → 0 (không ghim)."""
	for value in results:
		if isinstance(value, int) and not isinstance(value, bool):
			return value
	return 0


def start_cycle(set_unit, on=None):
	"""Mở chu trình mới (stub của T1): ``current_cycle_no + 1``, Set Unit sang Processing, bỏ Cycle ID cũ.

	Ghim phiên bản BOM của chu trình (FR-M1-04.1, .2; FEAT-015 S3): hook ``tracecore_cycle_bom_version`` nhận
	``{"set_unit", "set_type", "cycle_no", "on"}`` và trả phiên bản; số nguyên đầu tiên được ghi vào
	``cycle_bom_version`` trong CÙNG lần lưu với ``current_cycle_no``/``status``. Ghim giữ nguyên sau khi bộ được giải
	phóng, tới lần tiếp nhận kế tiếp. Không có hook hoặc hook trả None → 0 (không ghim; nơi đọc dùng phiên bản hiệu lực).

	**Hợp đồng của `on`:** ngày/giờ tiếp nhận theo **giờ hệ thống** (``Asia/Ho_Chi_Minh``) không múi giờ, như
	``now_datetime()`` (mặc định). Nơi gọi có ``client_ts`` (``client_time.parse_client_ts`` trả UTC không múi giờ) phải
	đổi bằng ``client_time.to_system_time`` trước khi truyền (FEAT-019), nếu không bộ tiếp nhận từ 00:00 tới 06:59 giờ
	Việt Nam bị ghim phiên bản của ngày hôm trước.
	"""
	unit = _set_unit(set_unit, for_update=True)
	cycle_no = cint(unit.current_cycle_no) + 1
	ctx = {
		"set_unit": unit.name,
		"set_type": unit.set_type,
		"cycle_no": cycle_no,
		"on": on or now_datetime(),
	}
	version = _first_int(extension.run(CYCLE_BOM_VERSION_HOOK, ctx))
	_save_lifecycle(
		unit,
		current_cycle_no=cycle_no,
		status="Processing",
		active_cycle_id=None,
		cycle_bom_version=version,
	)
	return cycle_no


def check(set_unit, step, for_update=False):
	"""Lý do chặn bộ vào bước `step`, hoặc None nếu được vào (FR-M2-00.1, FR-M2-25, BRU-FLOW-002/004).

	Thứ tự: trạng thái Set Unit hợp với trạm → cổng liền trước của chu trình hiện hành phải Đạt.
	for_update: đọc Set Unit và các dòng cổng có khóa (theo khóa chính) để thấy bản mới nhất đã commit — dùng khi
	nơi gọi đã khóa Set Unit và sẽ ghi ngay sau đó (snapshot REPEATABLE READ có thể cũ, xem docstring module).
	"""
	_check_step(step)
	status, cycle_no = _state(set_unit, for_update)
	if status == END_OF_LIFE:  # FEAT-032, FR-M2-18.1: Hết vòng đời bị chặn ở mọi bước
		return Block(
			"SET_END_OF_LIFE",
			_("Set has reached the end of its life"),
			_("Set {0} has used up its reprocessing cycles and is waiting for disposal.").format(set_unit),
			_("Do not use this set. Ask R01 for an override or take it out of circulation."),
		)
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
	result = _results(set_unit, cycle_no, for_update).get(previous, (PENDING, 0))[0]
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
	# Đọc có khóa: request song song cùng bộ có thể vừa commit dòng này mà snapshot của ta chưa thấy
	exists = frappe.db.get_value("Step Gate Result", name, "name", for_update=True)
	row = (
		frappe.get_doc("Step Gate Result", name, for_update=True)
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

	# Đọc có khóa cả năm dòng SAU khi đã ghi dòng của mình: sau điểm này chỉ còn UPDATE dòng đã khóa, không còn
	# INSERT nào có thể phải chờ khóa khoảng của request khác
	results = _results(unit.name, cycle_no, for_update=True)
	if result == "Fail":
		_reset_later_steps(unit.name, cycle_no, step, results)
	_update_status(unit, results, result)
	return row.name


def _reset_later_steps(set_unit, cycle_no, step, results):
	"""Đưa các bước sau `step` đã có kết quả về Pending; cập nhật luôn `results` (đã đọc có khóa)."""
	for later in STEPS[STEPS.index(step) + 1 :]:
		current = results.get(later)
		if current and current[0] != PENDING:
			stale = frappe.get_doc(
				"Step Gate Result", result_name(set_unit, cycle_no, later), for_update=True
			)
			stale.result = PENDING
			stale.save(ignore_permissions=True)
			results[later] = (PENDING, current[1])


def _update_status(unit, results, result):
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


def check_stored(set_unit):
	"""Lý do chặn nhập kho vô khuẩn (cổng T6 kiểm, UC-11 E1, BRU-FLOW-004), hoặc None nếu bộ đủ năm cổng Đạt.

	Chỉ đọc, không ghi hàng `Step Gate Result` T6. `items` là các bước chưa Đạt của chu trình hiện hành (bộ chưa
	có chu trình: cả năm bước); `redo_step` là bước đầu tiên còn thiếu.
	"""
	_status, cycle_no = _state(set_unit)
	results = _results(set_unit, cycle_no) if cycle_no else {}
	missing = [step for step in STEPS if results.get(step, (PENDING, 0))[0] != "Pass"]
	if not missing:
		return None
	return Block(
		"GATE_PREV_NOT_PASSED",
		_("Set is not sterile yet"),
		_("Set {0} has not passed step(s) {1}.").format(set_unit, ", ".join(missing)),
		_("Send the set back to step {0} and complete it before storing the pack.").format(missing[0]),
		items=missing,
		redo_step=missing[0],
	)


def end_of_life(set_unit, reason=None):
	"""Bộ đã dùng hết cơ số: sang Hết vòng đời, chờ thanh lý, bỏ Cycle ID hiện hành (FEAT-032, FR-M8-03.2).

	Trả True khi vừa chuyển; đã Hết vòng đời thì False và không ghi gì. Bộ đã thanh lý → lỗi. `reason` đi vào
	cột lý do của Audit Log (mặc định None). Giữ nguyên chu trình và các cổng của chu trình hiện hành.
	"""
	unit = _set_unit(set_unit, for_update=True)
	if unit.status == END_OF_LIFE:
		return False
	if unit.status in NOT_RETIRABLE:
		frappe.throw(
			_("Set {0} is {1}; it cannot be moved to end of life.").format(
				unit.name, _(unit.status, context="Set Unit")
			)
		)
	unit.flags.tc_audit_reason = reason
	_save_lifecycle(unit, status=END_OF_LIFE, active_cycle_id=None)
	return True


def reopen_after_override(set_unit, override):
	"""Ghi đè cơ số được duyệt: bộ Hết vòng đời quay lại Processing để đóng gói tiếp (A-18 Q4).

	`override` (tên Par Override) đi vào lý do của Audit Log. Trạng thái khác Hết vòng đời → lỗi, không ghi gì.
	Các cổng của chu trình hiện hành giữ nguyên nên bộ quay lại T4 ngay.
	"""
	unit = _set_unit(set_unit, for_update=True)
	if unit.status != END_OF_LIFE:
		frappe.throw(
			_("Set {0} is {1}; only a set at end of life can be reopened by an override.").format(
				unit.name, _(unit.status, context="Set Unit")
			)
		)
	unit.flags.tc_audit_reason = override
	_save_lifecycle(unit, status="Processing")


def return_to_receipt(set_unit):
	"""Gói hết hiệu lực trong kho: bộ Vô khuẩn sang Chờ tiếp nhận để đưa về khu bẩn (FR-M2-14); bỏ Cycle ID hiện hành.

	Chỉ bộ đang Vô khuẩn; trạng thái khác → lỗi, không ghi gì. Chu trình kế tiếp mở lại bằng ``start_cycle`` (T1).
	"""
	unit = _set_unit(set_unit, for_update=True)
	if unit.status != "Sterile":
		frappe.throw(
			_("Set {0} is {1}; only a sterile set can be returned for receipt.").format(
				unit.name, _(unit.status, context="Set Unit")
			)
		)
	_save_lifecycle(unit, status="Awaiting Receipt", active_cycle_id=None)


def issue_to_department(set_unit, station):
	"""Cấp phát T7 (FEAT-026 C3): bộ Vô khuẩn sang Tại khoa, ghi trạm cấp; giữ Cycle ID vì gói còn dùng ở T8.

	Chỉ bộ đang Vô khuẩn; trạng thái khác → lỗi, không ghi gì.
	"""
	unit = _set_unit(set_unit, for_update=True)
	if unit.status != "Sterile":
		frappe.throw(
			_("Set {0} is {1}; only a sterile set can be issued to a department.").format(
				unit.name, _(unit.status, context="Set Unit")
			)
		)
	fields = {"status": "At Department"}
	if station:
		fields["current_station"] = station
	_save_lifecycle(unit, **fields)
