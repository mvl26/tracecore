"""Dỡ mẻ, chỉ thị, giải phóng và cách ly chờ BI (T5b, FEAT-023; FR-M2-11, FR-M2-12.2, FR-M2-25; UC-10; WF-03).

Theo khuôn `washing.set_result`: kiểm lại trạm và CẢ HAI mã quét ở server, mọi ghi nhiều bước nằm trong một savepoint.
Người dỡ ghi kết quả chu trình (`set_cycle_result`, nhập tay có xác nhận) và chỉ thị (`record_indicator`); R02 giải phóng
bằng PIN proof của chính phiên (`release`) hoặc R01 giải phóng khẩn kèm lý do. Mẻ cần BI sang Cách ly cho tới khi
`bi_result` đọc kết quả. Mẻ Không đạt (`reject`) trả bộ về xử lý lại. Chỉ `core.step_gate` đổi trạng thái và bộ đếm
chu trình của Set Unit; Pack đổi trạng thái qua `storage._save`.

Không làm (ngoài phạm vi, ghi ở Amendment A-20): NC tự tạo (FEAT-030), lệnh thu hồi (FEAT-029), thông báo (FEAT-010),
dữ liệu máy tự động (FEAT-024), tiêu hao/chi phí (FEAT-042/046: chỉ phát hook `tracecore_after_load_release`).
"""

import contextlib

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, today

from tracecore.core import audit, client_time, code_registry, extension, station_auth, step_gate
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import sterilizing, storage

STEP = sterilizing.STEP
RELEASED = "Released"
QUARANTINE = "Quarantine"
FAILED = "Failed"
SAVEPOINT = "tc_load_release"
APPROVER_ROLE = "TC R02"
EMERGENCY_ROLE = "TC R01"
RESULTS = ("Pass", "Fail")
REDO_STEPS = ("T4", "T2")
BIOLOGICAL = "biological"
BOWIE_DICK = "bowie_dick"
INDICATOR_KINDS = ("bowie_dick", "chemical_class_5", "chemical_plasma", BIOLOGICAL)
AFTER_RELEASE_HOOK = "tracecore_after_release"  # M1 (FEAT-014): +1 bộ đếm bảo dưỡng, mỗi bộ một lần
AFTER_LOAD_RELEASE_HOOK = "tracecore_after_load_release"  # M6/M7 (FEAT-042/046) tiêu hao và chi phí mẻ
AFTER_LOAD_FAILED_HOOK = "tracecore_after_load_failed"  # FEAT-030 NC mẻ không đạt
BI_POSITIVE_HOOK = "tracecore_bi_positive"  # FEAT-029 thu hồi, FEAT-010 thông báo
DAILY_INDICATOR_HOOK = "tracecore_load_daily_indicator"  # M5 (FEAT-040, A-23): Bowie-Dick từ test hằng ngày


def _blocked(code, title, reason, action, items=None):
	return BlockedError(Block(code, title, reason, action, items=items))


def _now(client_ts):
	return sterilizing._system_time(client_ts) if client_ts else now_datetime()


def _methods(machine):
	return sterilizing.STERILIZER_TYPES.get(machine.equipment_type)


def required_indicators(machine):
	"""Chỉ thị bắt buộc để giải phóng theo loại máy (hơi nước: hóa học 5 + Bowie-Dick; plasma: hóa học plasma)."""
	return list(sterilizing.INDICATORS.get(_methods(machine), ()))


def _rows(load):
	return frappe.get_all(
		"Load Indicator Result",
		filters={"load": load},
		fields=["name", "indicator", "pack", "result", "test_date", "lot", "incubator", "read_at", "read_by"],
		order_by="creation asc, name asc",
	)


def _status_of(kind, rows, packs):
	"""``Pass`` / ``Fail`` / ``Missing`` của một chỉ thị: kết quả mới nhất theo mẻ hoặc mới nhất của từng gói."""
	mine = [row for row in rows if row.indicator == kind]
	latest = {}
	for row in mine:
		latest[row.pack or ""] = row.result
	if "Fail" in latest.values():
		return "Fail"
	if latest.get("") == "Pass":
		return "Pass"
	if packs and all(latest.get(pack) == "Pass" for pack in packs):
		return "Pass"
	return "Missing"


