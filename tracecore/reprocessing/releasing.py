"""Dỡ mẻ, chỉ thị, giải phóng và cách ly chờ BI (T5b, FEAT-023; FR-M2-11, FR-M2-12.2, FR-M2-25; UC-10; WF-03).

Theo khuôn `washing.set_result`: kiểm lại trạm và CẢ HAI mã quét ở server, mọi ghi nhiều bước nằm trong một savepoint.
Người dỡ ghi kết quả chu trình (`set_cycle_result`, nhập tay có xác nhận) và chỉ thị (`record_indicator`). Giải phóng theo
A-106: dữ liệu trong dải thì R05, R02, R01 của phiên tự giải phóng, không PIN (mẻ Cần xem xét: R02, R01); dữ liệu ngoài dải
chỉ R01 tại trạm, có PIN proof của chính phiên và lý do. R01 giải phóng khẩn kèm PIN và lý do khi dữ liệu trong dải. Mẻ cần BI sang Cách ly cho tới khi
`bi_result` đọc kết quả. Mẻ Không đạt (`reject`) trả bộ về xử lý lại. Chỉ `core.step_gate` đổi trạng thái và bộ đếm
chu trình của Set Unit; Pack đổi trạng thái qua `storage._save`.

Không làm (ngoài phạm vi, ghi ở Amendment A-20): NC tự tạo (FEAT-030), lệnh thu hồi (FEAT-029), thông báo (FEAT-010),
dữ liệu máy tự động (FEAT-024), tiêu hao/chi phí (FEAT-042/046: chỉ phát hook `tracecore_after_load_release`).
"""

import contextlib

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime, today

from tracecore.core import audit, client_time, code_registry, extension, station_auth, step_gate, zones
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import sterilizing, storage

STEP = sterilizing.STEP
RELEASED = "Released"
QUARANTINE = "Quarantine"
FAILED = "Failed"
SAVEPOINT = "tc_load_release"
APPROVER_ROLE = "TC R02"
EMERGENCY_ROLE = "TC R01"
TECHNICIAN_ROLE = "TC R05"
# quy tắc giải phóng của mẻ (A-106): ai bấm được Giải phóng mẻ
RULE_TECHNICIAN, RULE_SUPERVISOR, RULE_HEAD = "technician", "supervisor", "head"
RULE_ROLES = {
	RULE_TECHNICIAN: {TECHNICIAN_ROLE, APPROVER_ROLE, EMERGENCY_ROLE},
	RULE_SUPERVISOR: {APPROVER_ROLE, EMERGENCY_ROLE},
	RULE_HEAD: {EMERGENCY_ROLE},
}
RESULTS = ("Pass", "Fail")
REDO_STEPS = ("T4", "T2")
BIOLOGICAL = "biological"
BOWIE_DICK = "bowie_dick"
OPTIONAL = "Optional"  # chỉ thị không bắt buộc của máy ngoài diện test hằng ngày và chưa có kết quả (A-70)
INDICATOR_KINDS = ("bowie_dick", "chemical_class_5", "chemical_plasma", BIOLOGICAL)
AFTER_RELEASE_HOOK = "tracecore_after_release"  # M1 (FEAT-014): +1 bộ đếm bảo dưỡng, mỗi bộ một lần
AFTER_LOAD_RELEASE_HOOK = "tracecore_after_load_release"  # M6/M7 (FEAT-042/046) tiêu hao và chi phí mẻ
AFTER_LOAD_FAILED_HOOK = "tracecore_after_load_failed"  # FEAT-030 NC mẻ không đạt
BI_POSITIVE_HOOK = "tracecore_bi_positive"  # FEAT-029 thu hồi, FEAT-010 thông báo
DAILY_INDICATOR_HOOK = "tracecore_load_daily_indicator"  # M5 (FEAT-040, A-23): Bowie-Dick từ test hằng ngày


def _blocked(code, title, reason, action, items=None, **fields):
	return BlockedError(Block(code, title, reason, action, items=items, **fields))


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
	optional = sterilizing.optional_indicators(doc.equipment)
	kinds = [*required_indicators(machine), *([BIOLOGICAL] if cint(doc.requires_bi) else [])]
	state = {}
	for kind in kinds:
		if kind == BIOLOGICAL and doc.bi_result == "Pending":
			state[kind] = "Pending"
			continue
		state[kind] = _status_of(kind, rows, packs)
		if state[kind] == "Missing" and kind in (daily or {}) and daily[kind]["result"] in RESULTS:
			state[kind] = daily[kind]["result"]
		if state[kind] == "Missing" and kind in optional:
			state[kind] = OPTIONAL
	return state


