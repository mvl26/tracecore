"""RPC tracecore.v1.audit.* — tra cứu Audit Log (theo permission người gọi)."""

import frappe
from frappe.utils import cint

MAX_LIMIT = 500
FIELDS = [
	"name",
	"timestamp",
	"user",
	"station",
	"device",
	"action",
	"ref_doctype",
	"ref_name",
	"reason",
	"old_value",
	"new_value",
	"request_id",
	"client_ts",
]


@frappe.whitelist()
def query(ref_doctype=None, ref_name=None, user=None, station=None, from_ts=None, to_ts=None, limit=50):
	filters = {
		key: value
		for key, value in (
			("ref_doctype", ref_doctype),
			("ref_name", ref_name),
			("user", user),
			("station", station),
		)
		if value
	}
	if from_ts and to_ts:
		filters["timestamp"] = ("between", [from_ts, to_ts])
	elif from_ts:
		filters["timestamp"] = (">=", from_ts)
	elif to_ts:
		filters["timestamp"] = ("<=", to_ts)
	limit = min(cint(limit) or 50, MAX_LIMIT)
	return frappe.get_list(
		"Audit Log",
		filters=filters,
		fields=FIELDS,
		order_by="timestamp desc, name desc",
		limit_page_length=limit,
	)
