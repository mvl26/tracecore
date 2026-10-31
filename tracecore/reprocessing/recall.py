"""Thu hồi theo mẻ / lô chỉ thị (M2, FEAT-029, UC-14, FR-M2-20, FR-M2-11.7, BRU-REP-007, WF-05).

Lệnh thu hồi gom mọi gói đã giải phóng trở đi của một mẻ (hoặc của mọi mẻ có chỉ thị dùng một lô), không nhập tay:
gói còn ở CSSD bị khóa (Pack ``Recalled``, bộ về Chờ tiếp nhận), gói đã cấp bị khóa ở khoa (``Recalled``, T8 chặn) chờ
khoa trả, gói đã dùng giữ nguyên và chờ R01 báo bác sĩ (mã bệnh nhân chỉ ở dạng che). Từng dòng được xác nhận theo đúng
vai trò; đóng lệnh khi 100 % dòng đã xác nhận. Lệnh luôn gắn một Incident CAPA (FEAT-030).

Đổi trạng thái Set Unit chỉ qua ``core.step_gate`` (ADR-005); Pack đổi qua ``storage._save`` như các dịch vụ kho.
Thông báo là chuông Desk (Notification Log); email/SMS và PDA thuộc FEAT-010/FEAT-009.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cstr, get_datetime, now_datetime

from tracecore.core import notification, step_gate
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import incidents, storage, trace, usage

DOCTYPE = "Recall Order"
FLAG = "tc_recall"
R01, R02, R06, R08 = "TC R01", "TC R02", "TC R06", "TC R08"
RECALLABLE = ("Released", "In Sterile Stock", "Issued", "Used")
LOCK, RETURN, NOTIFY = "Lock in Stock", "Return from Department", "Notify Physician"
REMIND_AFTER_HOURS = 2


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _not_allowed(reason):
	return _blocked(
		"RECALL_NOT_ALLOWED", _("Not allowed"), reason, _("Ask the person responsible to do this step.")
	)


def _has(*roles, user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(roles))


def _users_with(role):
	holders = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
	if not holders:
		return []
	return frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1}, pluck="name")


def _department_users(departments):
	"""Người dùng R08 đang hoạt động có Employee thuộc các khoa `departments`."""
	if not departments:
		return []
	users = frappe.get_all(
		"Employee",
		filters={"department": ["in", list(departments)], "status": "Active", "user_id": ["is", "set"]},
		pluck="user_id",
	)
	ward = set(_users_with(R08))
	return [user for user in users if user in ward]


def _notify(users, subject, doc):
	"""Thu hồi là sự kiện khẩn (UC-38 E3): chưa đọc sau 15 phút thì leo thang email/SMS cho R01."""
	notification.emit("RECALL_ORDER", doc, subject, users=users)


# --- Lập lệnh -----------------------------------------------------------------------------------------


def _loads_of_lot(lot):
	# chỉ thị rửa (A-257) không gắn mẻ: lệnh thu hồi theo lô chỉ thị chỉ áp cho mẻ tiệt khuẩn
	return frappe.get_all(
		"Load Indicator Result", filters={"lot": lot, "load": ("is", "set")}, pluck="load", distinct=True
	)


def _open_order(load=None, lot=None):
	filters = {"docstatus": 0}
	if load:
		filters["sterilization_load"] = load
	else:
		filters["indicator_lot"] = lot
	return frappe.db.get_value(DOCTYPE, filters, "name")


def _line(pack):
	"""Dòng lệnh cho một Pack; khóa gói chưa dùng (Pack Recalled, bộ ở CSSD về Chờ tiếp nhận)."""
	row = {
		"pack": pack.name,
		"set_unit": pack.set_unit,
		"load": pack.load,
		"status_at_recall": pack.status,
		"wash_indicator": trace.wash_indicator_text(
			pack.set_unit, frappe.db.get_value("Pack", pack.name, "cycle_no")
		),
	}
	if pack.status == "Used":
		name = frappe.db.get_value("Usage Record", {"pack": pack.name}, "name")
		used = frappe.get_doc("Usage Record", name) if name else None  # mã che là thuộc tính ảo, không có cột
		row.update(
			{
				"action": NOTIFY,
				"usage_record": name,
				"patient_code_masked": used.patient_code_masked if used else None,
				"department": used.department if used else None,
			}
		)
		return row
	locked = storage._lock_pack(pack.name)
	if pack.status == "Issued":
		row.update({"action": RETURN, "department": usage._pack_department(locked)})
	else:
		row["action"] = LOCK
	locked.update({"status": "Recalled", "location": None})
	storage._save(locked)
	if frappe.db.get_value("Set Unit", pack.set_unit, "status") == "Sterile":
		step_gate.return_to_receipt(pack.set_unit)
	return row


def _incident(doc, loads):
	"""NC liên kết (UC-14 bước 6): NC Mẻ không đạt sẵn có của mẻ, nếu không thì tự tạo mức High."""
	existing = frappe.db.get_value(
		"Incident CAPA", {"sterilization_load": ["in", loads], "incident_type": "Load Failed"}, "name"
	)
	if existing:
		return existing
	return incidents.create(
		{
			"incident_type": "Load Failed",
			"severity": "High",
			"description": _("Recall {0}: {1}").format(doc.name, doc.reason),
			"sterilization_load": loads[0],
			"source_doctype": DOCTYPE,
			"source_name": doc.name,
		},
		auto=True,
	).name


def create(load=None, lot=None, reason=None, trigger="Opened Manually", hook=False):
	"""Lập lệnh thu hồi theo mẻ `load` hoặc lô chỉ thị `lot` (FR-M2-20); R01/R02, hoặc hook hệ thống."""
	if not hook and not _has(R01, R02):
		raise _not_allowed(_("Only R01 or R02 can open a recall order."))
	reason = cstr(reason).strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason was entered for the recall."),
			_("Enter why the packs are recalled."),
		)
	existing = _open_order(load, lot)
	if existing:
		if hook:
			return frappe.get_doc(DOCTYPE, existing)
		raise _blocked(
			"RECALL_EXISTS",
			_("Recall already open"),
			_("Recall order {0} is still open for this load or lot.").format(existing),
			_("Open the existing recall order."),
		)
	loads = [load] if load else _loads_of_lot(lot)
	packs = (
		frappe.get_all(
			"Pack",
			filters={"load": ["in", loads], "status": ["in", RECALLABLE], "docstatus": 1},
			fields=["name", "set_unit", "status", "load"],
			order_by="name asc",
		)
		if loads
		else []
	)
	if not packs:
		raise _blocked(
			"RECALL_EMPTY",
			_("Nothing to recall"),
			_("No released, stored, issued or used pack belongs to this load or lot."),
			_("Check the load or lot code."),
		)
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"trigger": trigger,
			"sterilization_load": load,
			"indicator_lot": lot,
			"reason": reason,
			"status": "Open",
			"opened_by": frappe.session.user,
			"opened_at": now_datetime(),
			"packs": [_line(pack) for pack in packs],
		}
	)
	doc.pack_count = len(doc.packs)
	doc.confirmed_count = 0
	doc.flags[FLAG] = True
	doc.insert(ignore_permissions=True)
	doc.incident = _incident(doc, loads)
	_save(doc)
	departments = {row.department for row in doc.packs if row.department}
	users = _users_with(R01) + _users_with(R02) + _department_users(departments)
	_notify(users, _("Recall {0}: {1} pack(s) affected").format(doc.name, doc.pack_count), doc)
	return doc


def _save(doc, submit=False):
	doc.flags[FLAG] = True
	doc.flags.ignore_permissions = True
	if submit:
		doc.submit()
	else:
		doc.save()
	return doc


def guard_changes(doc):
	if not doc.flags.get(FLAG):
		frappe.throw(_("Recall orders change only through the recall actions."), frappe.ValidationError)


def guard_submit(doc):
	if not doc.flags.get(FLAG) or doc.status != "Closed":
		frappe.throw(_("Close the recall order with its action, not by submitting it."))


def guard_cancel(doc):
	frappe.throw(_("A closed recall order cannot be cancelled."))


# --- Xác nhận và đóng ---------------------------------------------------------------------------------


def _order(name):
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)
	if doc.docstatus != 0:
		raise _blocked(
			"RECALL_NOT_OPEN",
			_("Recall is closed"),
			_("Recall order {0} is already closed.").format(doc.name),
			_("Open a new recall order if more packs are affected."),
		)
	return doc


def _may_confirm(row):
	if row.action == LOCK:
		return _has(R02, R06)
	if row.action == NOTIFY:
		return _has(R01)
	if _has(R02):
		return True
	if not _has(R08):
		return False
	department = frappe.db.get_value(
		"Employee", {"user_id": frappe.session.user, "status": "Active"}, "department"
	)
	return bool(department) and department == row.department


def confirm_pack(name, pack, note=None):
	"""Xác nhận một dòng: khóa trong kho (R02/R06), khoa đã trả (R02 / R08 đúng khoa), đã báo bác sĩ (R01)."""
	doc = _order(name)
	row = next((row for row in doc.packs if row.pack == pack), None)
	if not row:
		raise _blocked(
			"RECALL_PACK_NOT_FOUND",
			_("Pack is not in this recall"),
			_("Pack {0} is not part of recall order {1}.").format(pack, doc.name),
			_("Scan a pack listed in the recall order."),
		)
	if row.line_status == "Confirmed":
		raise _blocked(
			"RECALL_LINE_DONE",
			_("Already confirmed"),
			_("Pack {0} was confirmed by {1}.").format(pack, row.confirmed_by),
			_("Continue with the next pack."),
		)
	if not _may_confirm(row):
		raise _not_allowed(_("Your role cannot confirm this pack ({0}).").format(_(row.action)))
	row.update(
		{
			"line_status": "Confirmed",
			"confirmed_by": frappe.session.user,
			"confirmed_at": now_datetime(),
			"note": cstr(note).strip() or None,
		}
	)
	doc.confirmed_count = sum(1 for line in doc.packs if line.line_status == "Confirmed")
	return _save(doc)


def close(name):
	"""Đóng lệnh (ghi sổ): chỉ R01/R02, khi 100 % gói đã xác nhận (FR-M2-20.2)."""
	if not _has(R01, R02):
		raise _not_allowed(_("Only R01 or R02 can close a recall order."))
	doc = _order(name)
	pending = [row.pack for row in doc.packs if row.line_status != "Confirmed"]
	if pending:
		raise _blocked(
			"RECALL_INCOMPLETE",
			_("Packs are not all confirmed"),
			_("{0} of {1} pack(s) are still waiting: {2}.").format(
				len(pending), len(doc.packs), ", ".join(pending)
			),
			_("Confirm every pack before closing the recall."),
		)
	doc.update({"status": "Closed", "closed_by": frappe.session.user, "closed_at": now_datetime()})
	return _save(doc, submit=True)


# --- Hook và nhắc -------------------------------------------------------------------------------------


def _from_hook(ctx, trigger, reason):
	try:
		return create(load=ctx["load"], reason=reason, trigger=trigger, hook=True).name
	except BlockedError as error:
		if error.block.code == "RECALL_EMPTY":
			return None
		raise


def on_bi_positive(ctx):
	"""Hook ``tracecore_bi_positive``: BI dương tính sau giải phóng → lệnh thu hồi (FR-M2-11.7)."""
	return _from_hook(ctx, "BI Positive", _("Biological indicator positive after release"))


def on_load_failed(ctx):
	"""Hook ``tracecore_after_load_failed``: mẻ Không đạt có gói đã giải phóng → lệnh thu hồi (FR-M2-12.2)."""
	return _from_hook(ctx, "Load Failed", _("Sterilization load failed"))


def remind_pending():
	"""Job 15 phút: lệnh mở quá 2 giờ còn dòng chờ → nhắc khoa liên quan và R01, mỗi lệnh tối đa một lần / 2 giờ."""
	cutoff = add_to_date(now_datetime(), hours=-REMIND_AFTER_HOURS)
	count = 0
	for name in frappe.get_all(DOCTYPE, filters={"docstatus": 0, "opened_at": ["<=", cutoff]}, pluck="name"):
		doc = frappe.get_doc(DOCTYPE, name)
		if doc.last_reminded_at and get_datetime(doc.last_reminded_at) > cutoff:
			continue
		pending = [row for row in doc.packs if row.line_status != "Confirmed"]
		if not pending:
			continue
		departments = {row.department for row in pending if row.department}
		subject = _("Recall {0}: {1} pack(s) still waiting for confirmation").format(doc.name, len(pending))
		_notify(_department_users(departments) + _users_with(R01), subject, doc)
		frappe.db.set_value(DOCTYPE, doc.name, "last_reminded_at", now_datetime(), update_modified=False)
		count += 1
	return count