def _daily_indicators(doc, machine):
	"""Chỉ thị bắt buộc lấy được từ test hằng ngày của máy trong ngày chạy mẻ (A-23), qua hook của M5 (M2 không import M5).

	``{kind: {"daily_test", "result", "test_date", "tested_at", "tested_by"}}``; chỉ thị không có test hằng ngày thì vắng.
	"""
	on = getdate(doc.started_at) if doc.started_at else getdate(today())
	daily = {}
	for kind in required_indicators(machine):
		found = [row for row in extension.run(DAILY_INDICATOR_HOOK, doc.equipment, kind, on) if row]
		if found:
			daily[kind] = found[0]
	return daily


def _indicator_state(doc, machine, daily=None):
	"""Trạng thái từng chỉ thị; kết quả ghi theo mẻ thắng, chưa ghi thì lấy test hằng ngày của máy (A-23)."""
	rows = _rows(doc.name)
	packs = [row.pack for row in doc.packs]
	kinds = [*required_indicators(machine), *([BIOLOGICAL] if cint(doc.requires_bi) else [])]
	state = {}
	for kind in kinds:
		if kind == BIOLOGICAL and doc.bi_result == "Pending":
			state[kind] = "Pending"
			continue
		state[kind] = _status_of(kind, rows, packs)
		if state[kind] == "Missing" and kind in (daily or {}) and daily[kind]["result"] in RESULTS:
			state[kind] = daily[kind]["result"]
	return state


def context(load, equipment_raw, load_raw, station):
	"""Màn dỡ mẻ sau khi quét QR máy và QR mẻ: thẻ mẻ, chỉ thị đã ghi, trạng thái từng chỉ thị và điều kiện còn thiếu."""
	doc, machine = sterilizing._open_for_data(load, equipment_raw, load_raw, station)
	daily = _daily_indicators(doc, machine)
	state = _indicator_state(doc, machine, daily)
	return {
		**sterilizing._describe(doc),
		"cycle_result": doc.cycle_result or None,
		"indicator_state": state,
		"daily_indicators": daily,
		"indicator_rows": _rows(doc.name),
		"missing": _missing(doc, state, review_confirmed=bool(cint(doc.review_confirmed))),
	}


def _confirmation_needed(items):
	return _blocked(
		"DATA_INCOMPLETE",
		_("Cycle result is not confirmed"),
		_("The cycle result needs a Pass or Fail and the confirmation tick."),
		_("Choose Pass or Fail, tick the confirmation, then record the result."),
		items=items,
	)


def set_cycle_result(
	load, station, equipment_raw, load_raw, result, confirmed, employee=None, client_ts=None
):
	"""Ghi kết quả chu trình Đạt/Không đạt (nhập tay có xác nhận, FR-M2-11.3) áp cho mọi gói của mẻ.

	Chưa có dữ liệu chu trình đầy đủ (`data_complete`) hoặc chưa tick xác nhận → DATA_INCOMPLETE; kết quả khác Đạt/Không
	đạt → RESULT_INVALID. Mẻ vẫn mở, chưa giải phóng.
	"""
	doc, _machine = sterilizing._open_for_data(load, equipment_raw, load_raw, station, for_update=True)
	if result not in RESULTS:
		raise _blocked(
			"RESULT_INVALID",
			_("Result is not valid"),
			_("The cycle result must be Pass or Fail."),
			_("Choose Pass or Fail for the cycle."),
		)
	if not cint(doc.data_complete):
		raise _blocked(
			"DATA_INCOMPLETE",
			_("Cycle data is incomplete"),
			_("Sterilization load {0} has no complete, confirmed cycle data.").format(doc.name),
			_("Enter the cycle data from the sterilizer screen or printout and confirm it first."),
			items=[_("cycle data")],
		)
	if not confirmed:
		raise _confirmation_needed([sterilizing.MISSING_CONFIRMATION])
	doc.update(
		{
			"cycle_result": result,
			"result_source": "Manual",
			"unload_scan_equipment": doc.equipment,
			"unload_scan_at": _now(client_ts),
		}
	)
	doc.flags.tc_sterilizing = True
	doc.flags.ignore_permissions = True
	doc.save()
	return {"load": doc.name, "cycle_result": result, "needs_review": cint(doc.needs_review)}


def _invalid(reason):
	return _blocked(
		"INDICATOR_INVALID",
		_("Indicator is not valid"),
		reason,
		_("Check the indicator type and result, then record it again."),
	)