def context(load, equipment_raw, load_raw, station):
	"""Màn dỡ mẻ sau khi quét QR máy và QR mẻ: thẻ mẻ, chỉ thị đã ghi, trạng thái từng chỉ thị và điều kiện còn thiếu."""
	doc, machine = sterilizing._open_for_data(load, equipment_raw, load_raw, station, unload_only=True)
	daily = _daily_indicators(doc, machine)
	state = _indicator_state(doc, machine, daily)
	return {
		**sterilizing._describe(doc),
		"cycle_result": doc.cycle_result or None,
		"indicator_state": state,
		"daily_indicators": daily,
		"indicator_rows": _rows(doc.name),
		"missing": _missing(doc, state, review_confirmed=bool(cint(doc.review_confirmed))),
		"release_rule": release_rule(doc),
		"out_of_range_names": [row["parameter_name"] for row in _outside_rows(doc)],
		"out_of_range_accepted": _accepted_current(doc),
	}


def _outside_rows(doc):
	"""Tham số ngoài dải của chương trình trong dữ liệu chu trình hiện tại của mẻ."""
	rows = frappe.parse_json(doc.params) if doc.params else []
	return [
		{key: row.get(key) for key in ("parameter_name", "unit", "value", "min_value", "max_value")}
		for row in rows or []
		if row.get("outside_range")
	]


def release_rule(doc):
	"""A-106: ngoài dải → trưởng khoa; Cần xem xét do sự cố máy, khớp theo giờ → giám sát; còn lại → KTV tự giải phóng."""
	if _outside_rows(doc):
		return RULE_HEAD
	return RULE_SUPERVISOR if cint(doc.needs_review) else RULE_TECHNICIAN


def _accepted_current(doc):
	"""Lựa chọn Vẫn chấp nhận còn hiệu lực: đúng các giá trị ngoài dải đang có; sửa số liệu thì phải chọn lại."""
	if not doc.out_of_range_accepted:
		return False
	return frappe.parse_json(doc.out_of_range_accepted) == _outside_rows(doc)


def _needs_acceptance(doc):
	names = [row["parameter_name"] for row in _outside_rows(doc)]
	return _blocked(
		"CYCLE_DATA_OUT_OF_RANGE",
		_("A Pass needs a deliberate choice"),
		_("{0} {1} has values outside the program range: {2}.").format(
			_("Sterilization load"), doc.name, ", ".join(names)
		),
		_(
			"Correct the data if it was entered wrong, record Fail, or choose Accept anyway; the head of KSNK then approves the release."
		),
		items=names,
	)


def _confirmation_needed(items):
	return _blocked(
		"DATA_INCOMPLETE",
		_("Cycle result is not confirmed"),
		_("The cycle result needs a Pass or Fail and the confirmation tick."),
		_("Choose Pass or Fail, tick the confirmation, then record the result."),
		items=items,
	)


