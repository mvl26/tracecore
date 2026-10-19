"""RPC tracecore.v1.set_unit.*"""

import frappe
from frappe import _

from tracecore.core import audit, gs1
from tracecore.core.idempotency import idempotent
from tracecore.v1._payload import rejection

FIELDS = (
	"name",
	"set_type",
	"status",
	"cycles_used",
	"max_cycles",
	"active_cycle_id",
	"current_station",
	"is_loaner",
	"department",
)


def _reject(code, title, reason, action, raw):
	audit.log("Reject", reason=code, new={"raw": raw})
	return rejection(code, title, reason, action)


@frappe.whitelist(methods=["POST"])
@idempotent
def get(set_id, client_ts=None):
	"""Tra cứu Set Unit theo chuỗi quét (Set ID GIAI); mã lạ → từ chối và ghi Audit Log (FR-M9-07.3)."""
	scanned = gs1.parse_scan(set_id)
	if scanned["type"] == "unknown":
		return _reject(
			"SCAN_INVALID",
			_("Invalid code"),
			_("Code {0} was not issued by TraceCore.").format(scanned["raw"]),
			_("Rescan the set tag or call R02."),
			scanned["raw"],
		)
	if scanned["type"] != "set":
		return _reject(
			"SCAN_WRONG_TYPE",
			_("Not a set code"),
			_("Code {0} is not a Set ID.").format(scanned["id"]),
			_("Scan the Set ID on the set tag."),
			scanned["raw"],
		)

	frappe.has_permission("Set Unit", "read", throw=True)
	row = frappe.db.get_value("Set Unit", scanned["id"], FIELDS, as_dict=True)
	if not row:
		return _reject(
			"SET_NOT_FOUND",
			_("Set not found"),
			_("Set ID {0} does not exist in TraceCore.").format(scanned["id"]),
			_("Check the set tag or call R02."),
			scanned["raw"],
		)
	frappe.has_permission("Set Unit", "read", doc=row.name, throw=True)

	set_type = frappe.db.get_value("Instrument Set Type", row.set_type, ["set_type_name", "method"], as_dict=True)
	data = {key: row[key] for key in FIELDS if key != "name"}
	data.update(
		set_id=row.name,
		set_type_name=set_type.set_type_name if set_type else None,
		method=set_type.method if set_type else None,
	)
	return {"ok": True, "set_unit": data}
