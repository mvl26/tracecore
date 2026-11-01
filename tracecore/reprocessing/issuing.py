"""T7 Cấp phát cho khoa (FEAT-026, UC-12, FR-M2-15/16, A-17 C1-C13): phiếu nhiều gói, người nhận, chữ ký, cơ số khoa.

Phiếu `Issue Note` mở ở trạng thái nháp khi chọn khoa, nhận từng gói `In Sterile Stock` (C9), người nhận quét thẻ và
ký (thẻ hoặc cảm ứng, C7), rồi ghi sổ: Pack → `Issued`, Set Unit → `At Department` qua `step_gate.issue_to_department`
(module này không tự đổi trạng thái Set Unit, ADR-005). Tồn khoa suy ra từ phiếu đã ghi sổ (C4). Cơ số khoa hỏi M8 qua
hook ``tracecore_issue_par_check`` (C5, không import M8); vượt tối đa cần R02 duyệt bằng thẻ + PIN (C6).
Khóa theo thứ tự Set Unit rồi Pack như `storage._lock_pack`.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, getdate, now_datetime, today

from tracecore.core import audit, error_codes, extension, gs1, station_auth, step_gate, zones
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import pack_display, storage

FUNCTION = "ISSUE"
ISSUED = "Issued"
IN_STOCK = storage.IN_STOCK
PAR_HOOK = "tracecore_issue_par_check"
APPROVER_ROLE = "TC R02"
PRINT_FORMAT = "TC Issue Note"
SIGN_METHODS = ("Card", "Touch")
SIGNATURE_PREFIX = "data:image/png;base64,"
SIGNATURE_MAX_LENGTH = 200_000  # ảnh chữ ký PNG ≤ ~150 KB sau base64 (C7)
SAVEPOINT = "tc_issue_submit"


def _blocked(code, title, reason, action, items=None, **fields):
	return BlockedError(Block(code, title, reason, action, items=items, **fields))


def _require_station(station):
	"""Trạm (không phải khu) có chức năng ``FUNCTION``; ngược lại STATION_WRONG_STEP."""
	row = frappe.db.get_value("Zone Station", station, "is_zone", as_dict=True) if station else None
	if row and not cint(row.is_zone) and zones.station_has_function(station, FUNCTION):
		return
	raise _blocked(
		"STATION_WRONG_STEP",
		_("Wrong station"),
		_("{0} is not a {1} station.").format(station, zones.function_label(FUNCTION))
		if row
		else _("Station {0} does not exist.").format(station or "-"),
		_("Open this screen on a {0} station.").format(zones.function_label(FUNCTION)),
	)


# --- Đọc: khoa, tồn khoa, cơ số ----------------------------------------------------------------------------


def departments():
	"""Khoa nhận cấp phát (Department không phải nhóm, đang dùng), theo tên.

	Chỉ khoa đánh dấu `tc_is_ward` (A-22): phòng ban mặc định của ERPNext (Accounts, Sales…) không phải khoa.
	Mỗi khoa kèm `shortage`, loại bộ đang thiếu cơ số.
	"""
	rows = frappe.get_all(
		"Department",
		filters={"is_group": 0, "disabled": 0, "tc_is_ward": 1},
		fields=["name", "department_name"],
		order_by="department_name asc, name asc",
	)
	for row in rows:
		row["shortage"] = _shortage(row.name)
	return rows


def _shortage(department):
	"""Loại bộ khoa đang thiếu so với cơ số tối thiểu (D10, A-95): chỉ từ Par Level có sẵn."""
	return [
		{key: par[key] for key in ("set_type", "set_name", "stock", "suggest", "available")}
		for par in _par_rows(department, {})
		if par["suggest"] > 0
	]


def _department(department):
	name = frappe.db.get_value("Department", department, "name") if department else None
	if not name:
		raise _blocked(
			"DEPARTMENT_NOT_FOUND",
			_("Department not found"),
			_("Department {0} does not exist.").format(department or "-"),
			_("Choose the department again from the list."),
		)
	return name


def department_stock(department):
	"""Tồn khoa theo loại bộ (C4): gói `Issued` nằm trong phiếu cấp phát đã ghi sổ của khoa."""
	rows = frappe.db.sql(
		"""
		select p.set_type, count(*) as qty
		from `tabIssue Note` n
		join `tabIssue Note Pack` r on r.parent = n.name and r.parenttype = 'Issue Note'
		join `tabPack` p on p.name = r.pack
		where n.docstatus = 1 and n.department = %s and p.docstatus = 1 and p.status = %s
		group by p.set_type
		""",
		(department, ISSUED),
		as_dict=True,
	)
	return {row.set_type: cint(row.qty) for row in rows}


def sterile_stock():
	"""Gói còn dùng được trong kho vô khuẩn theo loại bộ (tồn kho vô khuẩn, FEAT-025)."""
	rows = frappe.get_all(
		"Pack",
		filters={"docstatus": 1, "status": IN_STOCK, "expiry": (">=", today())},
		fields=["set_type", "count(name) as qty"],
		group_by="set_type",
	)
	return {row.set_type: cint(row.qty) for row in rows}


def _par_check(department, set_type, stock, adding):
	"""Kết quả hook cơ số khoa (C5) cho một loại bộ; không hàm nào trả dict → `unconfigured`."""
	ctx = {"department": department, "set_type": set_type, "stock": stock, "adding": adding}
	for result in extension.run(PAR_HOOK, ctx):
		if isinstance(result, dict):
			return result
	return {
		"set_type": set_type,
		"stock": stock,
		"adding": adding,
		"after": stock + adding,
		"min": None,
		"max": None,
		"over_percent": 0,
		"limit": None,
		"suggest": 0,
		"state": "unconfigured",
	}


def _set_names(set_types):
	if not set_types:
		return {}
	return dict(
		frappe.get_all(
			"Instrument Set Type",
			filters={"name": ("in", list(set_types))},
			fields=["name", "set_type_name"],
			as_list=True,
		)
	)


def _par_rows(department, adding):
	"""Một dòng mỗi loại bộ: đang có trong phiếu (`adding`), có cơ số của khoa, hoặc khoa đang giữ."""
	stock = department_stock(department)
	configured = frappe.get_all(
		"Par Level",
		filters={
			"par_kind": "Department Stock",
			"target_doctype": "Instrument Set Type",
			"department": department,
			"is_active": 1,
		},
		pluck="target",
	)
	set_types = sorted(set(adding) | set(stock) | set(configured))
	names = _set_names(set_types)
	available = sterile_stock()
	rows = []
	for set_type in set_types:
		row = _par_check(department, set_type, stock.get(set_type, 0), adding.get(set_type, 0))
		rows.append(
			{
				**row,
				"set_type": set_type,
				"set_name": names.get(set_type),
				"available": available.get(set_type, 0),
			}
		)
	return rows


def context(department, issue_note=None):
	"""UC-12 bước 1: tồn khoa, cơ số và tồn kho vô khuẩn theo loại bộ của khoa (kèm số gói trong phiếu nháp)."""
	department = _department(department)
	adding = {}
	if issue_note:
		for row in _note(issue_note).packs:
			adding[row.set_type] = adding.get(row.set_type, 0) + 1
	return {
		"department": department,
		"department_name": frappe.db.get_value("Department", department, "department_name"),
		"rows": _par_rows(department, adding),
	}


# --- Phiếu nháp ---------------------------------------------------------------------------------------------


def _note(name, for_update=False, draft=True):
	exists = frappe.db.exists("Issue Note", name) if isinstance(name, str) and name else None
	if not exists:
		raise _blocked(
			"ISSUE_NOT_FOUND",
			_("Issue note not found"),
			_("Issue note {0} does not exist.").format(name or "-"),
			_("Choose the department again to open a new issue note."),
		)
	note = frappe.get_doc("Issue Note", name, for_update=for_update)
	if draft and note.docstatus != 0:
		raise _blocked(
			"ISSUE_NOT_DRAFT",
			_("Issue note is already confirmed"),
			_("Issue note {0} has been confirmed and cannot change.").format(name),
			_("Choose the department again to open a new issue note."),
		)
	return note


def _save(note):
	note.flags.tc_issuing = True
	note.save(ignore_permissions=True)


def _clear_signature(note):
	"""Chữ ký thuộc về danh sách gói đã ký: đổi danh sách thì ký lại (C7)."""
	note.update(
		{
			"recipient": None,
			"recipient_name": None,
			"recipient_department": None,
			"dept_mismatch_reason": None,
			"sign_method": None,
			"signature": None,
			"signed_at": None,
		}
	)


def view(note):
	"""Phiếu cho màn T7: gói, người nhận, đã ký chưa và kết quả cơ số theo loại bộ (`needs_approval` khi vượt)."""
	adding = {}
	for row in note.packs:
		adding[row.set_type] = adding.get(row.set_type, 0) + 1
	par = [row for row in _par_rows(note.department, adding) if row["set_type"] in adding]
	return {
		"issue_note": note.name,
		"docstatus": note.docstatus,
		"department": note.department,
		"department_name": frappe.db.get_value("Department", note.department, "department_name"),
		"packs": [
			{
				"cycle_id": row.pack,
				"set_id": row.set_unit,
				"set_type": row.set_type,
				"set_name": row.set_name,
				"department_name": pack_display.row_of(row.pack)["department_name"],
				"expiry": getdate(row.expiry) if row.expiry else None,
				"fefo_note": row.fefo_note,
			}
			for row in note.packs
		],
		"recipient": {
			"employee": note.recipient,
			"name": note.recipient_name,
			"department": note.recipient_department,
		}
		if note.recipient
		else None,
		"dept_mismatch_reason": note.dept_mismatch_reason,
		"sign_method": note.sign_method,
		"signed": bool(note.signed_at),
		"par": par,
		"needs_approval": any(row["state"] == "over" for row in par),
	}


def create(department, station, issued_by=None, client_ts=None):
	"""Mở phiếu nháp cho khoa tại trạm T7; phiếu nháp cùng (trạm, người, khoa) đang có thì mở lại (quét tiếp)."""
	_require_station(station)
	department = _department(department)
	existing = frappe.db.get_value(
		"Issue Note",
		{
			"docstatus": 0,
			"station": station,
			"department": department,
			"issued_by_user": frappe.session.user,
		},
		"name",
		order_by="creation desc",
	)
	if existing:
		return view(_note(existing))
	note = frappe.get_doc(
		{
			"doctype": "Issue Note",
			"department": department,
			"station": station,
			"issued_by_user": frappe.session.user,
			"issued_by": issued_by,
			"client_ts": client_ts,
		}
	)
	note.flags.tc_issuing = True
	note.insert(ignore_permissions=True)
	return view(note)


def _pack_name(raw):
	scanned = gs1.parse_scan(raw)
	if scanned["type"] != "pack":
		raise _blocked(
			"SCAN_INVALID",
			_("Not a pack code"),
			_("Code {0} is not valid here.").format(scanned["raw"] or "-"),
			_("Scan the DataMatrix or the Cycle ID on the pack label."),
		)
	return storage._pack_name(scanned["id"])


def _check_issuable(pack):
	"""Gói còn cấp được (C9): Trong kho vô khuẩn, chưa quá hạn, bộ Vô khuẩn. Dùng khi thêm gói và khi ghi sổ."""
	if pack.status != IN_STOCK:
		raise _blocked(
			"PACK_NOT_IN_STOCK",
			_("Pack is not in the sterile store"),
			_("Pack {0} is {1}; only a pack in the sterile store can be issued.").format(
				pack.name, _(pack.status, context="Pack")
			),
			_("Store the pack in sterile storage first, or check its status with R02."),
			object_type="Pack",
			object_name=pack.name,
			error_code=error_codes.pack_error_code(pack),
		)
	if getdate(pack.expiry) < getdate(today()):
		raise _blocked(
			"PACK_EXPIRED",
			_("Pack has expired"),
			_("Pack {0} expired on {1}.").format(pack.name, frappe.utils.formatdate(pack.expiry)),
			_("Do not issue the pack; send it back to the dirty zone."),
			object_type="Pack",
			object_name=pack.name,
		)
	status = frappe.db.get_value("Set Unit", pack.set_unit, "status")
	if status != "Sterile":
		raise _blocked(
			"STATUS_INVALID_FOR_STATION",
			_("Set status does not match this station"),
			_("Set {0} is {1}; station {2} accepts only sets that are {3}.").format(
				pack.set_unit,
				_(status, context="Set Unit"),
				zones.function_label(FUNCTION),
				_("Sterile", context="Set Unit"),
			),
			_("Check the set status, or call R02."),
		)


def _other_draft(pack_name, note_name):
	return frappe.db.get_value(
		"Issue Note Pack",
		{"pack": pack_name, "parenttype": "Issue Note", "parent": ("!=", note_name), "docstatus": 0},
		"parent",
	)


def add_pack(issue_note, raw, station, note=None, move=False, client_ts=None, department_reason=None):
	"""Quét một gói vào phiếu nháp (C9). Quét lặp gói đã có: không lỗi, trả phiếu.

	`note`: ghi chú khi khoa chỉ định gói hạn xa hơn gói FEFO (C8). `move`: gói đang nằm ở phiếu nháp khác thì
	chuyển sang phiếu này. Đổi danh sách gói thì chữ ký cũ mất hiệu lực.
	"""
	_require_station(station)
	doc = _note(issue_note, for_update=True)
	name = _pack_name(raw)
	if any(row.pack == name for row in doc.packs):
		return view(doc)
	pack = storage._lock_pack(name)
	_check_issuable(pack)
	other = _other_draft(name, doc.name)
	if other and not cint(move):
		raise _blocked(
			"PACK_IN_OTHER_ISSUE",
			_("Pack is on another issue note"),
			_("Pack {0} is already on draft issue note {1}.").format(name, other),
			_("Move the pack to this issue note, or remove it from {0}.").format(other),
		)
	_check_pack_department(pack, doc, department_reason, station, client_ts)
	note = cstr(note).strip()
	warning = storage.fefo_check(name, exclude=[row.pack for row in doc.packs])
	if warning and not note:
		suggested = warning["suggested"]
		raise _blocked(
			"FEFO_NOTE_REQUIRED",
			warning["title"],
			warning["reason"],
			_("Issue {0} instead, or enter a note if the department asked for this Set ID.").format(
				suggested["cycle_id"]
			),
			items=[suggested["cycle_id"]],
		)
	if other:
		_drop_pack(_note(other, for_update=True), name)
	doc.append(
		"packs",
		{
			"pack": name,
			"set_unit": pack.set_unit,
			"set_type": pack.set_type,
			"set_name": pack.set_name,
			"expiry": pack.expiry,
			"fefo_note": note if warning else None,
		},
	)
	_clear_signature(doc)
	_save(doc)
	return view(doc)


def _department_name(department):
	return frappe.db.get_value("Department", department, "department_name") or department


def _check_pack_department(pack, doc, reason, station, client_ts):
	"""Gói của khoa khác khoa nhận (A-102): cảnh báo, chỉ đi tiếp khi người cấp xác nhận kèm lý do; ghi Audit Log."""
	if not pack.department or pack.department == doc.department:
		return
	reason = cstr(reason).strip()
	if not reason:
		raise _blocked(
			"PACK_DEPT_MISMATCH",
			_("Pack belongs to another department"),
			_("Pack {0} belongs to {1}; this issue note is for {2}.").format(
				pack.name, _department_name(pack.department), _department_name(doc.department)
			),
			_("Check the department. To issue it anyway, enter the reason and confirm."),
		)
	audit.log(
		"Override",
		"Pack",
		pack.name,
		new={
			"event": "PackOfOtherDepartment",
			"issue_note": doc.name,
			"pack_department": pack.department,
			"issue_department": doc.department,
			"note": reason,
		},
		reason="PackOfOtherDepartment",
		station=station,
		client_ts=client_ts,
	)


def _drop_pack(doc, cycle_id):
	rows = [row for row in doc.packs if row.pack != cycle_id]
	if len(rows) == len(doc.packs):
		return False
	doc.set("packs", rows)
	_clear_signature(doc)
	_save(doc)
	return True


def remove_pack(issue_note, cycle_id, station, client_ts=None):
	"""Bỏ một gói quét nhầm khỏi phiếu nháp; chữ ký cũ mất hiệu lực. Gói không có trong phiếu: không đổi gì."""
	_require_station(station)
	doc = _note(issue_note, for_update=True)
	_drop_pack(doc, cstr(cycle_id).strip())
	return view(doc)


# --- Người nhận và chữ ký (C7) ------------------------------------------------------------------------------


def _recipient(card):
	card = station_auth.normalize_card_id(card)
	row = (
		frappe.db.get_value(
			"Employee",
			{"tc_card_id": card},
			["name", "employee_name", "department", "status", "tc_card_enabled"],
			as_dict=True,
		)
		if card
		else None
	)
	if not row or row.status != "Active" or not cint(row.tc_card_enabled):
		raise _blocked(
			"RECIPIENT_INVALID",
			_("Recipient card is not valid"),
			_("The card does not belong to an active employee."),
			_("Ask the recipient for an active employee card, or call R02."),
		)
	return row


def _check_signature(method, signature):
	if method not in SIGN_METHODS:
		raise _blocked(
			"SIGNATURE_INVALID",
			_("Signature is not valid"),
			_("Sign method {0} is not supported.").format(method or "-"),
			_("Sign with the card or on the screen."),
		)
	if method == "Card":
		return None
	if (
		not isinstance(signature, str)
		or not signature.startswith(SIGNATURE_PREFIX)
		or len(signature) <= len(SIGNATURE_PREFIX)
		or len(signature) > SIGNATURE_MAX_LENGTH
	):
		raise _blocked(
			"SIGNATURE_INVALID",
			_("Signature is not valid"),
			_("The signature drawn on the screen is empty or too large."),
			_("Clear the signature box and ask the recipient to sign again."),
		)
	return signature


def sign(issue_note, card, station, method="Card", signature=None, reason=None, client_ts=None):
	"""Người nhận quét thẻ và ký (thẻ hoặc cảm ứng). Người nhận thuộc khoa khác: cảnh báo, tiếp tục khi có lý do."""
	_require_station(station)
	doc = _note(issue_note, for_update=True)
	if not doc.packs:
		raise _blocked(
			"ISSUE_EMPTY",
			_("No packs on the issue note"),
			_("Issue note {0} has no packs yet.").format(doc.name),
			_("Scan the packs to issue first."),
		)
	recipient = _recipient(card)
	signature = _check_signature(method, signature)
	reason = cstr(reason).strip()
	mismatch = recipient.department != doc.department
	if mismatch and not reason:
		raise _blocked(
			"RECIPIENT_DEPT_MISMATCH",
			_("Recipient is not from this department"),
			_("{0} belongs to {1}, not {2}.").format(
				recipient.employee_name or recipient.name, recipient.department or "-", doc.department
			),
			_("Enter the reason to continue, or ask a member of {0} to receive.").format(doc.department),
		)
	doc.update(
		{
			"recipient": recipient.name,
			"recipient_name": recipient.employee_name,
			"recipient_department": recipient.department,
			"dept_mismatch_reason": reason if mismatch else None,
			"sign_method": method,
			"signature": signature,
			"signed_at": now_datetime(),
		}
	)
	_save(doc)
	return view(doc)


# --- Ghi sổ (C3, C5, C6) ------------------------------------------------------------------------------------


def _approver(session, proof):
	"""User R02 đã duyệt bằng thẻ + PIN trên kiosk này (proof của ``v1.station.verify_approver``, FEAT-019); không có → None."""
	if not proof or not session:
		return None
	try:
		approver = station_auth.consume_approver_proof(session, proof)
	except BlockedError:
		return None
	return approver.user if APPROVER_ROLE in frappe.get_roles(approver.user) else None


def print_url(name):
	return "/printview?" + frappe.utils.urlencode(
		{"doctype": "Issue Note", "name": name, "format": PRINT_FORMAT, "no_letterhead": 1}
	)


def submit(issue_note, station, approver_proof=None, session=None, client_ts=None):
	"""Xác nhận phiếu đã ký: kiểm lại từng gói, cơ số khoa; ghi sổ phiếu, Pack → Issued, Set Unit → At Department.

	Vượt tối đa (`over`) cần proof R02 (`approver_proof`, từ ``v1.station.verify_approver``) gắn với phiên trạm
	`session`, nếu không → PAR_APPROVAL_REQUIRED kèm các loại bộ vượt. Khoa cấp cứu vượt trong % cho phép và khoa chưa cấu hình cơ số được cấp, ghi Audit
	`Override` (PAR_OVER_ALLOWED / PAR_UNCONFIGURED). Mọi ghi trong một savepoint: lỗi giữa chừng không đổi gì.
	Trả ``{"issue": view, "print_url"}``.
	"""
	_require_station(station)
	doc = _note(issue_note, for_update=True)
	if not doc.packs:
		raise _blocked(
			"ISSUE_EMPTY",
			_("No packs on the issue note"),
			_("Issue note {0} has no packs yet.").format(doc.name),
			_("Scan the packs to issue first."),
		)
	if not doc.signed_at or not doc.recipient:
		raise _blocked(
			"ISSUE_NOT_SIGNED",
			_("Issue note is not signed"),
			_("The recipient has not signed issue note {0}.").format(doc.name),
			_("Ask the recipient to scan the employee card and sign."),
		)
	packs = []
	for row in sorted(doc.packs, key=lambda r: r.pack):
		pack = storage._lock_pack(row.pack)
		_check_issuable(pack)
		packs.append(pack)
	current = view(doc)
	over = [row["set_type"] for row in current["par"] if row["state"] == "over"]
	approved_by = None
	if over:
		approved_by = _approver(session, approver_proof)
		if not approved_by:
			raise _blocked(
				"PAR_APPROVAL_REQUIRED",
				_("Department par level exceeded"),
				_("The department would hold more sets than its maximum for: {0}.").format(", ".join(over)),
				_("Ask R02 to scan the card and enter the PIN to approve, or remove packs."),
				items=over,
			)
	frappe.db.savepoint(SAVEPOINT)
	try:
		for pack in packs:
			pack.update({"status": ISSUED, "location": None})
			storage._save(pack)
			step_gate.issue_to_department(pack.set_unit, station)
		now = now_datetime()
		doc.update(
			{
				"par_result": frappe.as_json(current["par"]),
				"approved_by": approved_by,
				"approved_at": now if approved_by else None,
				"issued_at": now,
				"client_ts": client_ts or doc.client_ts,
			}
		)
		doc.flags.tc_issuing = True
		doc.flags.ignore_permissions = True  # người cấp đã qua phiên trạm và role cấp phát ở tầng RPC
		doc.submit()
		_log_par(doc, current["par"], approved_by, station, client_ts)
	except Exception:
		frappe.db.rollback(save_point=SAVEPOINT)
		raise
	return {"issue": view(doc), "print_url": print_url(doc.name)}


def _log_par(doc, par, approved_by, station, client_ts):
	"""Audit `Override` cho mọi loại bộ cấp ngoài cơ số: R02 duyệt, cấp cứu vượt trong %, chưa cấu hình."""
	reasons = {
		"over": "PAR_OVER_APPROVED",
		"over_allowed": "PAR_OVER_ALLOWED",
		"unconfigured": "PAR_UNCONFIGURED",
	}
	for row in par:
		reason = reasons.get(row["state"])
		if not reason:
			continue
		audit.log(
			"Override",
			"Issue Note",
			doc.name,
			new={
				key: row.get(key)
				for key in ("set_type", "stock", "adding", "after", "min", "max", "limit", "over_percent")
			}
			| ({"approved_by": approved_by} if row["state"] == "over" else {}),
			reason=reason,
			station=station,
			client_ts=client_ts,
		)