def record_indicator(
	load,
	station,
	equipment_raw,
	load_raw,
	indicator,
	result,
	pack=None,
	test_date=None,
	lot=None,
	incubator=None,
	read_at=None,
	employee=None,
	client_ts=None,
):
	"""Ghi kết quả một chỉ thị của mẻ (theo mẻ, hoặc theo gói khi truyền `pack`); trả ``{"indicator_result"}``.

	Chỉ thị phải thuộc loại máy (hơi nước: hóa học 5, Bowie-Dick; plasma: hóa học plasma; sinh học khi mẻ cần BI);
	Bowie-Dick cần ngày thử là hôm nay; sinh học tạo ``Pending`` kèm lô và tủ ủ, đọc sau bằng `bi_result`.
	"""
	doc, machine = sterilizing._open_for_data(load, equipment_raw, load_raw, station, for_update=True)
	allowed = set(required_indicators(machine))
	if cint(doc.requires_bi):
		allowed.add(BIOLOGICAL)
	if indicator not in allowed:
		raise _invalid(_("Indicator {0} does not apply to this load.").format(indicator))
	valid = ("Pending", *RESULTS) if indicator == BIOLOGICAL else RESULTS
	if result not in valid:
		raise _invalid(_("Result {0} is not valid for indicator {1}.").format(result, indicator))
	if pack and pack not in [row.pack for row in doc.packs]:
		raise _invalid(_("Pack {0} is not in load {1}.").format(pack, doc.name))
	if indicator == BOWIE_DICK and (not test_date or getdate(test_date) != getdate(today())):
		raise _invalid(_("The Bowie-Dick test date must be today."))
	if indicator == BIOLOGICAL and result == "Pending" and not (lot and incubator):
		raise _invalid(_("A biological indicator needs its lot and the incubator."))
	row = frappe.get_doc(
		{
			"doctype": "Load Indicator Result",
			"load": doc.name,
			"indicator": indicator,
			"pack": pack or None,
			"result": result,
			"test_date": test_date if indicator == BOWIE_DICK else None,
			"lot": lot or None,
			"incubator": incubator or None,
			"read_at": read_at or (now_datetime() if result != "Pending" else None),
			"read_by": employee if result != "Pending" else None,
			"recorded_by_user": frappe.session.user,
			"station": station,
		}
	)
	row.flags.tc_releasing = True
	row.insert(ignore_permissions=True)
	if indicator == BIOLOGICAL and result == "Pending":
		doc.bi_result = "Pending"
		doc.flags.tc_sterilizing = True
		doc.flags.ignore_permissions = True
		doc.save()
	return {"indicator_result": row.name, "indicator": indicator, "result": result}


def _missing(doc, state, review_confirmed):
	items = []
	if doc.cycle_result != "Pass":
		items.append("cycle_result")
	if cint(doc.needs_review) and not review_confirmed:
		items.append("review")
	items += [kind for kind, value in state.items() if kind != BIOLOGICAL and value != "Pass"]
	return items


def _approver(session, proof, emergency_reason):
	"""R02 đã xác nhận PIN (hoặc R01 kèm lý do khẩn) bằng proof của phiên `session`; ngược lại R02_CONFIRM_REQUIRED."""
	user = None
	if proof:
		with contextlib.suppress(BlockedError):
			user = station_auth.consume_session_pin_proof(session, proof).user
	roles = frappe.get_roles(user) if user else []
	reason = emergency_reason.strip() if isinstance(emergency_reason, str) else ""
	if user and APPROVER_ROLE in roles:
		return user, None
	if user and EMERGENCY_ROLE in roles and reason:
		return user, reason
	raise _blocked(
		"R02_CONFIRM_REQUIRED",
		_("R02 confirmation required"),
		_("Only R02 can release a sterilization load, with the card and PIN."),
		_(
			"Ask R02 to sign in at this station and enter the PIN. R01 needs a reason for an emergency release."
		),
	)


def _employee(user):
	return frappe.db.get_value("Employee", {"user_id": user}, "name") if user else None


