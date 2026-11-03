"""R02 hủy lô rửa / mẻ tiệt khuẩn nhập sai (A-112 D10, D11; FR-M2-03.10, FR-M2-09.10, BRU-REP-018).

* Lô rửa Đang chạy, Chờ kết quả hoặc Đạt, chưa bộ nào qua T3 (cổng T3 Đạt hoặc đã mở kiểm tra lắp ráp): lô Đạt trả cổng T2
  của các bộ về Chưa; bộ đợi rửa lại.
* Mẻ Đang chạy, Xong chu trình, Cách ly chờ BI hoặc Đã giải phóng, chưa gói nào nhập kho vô khuẩn, cấp phát, dùng, thu hồi
  hay hết hiệu lực: mẻ đã giải phóng trả cổng T5 về Chưa và trừ lại chu trình đã cộng (``step_gate.revert``), hook
  `tracecore_after_release_cancel` cho M1 trừ lại bộ đếm bảo dưỡng; gói về Đã đóng gói, chờ nạp mẻ khác.
* Lô/mẻ Không đạt không hủy (đã có NC, thu hồi). Qua mốc trên → ``RUN_CANCEL_BLOCKED`` (409) kèm bộ/gói đã đi tiếp.
* Hook `tracecore_after_wash_cancel` / `tracecore_after_load_cancel` (cùng transaction, chạy trước khi đóng chứng từ):
  M6 hủy phiếu xuất tiêu hao (còn phiếu Nháp thì từ chối), M7 đánh dấu Cost Sheet Đã hủy.
* Chứng từ đã ghi sổ được hủy bằng ``cancel()``; bản Nháp (lô/mẻ chưa có kết quả) chuyển thẳng ``docstatus = 2`` vì Frappe
  không hủy bản Nháp. Lý do và người hủy lưu ở `cancel_reason`, `cancelled_by`; Audit Log ``Cancel``.
"""

import frappe
from frappe import _

from tracecore.core import audit, extension, step_gate
from tracecore.core.errors import Block, BlockedError
from tracecore.reprocessing import storage

WASH, LOAD = "Wash Batch", "Sterilization Load"
CANCEL_ROLES = ("TC R02", "System Manager")
WASH_CANCELLABLE = ("Running", "Awaiting Result", "Passed")
LOAD_CANCELLABLE = ("Running", "Cycle Complete", "Quarantine", "Released")
LOAD_PACK_STATUSES = ("In Load", "Quarantine", "Released")  # gói còn nằm ở mẻ, chưa đi tiếp
PACKED = "Packed"
AFTER_WASH_CANCEL_HOOK = "tracecore_after_wash_cancel"
AFTER_LOAD_CANCEL_HOOK = "tracecore_after_load_cancel"
AFTER_RELEASE_CANCEL_HOOK = "tracecore_after_release_cancel"
CHILD_TABLES = {
	WASH: ("Wash Batch Set Unit", "Wash Batch Chemical", "Run Consumable"),
	LOAD: ("Load Pack", "Run Consumable"),
}


def _blocked(reason, items=None):
	return BlockedError(
		Block(
			"RUN_CANCEL_BLOCKED",
			_("Cannot cancel"),
			reason,
			_("Handle the sets or packs that moved on through recall or a manual correction."),
			items=items,
		)
	)


def _desk_employee():
	"""Nhân viên gắn với tài khoản Desk đang hủy (người hủy ghi trên chứng từ); không có → None."""
	return frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "name")


def _check_caller(reason):
	if not set(CANCEL_ROLES) & set(frappe.get_roles()):
		raise frappe.PermissionError(_("Only R02 can cancel a wash batch or a sterilization load."))
	reason = (reason or "").strip() if isinstance(reason, str) else ""
	if not reason:
		raise BlockedError(
			Block(
				"REASON_REQUIRED",
				_("Reason required"),
				_("Enter why the batch or load is cancelled."),
				_("Enter the reason, then cancel again."),
			)
		)
	return reason


