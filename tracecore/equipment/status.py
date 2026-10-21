"""Trạng thái thiết bị (WF-07, Q5): nơi duy nhất đổi ``Equipment.status``.

``Locked``/``Repair`` do FEAT-039/040 dùng; FEAT-038 dùng ``Retired`` (ngừng sử dụng, một chiều).
Audit Log Update (old/new ``status``) do hook doc_events của Equipment ghi.
"""

import frappe
from frappe import _

STATUSES = ("Ready", "Locked", "Repair", "Retired")


def set_status(equipment: str, status: str, reason: str | None = None) -> None:
	"""Đặt trạng thái thiết bị; ``Retired`` cần lý do và không quay lại được."""
	if status not in STATUSES:
		frappe.throw(_("Invalid equipment status {0}.").format(status))
	doc = frappe.get_doc("Equipment", equipment, for_update=True)
	if doc.status == status:
		return
	if doc.status == "Retired":
		frappe.throw(_("Retired equipment cannot be put back into use."))
	if status == "Retired":
		reason = (reason or "").strip()
		if not reason:
			frappe.throw(_("A reason is required to retire equipment."))
		doc.retired_reason = reason
		doc.retired_on = frappe.utils.today()
	doc.status = status
	doc.flags.tc_equipment = True
	doc.save(ignore_permissions=True)