def release(
	load,
	station,
	equipment_raw,
	load_raw,
	session=None,
	pin_proof=None,
	review_confirmed=False,
	emergency_reason=None,
	client_ts=None,
):
	"""Giải phóng mẻ (R02 + PIN proof; R01 kèm lý do là giải phóng khẩn, FR-M2-11.4, .8): Đã giải phóng hoặc Cách ly.

	Điều kiện (không đổi gì nếu thiếu → LOAD_NOT_RELEASABLE kèm danh sách thiếu): có kết quả chu trình Đạt, đủ chỉ
	thị bắt buộc Đạt, mẻ Cần xem xét được R02 xác nhận. Mẻ cần BI mà chưa có BI âm tính sang Cách ly chờ đọc (trừ
	giải phóng khẩn). Giải phóng Đạt: Pack ``Released``, cổng T5 Đạt từng bộ (đủ 5 cổng → Vô khuẩn), +1 chu trình, hook
	`tracecore_after_release` mỗi bộ và `tracecore_after_load_release`, mẻ ghi sổ. Trả ``{"load", "status", "sets"}``.
	"""
	client_ts = client_ts or client_time.utc_now()
	frappe.db.savepoint(SAVEPOINT)
	try:
		return _release(
			load,
			station,
			equipment_raw,
			load_raw,
			session,
			pin_proof,
			review_confirmed,
			emergency_reason,
			client_ts,
		)
	except Exception:
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _release(
	load, station, equipment_raw, load_raw, session, pin_proof, review_confirmed, emergency_reason, client_ts
):
	doc, machine = sterilizing._open_for_data(load, equipment_raw, load_raw, station, for_update=True)
	if not cint(doc.data_complete):
		raise _blocked(
			"DATA_INCOMPLETE",
			_("Cycle data is incomplete"),
			_("Sterilization load {0} has no complete, confirmed cycle data.").format(doc.name),
			_("Enter the cycle data and confirm it, then record the result."),
			items=[_("cycle data")],
		)
	daily = _daily_indicators(doc, machine)
	state = _indicator_state(doc, machine, daily)
	missing = _missing(doc, state, bool(cint(review_confirmed)))
	if missing:
		failed = doc.cycle_result == "Fail" or "Fail" in state.values()
		raise _blocked(
			"LOAD_NOT_RELEASABLE",
			_("Load cannot be released"),
			_("A failed cycle or indicator cannot be released; reject the load.")
			if failed
			else _("Sterilization load {0} still lacks: {1}.").format(doc.name, ", ".join(missing)),
			_("Reject the load so its sets are reprocessed.")
			if failed
			else _("Record the missing results, then ask R02 to release the load."),
			items=missing,
		)
	approver, emergency = _approver(session, pin_proof, emergency_reason)
	employee = _employee(approver)
	_keep_daily_indicators(doc, daily, station)
	needs_bi = cint(doc.requires_bi) and state.get(BIOLOGICAL) != "Pass" and not emergency
	doc.review_confirmed = 1 if cint(doc.needs_review) else 0
	if emergency:
		audit.log(
			"Override",
			"Sterilization Load",
			doc.name,
			new={"event": "EmergencyRelease", "reason": emergency},
			reason="EmergencyRelease",
			station=station,
			client_ts=client_ts,
		)
	if needs_bi:
		return _quarantine(doc, station, employee)
	return _finalize(doc, station, client_ts, employee, emergency)


def _keep_daily_indicators(doc, daily, station):
	"""Lúc giải phóng, chỉ thị lấy từ test hằng ngày được ghi lại thành Load Indicator Result của mẻ (A-23): hồ sơ mẻ
	giữ đúng kết quả đã dùng để giải phóng, kể cả khi sau đó máy có thêm lần test trong ngày."""
	recorded = {row.indicator for row in _rows(doc.name)}
	for kind, row in daily.items():
		if kind in recorded:
			continue
		result = frappe.get_doc(
			{
				"doctype": "Load Indicator Result",
				"load": doc.name,
				"indicator": kind,
				"result": row["result"],
				"test_date": row["test_date"],
				"read_at": row.get("tested_at") or now_datetime(),
				"read_by": row.get("tested_by"),
				"recorded_by_user": frappe.session.user,
				"station": station,
			}
		)
		result.flags.tc_releasing = True
		result.insert(ignore_permissions=True)


