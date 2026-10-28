"""RPC tracecore.v1.account.* — đặt PIN trạm cho nhân viên từ form Employee trên Desk (FR-M9-09.1, UC-33 A3).

Quy tắc nằm ở `core.account.reset_pin_on_desk`. Lỗi nghiệp vụ trả body ``ok: false`` (Audit Log ``Reject``), không ném.
"""

import frappe

from tracecore.core import account
from tracecore.core.errors import BlockedError
from tracecore.v1._common import reject_block


@frappe.whitelist(methods=["POST"])
def set_station_pin(employee, new_pin, supervisor_pin=None):
	"""Đặt PIN tạm 6 số cho `employee`; R02 kèm `supervisor_pin` là PIN trạm của chính mình. Nhân viên phải đổi PIN ở
	lần quẹt thẻ kế tiếp. Trả ``{"ok", "employee", "pin_change_required"}``."""
	try:
		account.reset_pin_on_desk(employee, new_pin, supervisor_pin)
	except BlockedError as error:
		return reject_block(error.block, "Employee", employee)
	return {"ok": True, "employee": employee, "pin_change_required": 1}