def set_cycle_result(
	load,
	station,
	equipment_raw,
	load_raw,
	result,
	confirmed,
	employee=None,
	client_ts=None,
	accept_out_of_range=False,
):
	"""Ghi kết quả chu trình Đạt/Không đạt (nhập tay có xác nhận, FR-M2-11.3) áp cho mọi gói của mẻ.

		Chưa có dữ liệu chu trình đầy đủ (`data_complete`) hoặc chưa tick xác nhận → DATA_INCOMPLETE; kết quả khác Đạt/Không
		đạt → RESULT_INVALID. Đạt khi có tham số ngoài dải chỉ qua lựa chọn `accept_out_of_range` (A-106), giải phóng sau đó cần
	trưởng khoa. Mẻ vẫn mở, chưa giải phóng.
	"""
	doc, _machine = sterilizing._open_for_data(
		load, equipment_raw, load_raw, station, for_update=True, unload_only=True
	)
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
	outside = _outside_rows(doc) if result == "Pass" else []
	if outside and not accept_out_of_range:
		raise _needs_acceptance(doc)
	if outside:
		audit.log(
			"Override",
			"Sterilization Load",
			doc.name,
			new={"event": "OutOfRangeAccepted", "employee": employee, "params": outside},
			reason="OutOfRangeAccepted",
			station=station,
			client_ts=client_ts,
		)
	doc.update(
		{
			"cycle_result": result,
			"out_of_range_accepted": frappe.as_json(outside) if outside else None,
			"out_of_range_accepted_by": employee if outside else None,
			"result_source": "Manual",
			"unload_scan_equipment": doc.equipment,
			"unload_scan_at": _now(client_ts),
			"unloaded_by": doc.unloaded_by or employee,  # A-86
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
	doc, machine = sterilizing._open_for_data(
		load, equipment_raw, load_raw, station, for_update=True, unload_only=True
	)
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
	items += [kind for kind, value in state.items() if kind != BIOLOGICAL and value not in ("Pass", OPTIONAL)]
	return items


def _clean(text):
	return text.strip() if isinstance(text, str) else ""


def _session_person(session):
	"""(user, employee) của phiên trạm; gọi không qua phiên trạm thì người dùng hiện tại."""
	row = (
		frappe.db.get_value("Station Session", session, ["user", "employee"], as_dict=True)
		if session
		else None
	)
	if row and row.user:
		return row.user, row.employee or _employee(row.user)
	return frappe.session.user, _employee(frappe.session.user)


def _proof_matches(session, proof, user):
	"""PIN proof còn hiệu lực của đúng người đang đăng nhập phiên trạm; không có PIN không thẻ (A-106)."""
	if not proof or not session:
		return False
	with contextlib.suppress(BlockedError):
		return station_auth.consume_session_pin_proof(session, proof).user == user
	return False


def _supervisor_needed():
	return _blocked(
		"R02_CONFIRM_REQUIRED",
		_("A CSSD supervisor must release the load"),
		_("This load needs a review by the CSSD supervisor or the head of KSNK before release."),
		_("Log out, then the CSSD supervisor signs in with the card at this station."),
	)


def _head_needed(rows, doc, reason=None):
	names = ", ".join(row["parameter_name"] for row in rows)
	return _blocked(
		"HEAD_APPROVAL_REQUIRED",
		_("Head of KSNK approval required"),
		reason
		or _("Head of KSNK approval is needed because the cycle data is outside the range: {0}").format(
			names
		),
		_("The head of KSNK signs in with the card at this station, enters the PIN and the reason."),
		items=[row["parameter_name"] for row in rows],
		object_type="Sterilization Load",
		object_name=doc.name,
	)


def _approve_out_of_range(doc, rows, user, employee, session, proof, reason, station, client_ts):
	"""Quy tắc B của A-106: chỉ R01 đăng nhập bằng thẻ tại trạm, có PIN và lý do; ghi người duyệt lên mẻ và Audit Log."""
	if EMERGENCY_ROLE not in frappe.get_roles(user):
		raise _head_needed(rows, doc)
	if not reason:
		raise _head_needed(rows, doc, _("A reason is required to accept cycle data outside the range."))
	if not _proof_matches(session, proof, user):
		raise _head_needed(rows, doc, _("The PIN of the head of KSNK signed in at this station is required."))
	doc.update({"out_of_range_approved_by": employee, "out_of_range_reason": reason})
	audit.log(
		"Override",
		"Sterilization Load",
		doc.name,
		new={"event": "OutOfRangeApproved", "approver": employee, "reason": reason, "params": rows},
		reason="OutOfRangeApproved",
		station=station,
		client_ts=client_ts,
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
	out_of_range_reason=None,
):
	"""Giải phóng mẻ theo A-106 (FR-M2-11.4, .8): Đã giải phóng hoặc Cách ly.

	Trong dải: R05, R02, R01 của phiên, không PIN; `released_by` là nhân viên của phiên. Cần xem xét: R02, R01 xác nhận.
	Ngoài dải: chỉ R01, `pin_proof` của chính phiên và `out_of_range_reason`, không có giải phóng khẩn. R01 trong dải kèm
	`emergency_reason` là giải phóng khẩn, cần PIN và không chờ BI. Điều kiện (không đổi gì nếu thiếu →
	LOAD_NOT_RELEASABLE kèm danh sách thiếu): có kết quả chu trình Đạt, đủ chỉ thị bắt buộc Đạt. Mẻ cần BI mà chưa có BI âm tính sang Cách ly chờ đọc (trừ
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
			out_of_range_reason,
		)
	except Exception:
		with contextlib.suppress(Exception):
			frappe.db.rollback(save_point=SAVEPOINT)
		raise


def _release(
	load,
	station,
	equipment_raw,
	load_raw,
	session,
	pin_proof,
	review_confirmed,
	emergency_reason,
	client_ts,
	out_of_range_reason=None,
):
	doc, machine = sterilizing._open_for_data(
		load, equipment_raw, load_raw, station, for_update=True, unload_only=True
	)
	if not cint(doc.data_complete):
		raise _blocked(
			"DATA_INCOMPLETE",
			_("Cycle data is incomplete"),
			_("Sterilization load {0} has no complete, confirmed cycle data.").format(doc.name),
			_("Enter the cycle data and confirm it, then record the result."),
			items=[_("cycle data")],
		)
	outside = _outside_rows(doc)
	# kết quả máy báo hoặc dữ liệu sửa sau khi ghi Đạt: chưa ai chọn Vẫn chấp nhận đúng các giá trị này (A-89, A-106)
	if doc.cycle_result == "Pass" and outside and not _accepted_current(doc):
		raise _needs_acceptance(doc)
	daily = _daily_indicators(doc, machine)
	state = _indicator_state(doc, machine, daily)
	# ngoài dải: trưởng khoa duyệt thay cho ô xác nhận của giám sát
	reviewed = bool(cint(review_confirmed)) or bool(outside)
	missing = _missing(doc, state, reviewed)
	blocking = [code for code in missing if code != "review"]
	if blocking:
		failed = doc.cycle_result == "Fail" or "Fail" in state.values()
		raise _blocked(
			"LOAD_NOT_RELEASABLE",
			_("Load cannot be released"),
			_("A failed cycle or indicator cannot be released; reject the load.")
			if failed
			else _("Sterilization load {0} still lacks: {1}.").format(doc.name, ", ".join(blocking)),
			_("Reject the load so its sets are reprocessed.")
			if failed
			else _("Record the missing results, then release the load."),
			items=blocking,
			object_type="Sterilization Load",
			object_name=doc.name,
		)
	user, employee = _session_person(session)
	roles = set(frappe.get_roles(user))
	emergency = None
	if outside:
		_approve_out_of_range(
			doc, outside, user, employee, session, pin_proof, _clean(out_of_range_reason), station, client_ts
		)
	else:
		if not roles & RULE_ROLES[release_rule(doc)]:
			raise _supervisor_needed()
		if "review" in missing:
			raise _blocked(
				"LOAD_NOT_RELEASABLE",
				_("Load cannot be released"),
				_("Sterilization load {0} still lacks: {1}.").format(doc.name, "review"),
				_("Tick the review confirmation, then release the load."),
				items=["review"],
				object_type="Sterilization Load",
				object_name=doc.name,
			)
		if _clean(emergency_reason) and EMERGENCY_ROLE in roles and APPROVER_ROLE not in roles:
			if not _proof_matches(session, pin_proof, user):
				raise _blocked(
					"R02_CONFIRM_REQUIRED",
					_("PIN is required"),
					_("An emergency release needs the PIN of the head of KSNK signed in at this station."),
					_("Enter the 6-digit PIN, or clear the emergency reason."),
				)
			emergency = _clean(emergency_reason)
		doc.update(
			{
				"out_of_range_accepted": None,
				"out_of_range_accepted_by": None,
				"out_of_range_approved_by": None,
				"out_of_range_reason": None,
			}
		)
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
	audit.log(
		"Update",
		"Sterilization Load",
		doc.name,
		new={"event": "LoadReleased", "employee": employee, "rule": release_rule(doc)},
		reason="LoadReleased",
		station=station,
		client_ts=client_ts,
	)
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


def _mark_unloaded(doc, employee, at):
	"""Mẻ có kết quả tự động từ máy chưa qua bước ghi kết quả: giải phóng hoặc cách ly là đã dỡ (A-86)."""
	if not doc.unload_scan_at:
		doc.update({"unload_scan_equipment": doc.equipment, "unload_scan_at": at})
	doc.unloaded_by = doc.unloaded_by or employee


def _quarantine(doc, station, employee):
	for row in doc.packs:
		pack = storage._lock_pack(row.pack)
		pack.update({"status": QUARANTINE})
		storage._save(pack)
	_mark_unloaded(doc, employee, now_datetime())
	# A-102: cách ly chưa phải giải phóng, `released_by` chỉ ghi ở `_finalize`; người duyệt cách ly nằm ở Audit Log
	doc.update({"status": QUARANTINE, "bi_result": doc.bi_result or "Pending"})
	audit.log(
		"Update",
		"Sterilization Load",
		doc.name,
		new={"event": "QuarantineApproved", "employee": employee},
		reason="QuarantineApproved",
		station=station,
	)
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
	_mark_unloaded(doc, employee, at)
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
			_("Restart from {0} or from {1}.").format(zones.gate_label("T4"), zones.gate_label("T2")),
			_("Choose {0} or {1} to restart the sets from.").format(
				zones.gate_label("T4"), zones.gate_label("T2")
			),
		)
	frappe.db.savepoint(SAVEPOINT)
	try:
		doc, _machine = sterilizing._open_for_data(
			load, equipment_raw, load_raw, station, for_update=True, unload_only=True
		)
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
		sterilizing._check_data_station(station, machine, unload_only=True)
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