def _quarantine(doc, station, employee):
	for row in doc.packs:
		pack = storage._lock_pack(row.pack)
		pack.update({"status": QUARANTINE})
		storage._save(pack)
	doc.update({"status": QUARANTINE, "bi_result": doc.bi_result or "Pending", "released_by": employee})
	doc.flags.tc_sterilizing = True
	doc.flags.ignore_permissions = True
	doc.save()
	return {"load": doc.name, "status": QUARANTINE, "sets": _set_states(doc)}


def _set_states(doc):
	return [
		{
			"set_id": row.set_unit,
			"status": frappe.db.get_value("Set Unit", row.set_unit, "status"),
			"cycles_used": cint(frappe.db.get_value("Set Unit", row.set_unit, "cycles_used")),
		}
		for row in doc.packs
	]


def _finalize(doc, station, client_ts, employee, reason):
	"""Giải phóng Đạt (kể cả sau BI âm tính): gói, cổng T5, bộ đếm, hook, ghi sổ mẻ."""
	at = _now(client_ts)
	sets = []
	for row in sorted(doc.packs, key=lambda r: r.pack):
		pack = storage._lock_pack(row.pack)
		pack.update({"status": RELEASED})
		storage._save(pack)
		step_gate.record(
			row.set_unit, STEP, "Pass", ref_doctype="Sterilization Load", ref_name=doc.name, station=station
		)
		step_gate.count_cycle(row.set_unit)
		extension.run(
			AFTER_RELEASE_HOOK,
			{
				"set_unit": row.set_unit,
				"set_type": pack.set_type,
				"bom_version": cint(pack.bom_version),
				"cycle_id": pack.name,
			},
		)
		sets.append(row.set_unit)
	doc.update(
		{
			"status": RELEASED,
			"released_by": employee or doc.released_by,
			"released_at": at,
			"release_reason": reason or doc.release_reason,
		}
	)
	doc.flags.tc_sterilizing = True
	doc.flags.ignore_permissions = True  # quyền đã kiểm ở RPC theo role trạm và PIN proof
	doc.submit()
	extension.run(
		AFTER_LOAD_RELEASE_HOOK,
		{
			"load": doc.name,
			"equipment": doc.equipment,
			"program": doc.program,
			"sets": sets,
			"packs": [row.pack for row in doc.packs],
		},
	)
	return {"load": doc.name, "status": RELEASED, "sets": _set_states(doc)}


def reject(
	load,
	station,
	equipment_raw,
	load_raw,
	reason=None,
	redo_from="T4",
	employee=None,
	client_ts=None,
):
	"""Mẻ Không đạt (kết quả chu trình hoặc chỉ thị không đạt): mọi gói Hết hiệu lực, bộ về Xử lý lại (FR-M2-12.2).

	`redo_from` ``T4`` (mặc định) hoặc ``T2``. Cổng T5 Không đạt cho từng bộ (T2: ghi thêm cổng T2 Không đạt), Cycle ID
	của gói bị vô hiệu, mẻ ghi sổ ``Failed``, hook `tracecore_after_load_failed` (NC tự tạo là FEAT-030).
	"""
	if redo_from not in REDO_STEPS:
		raise _blocked(
			"RESULT_INVALID",
			_("Result is not valid"),
			_("Restart from T4 or from T2."),
			_("Choose T4 or T2 to restart the sets from."),
		)
	frappe.db.savepoint(SAVEPOINT)
	try:
		doc, _machine = sterilizing._open_for_data(load, equipment_raw, load_raw, station, for_update=True)
		return _reject_load(doc, station, redo_from, reason, client_ts)
	except Exception:
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _reject_load(doc, station, redo_from, reason, client_ts):
	note = (reason or "").strip() or _("Sterilization load failed")
	sets = []
	for row in sorted(doc.packs, key=lambda r: r.pack):
		pack = storage._lock_pack(row.pack)
		pack.update({"status": "Void", "void_reason": "Load Failed", "void_note": note})
		storage._save(pack)
		code_registry.disable(pack.name, f"Load Failed: {note}")
		step_gate.record(
			row.set_unit, STEP, "Fail", ref_doctype="Sterilization Load", ref_name=doc.name, station=station
		)
		if redo_from == "T2":
			step_gate.record(
				row.set_unit,
				"T2",
				"Fail",
				ref_doctype="Sterilization Load",
				ref_name=doc.name,
				station=station,
			)
		sets.append(row.set_unit)
	doc.update({"status": FAILED, "redo_from": redo_from, "release_reason": note})
	doc.flags.tc_sterilizing = True
	doc.flags.ignore_permissions = True
	doc.submit()
	audit.log(
		"Update",
		"Sterilization Load",
		doc.name,
		new={"event": "LoadFailed", "sets": sets, "redo_from": redo_from},
		reason="LoadFailed",
		station=station,
		client_ts=client_ts,
	)
	extension.run(
		AFTER_LOAD_FAILED_HOOK,
		{
			"load": doc.name,
			"equipment": doc.equipment,
			"program": doc.program,
			"sets": sets,
			"redo_from": redo_from,
		},
	)
	return {"load": doc.name, "status": FAILED, "sets": _set_states(doc)}


