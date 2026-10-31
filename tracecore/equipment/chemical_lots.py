"""Lô hóa chất đang dùng trên máy (FEAT-052, A-71, FR-M5-07): HC-001, HC-002, HC-003.

Chỉ áp dụng cho loại máy có cờ `Equipment Type Norm.requires_chemical_lot`. Kết quả tính khi kiểm tra máy, không ghi
`Equipment.status`: thay lô là tự hết, không lẫn với Khóa do test ngày, và `unlock_temp` không bỏ qua được.
"""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, formatdate, getdate, now_datetime, today

from tracecore.core import error_codes
from tracecore.core.errors import Block, BlockedError

CHEMICAL_GROUP = "Chemical"
EXPIRED, EXPIRING, MISSING = "HC-001", "HC-002", "HC-003"


def requires_lot(equipment_type) -> bool:
	return bool(cint(frappe.db.get_value("Equipment Type Norm", equipment_type, "requires_chemical_lot")))


def declared_lots(equipment) -> list:
	return frappe.get_all(
		"Equipment Chemical Lot",
		filters={"parent": equipment, "parenttype": "Equipment"},
		fields=["item", "lot"],
		order_by="idx asc",
	)


def _expiry(lot):
	value = frappe.db.get_value("Batch", lot, "expiry_date")
	return getdate(value) if value else None


def _expired_block(equipment, lot, expiry):
	return Block(
		"CHEMICAL_LOT_EXPIRED",
		_("Chemical lot has expired"),
		_("Machine {0} is using lot {1}, which expired on {2}.").format(equipment, lot, formatdate(expiry)),
		_("Load a valid lot, then scan the lot code here."),
		object_type="Equipment",
		object_name=equipment,
		object_label=f"{equipment} / {lot}",
	)


def _expiring_block(equipment, lot, expiry):
	return Block(
		"CHEMICAL_LOT_EXPIRING",
		_("Chemical lot expires soon"),
		_("Machine {0} is using lot {1}, which expires on {2}.").format(equipment, lot, formatdate(expiry)),
		_("Ask the stores for a replacement lot in time."),
		object_type="Equipment",
		object_name=equipment,
		object_label=f"{equipment} / {lot}",
	)


def chemical_block(equipment, equipment_type) -> Block | None:
	"""Block HC-001/HC-003 nếu máy không chạy được; HC-002 là cảnh báo trừ khi viện cấu hình Chặn."""
	if not requires_lot(equipment_type):
		return None
	lots = declared_lots(equipment)
	if not lots:
		return Block(
			"EQUIPMENT_NO_CHEMICAL_LOT",
			_("Machine has no declared chemical lot"),
			_("Machine {0} needs a chemical lot, and none is declared.").format(equipment),
			_("Scan the code of the lot loaded on the machine."),
			object_type="Equipment",
			object_name=equipment,
		)
	error_codes.mark_resolved(MISSING, "Equipment", equipment)
	expiries = [(row.lot, _expiry(row.lot)) for row in lots]
	for lot, expiry in expiries:
		if not expiry or expiry < getdate(today()):
			return _expired_block(equipment, lot, expiry or today())
	error_codes.mark_resolved(EXPIRED, "Equipment", equipment)
	rule = error_codes.rule_of(EXPIRING)
	days = rule["warn_days"] if rule else 0
	for lot, expiry in expiries:
		if date_diff(expiry, today()) <= days:
			block = error_codes.check(_expiring_block(equipment, lot, expiry))
			if block:
				return block
	return None


def _invalid(reason):
	return BlockedError(
		Block(
			"CHEMICAL_LOT_INVALID",
			_("Chemical lot is not valid"),
			reason,
			_("Scan the lot of a chemical that is still valid."),
		)
	)


def declare(equipment, lot, client_ts=None) -> dict:
	"""Khai lô đang dùng trên máy; mỗi hóa chất giữ một lô, khai lô mới thay lô cũ. Lô hết hạn bị từ chối."""
	batch = frappe.db.get_value("Batch", lot, ["name", "item", "expiry_date", "disabled"], as_dict=True)
	if not batch or frappe.db.get_value("Item", batch.item, "tc_item_group_cssd") != CHEMICAL_GROUP:
		raise _invalid(_("Lot {0} is not a chemical lot.").format(lot or "-"))
	if cint(batch.disabled):
		raise _invalid(_("Lot {0} has been disabled.").format(batch.name))
	if not batch.expiry_date:
		raise _invalid(_("Lot {0} has no expiry date, so it cannot be checked.").format(batch.name))
	if getdate(batch.expiry_date) < getdate(today()):
		raise BlockedError(_expired_block(equipment, batch.name, batch.expiry_date))
	doc = frappe.get_doc("Equipment", equipment, for_update=True)
	doc.flags.tc_equipment = True
	row = next((item for item in doc.chemical_lots if item.item == batch.item), None)
	values = {
		"item": batch.item,
		"lot": batch.name,
		"declared_by": frappe.session.user,
		"declared_at": now_datetime(),
	}
	if row:
		row.update(values)
	else:
		doc.append("chemical_lots", values)
	doc.save(ignore_permissions=True)
	block = chemical_block(equipment, doc.equipment_type)
	return {"equipment": equipment, "lot": batch.name, "item": batch.item, "cleared": not block}


def default_rows(equipment, item) -> list[dict]:
	"""Hàm hook `tracecore_equipment_chemical_lots`: lô đã khai của `item` để điền sẵn vào lô rửa."""
	return [
		{"item": row.item, "lot": row.lot, "qty": 0} for row in declared_lots(equipment) if row.item == item
	]