def _close(doc, reason, employee):
	"""Đóng chứng từ: ghi sổ thì ``cancel()``, Nháp thì ``docstatus = 2`` cho cả bảng con; lưu lý do, người hủy."""
	values = {"cancel_reason": reason, "cancelled_by": employee}
	frappe.db.set_value(doc.doctype, doc.name, values, update_modified=False)
	if doc.docstatus == 1:
		doc.reload()
		doc.flags.update(tc_run_cancel=True, tc_audit_reason=reason, ignore_permissions=True)
		doc.cancel()
		return
	frappe.db.set_value(doc.doctype, doc.name, "docstatus", 2)
	for child in CHILD_TABLES[doc.doctype]:
		frappe.db.sql(
			f"update `tab{child}` set docstatus = 2 where parent = %s and parenttype = %s",  # nosec B608 - bảng con từ hằng CHILD_TABLES
			(doc.name, doc.doctype),
		)
	audit.log("Cancel", doc.doctype, doc.name, new={"status": doc.status, **values}, reason=reason)


def _ensure_open(doc, cancellable):
	if doc.docstatus == 2:
		raise _blocked(_("{0} {1} has already been cancelled.").format(_(doc.doctype), doc.name))
	if doc.status not in cancellable:
		raise _blocked(
			_("{0} {1} is {2}: only a run that has not failed can be cancelled.").format(
				_(doc.doctype), doc.name, _(doc.status)
			)
		)


def _assembly_opened(set_unit):
	cycle_no = frappe.db.get_value("Set Unit", set_unit, "current_cycle_no")
	return frappe.db.exists(
		"Assembly Record", {"set_unit": set_unit, "cycle_no": cycle_no, "docstatus": ["<", 2]}
	)


def cancel_wash(batch, reason, employee=None):
	"""Hủy lô rửa nhập sai; trả ``{"batch", "sets"}``."""
	reason = _check_caller(reason)
	doc = frappe.get_doc(WASH, batch, for_update=True)
	_ensure_open(doc, WASH_CANCELLABLE)
	sets = [row.set_unit for row in doc.set_units]
	moved = [unit for unit in sets if step_gate.passed_after(unit, "T2") or _assembly_opened(unit)]
	if moved:
		raise _blocked(_("These sets have already reached assembly: {0}.").format(", ".join(moved)), moved)
	if doc.docstatus == 1:
		for unit in sets:
			step_gate.revert(unit, "T2", WASH, doc.name, reason)
	extension.run(
		AFTER_WASH_CANCEL_HOOK,
		{
			"batch": doc.name,
			"equipment": doc.equipment,
			"program": doc.program,
			"sets": sets,
			"reason": reason,
		},
	)
	_close(doc, reason, employee or _desk_employee())
	return {"batch": doc.name, "sets": sets}


def cancel_load(load, reason, employee=None):
	"""Hủy mẻ tiệt khuẩn nhập sai; trả ``{"load", "packs"}``."""
	reason = _check_caller(reason)
	doc = frappe.get_doc(LOAD, load, for_update=True)
	_ensure_open(doc, LOAD_CANCELLABLE)
	packs = [row.pack for row in doc.packs]
	moved = [
		pack
		for pack in packs
		if frappe.db.get_value("Pack", pack, "status") not in LOAD_PACK_STATUSES
		or frappe.db.exists("Sterile Putaway", {"pack": pack, "docstatus": 1})
		or frappe.db.exists("Issue Note Pack", {"pack": pack, "docstatus": ["<", 2]})
	]
	if moved:
		raise _blocked(
			_("These packs have already left the load (stored, issued, used or void): {0}.").format(
				", ".join(moved)
			),
			moved,
		)
	released = doc.docstatus == 1
	for row in doc.packs:
		pack = storage._lock_pack(row.pack)
		if released:
			step_gate.revert(row.set_unit, "T5", LOAD, doc.name, reason, uncount=True)
			extension.run(AFTER_RELEASE_CANCEL_HOOK, {"set_unit": row.set_unit, "cycle_id": pack.name})
		pack.update({"status": PACKED, "load": None})
		storage._save(pack)
	extension.run(
		AFTER_LOAD_CANCEL_HOOK,
		{
			"load": doc.name,
			"equipment": doc.equipment,
			"program": doc.program,
			"packs": packs,
			"reason": reason,
		},
	)
	_close(doc, reason, employee or _desk_employee())
	return {"load": doc.name, "packs": packs}