def bi_result(load, result, station, read_at=None, employee=None, client_ts=None):
	"""Đọc kết quả BI của mẻ (FR-M2-11.7, FR-M2-12): cập nhật dòng BI đang `Pending`.

	Mẻ đang Cách ly: âm tính → hoàn tất giải phóng, dương tính → mẻ Không đạt. Mẻ đã giải phóng: âm tính chỉ ghi nhận;
	dương tính phát hook `tracecore_bi_positive` kèm danh sách gói và ghi Audit ``Override`` (lệnh thu hồi là FEAT-029).
	Không có BI đang chờ → BI_NOT_PENDING.
	"""
	if result not in RESULTS:
		raise _blocked(
			"RESULT_INVALID",
			_("Result is not valid"),
			_("The biological indicator result must be Pass (negative) or Fail (positive)."),
			_("Choose Pass or Fail for the biological indicator."),
		)
	frappe.db.savepoint(SAVEPOINT)
	try:
		doc = sterilizing._load_doc(load, for_update=True)
		machine = frappe.db.get_value(
			"Equipment", doc.equipment, list(sterilizing.EQUIPMENT_FIELDS), as_dict=True
		)
		sterilizing._check_data_station(station, machine)
		pending = frappe.get_all(
			"Load Indicator Result",
			filters={"load": doc.name, "indicator": BIOLOGICAL, "result": "Pending"},
			pluck="name",
		)
		if not pending:
			raise _blocked(
				"BI_NOT_PENDING",
				_("No biological indicator is waiting"),
				_("Sterilization load {0} has no biological indicator waiting to be read.").format(doc.name),
				_("Record the biological indicator with its lot and incubator first."),
			)
		for name in pending:
			row = frappe.get_doc("Load Indicator Result", name)
			row.update({"result": result, "read_at": read_at or now_datetime(), "read_by": employee})
			row.flags.tc_releasing = True
			row.save(ignore_permissions=True)
		return _after_bi(doc, result, station, employee, client_ts)
	except Exception:
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _after_bi(doc, result, station, employee, client_ts):
	if doc.status == QUARANTINE:
		doc.bi_result = result
		if result == "Pass":
			return _finalize(doc, station, client_ts, employee, None)
		out = _reject_load(doc, station, "T4", _("Biological indicator is positive"), client_ts)
		_bi_positive(doc, station, client_ts)
		return out
	frappe.db.set_value("Sterilization Load", doc.name, "bi_result", result, update_modified=False)
	out = {"load": doc.name, "status": doc.status, "recall_needed": False}
	if result == "Fail" and doc.status == RELEASED:
		_bi_positive(doc, station, client_ts)
		out["recall_needed"] = True
		# lệnh thu hồi do hook tracecore_bi_positive lập (FEAT-029); None khi không còn gói nào phải thu
		out["recall"] = frappe.db.get_value(
			"Recall Order", {"sterilization_load": doc.name, "docstatus": 0}, "name"
		)
	return out


def _bi_positive(doc, station, client_ts):
	packs = [
		{
			"cycle_id": row.pack,
			"set_unit": row.set_unit,
			"status": frappe.db.get_value("Pack", row.pack, "status"),
		}
		for row in doc.packs
	]
	audit.log(
		"Override",
		"Sterilization Load",
		doc.name,
		new={"event": "BIPositive", "packs": [pack["cycle_id"] for pack in packs]},
		reason="BIPositive",
		station=station,
		client_ts=client_ts,
	)
	extension.run(BI_POSITIVE_HOOK, {"load": doc.name, "equipment": doc.equipment, "packs": packs})
