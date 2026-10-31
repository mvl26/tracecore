"""RPC tracecore.v1.equipment.*: tra thiết bị theo mã QR và chương trình đang dùng (FR-M5-02.2, FEAT-038).

`get` chỉ đọc, không `@idempotent`; `declare_chemical_lot` ghi nên có (A-71). Từ chối nghiệp vụ qua `reject_block` (Audit Log `Reject`); thiết bị đã ngừng sử dụng
là cảnh báo trong body thành công chứ không phải lỗi HTTP.
"""

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core.client_time import parse_client_ts
from tracecore.core.errors import Block
from tracecore.core.idempotency import idempotent
from tracecore.equipment import chemical_lots, programs
from tracecore.v1._common import reject_block, require_any_role, station_session
from tracecore.v1.wash import _required_str, _run

FIELDS = (
	"name",
	"equipment_name",
	"equipment_type",
	"status",
	"zone_in",
	"zone_out",
	"is_connected",
	"has_printout",
	"capacity",
)


@frappe.whitelist(methods=["POST"])
def get(qr, client_ts=None):
	"""Tra thiết bị theo mã QR (``TB-####``): thông tin máy và chương trình đang dùng."""
	# kiểm quyền trước mọi thao tác ghi (Audit Log Reject)
	frappe.has_permission("Equipment", "read", throw=True)
	scanned = gs1.parse_scan(qr)
	if scanned["type"] != "equipment":
		return reject_block(
			Block(
				"SCAN_INVALID",
				_("Invalid code"),
				_("Code {0} is not an equipment code.").format(scanned["raw"] or "-"),
				_("Scan the QR code on the equipment."),
			),
			raw=scanned["raw"],
			client_ts=client_ts,
		)
	row = frappe.db.get_value("Equipment", scanned["id"], FIELDS, as_dict=True)
	if not row:
		return reject_block(
			Block(
				"EQUIPMENT_NOT_FOUND",
				_("Equipment not found"),
				_("Equipment {0} does not exist in TraceCore.").format(scanned["id"]),
				_("Check the QR code on the equipment or call R10."),
			),
			raw=scanned["raw"],
			client_ts=client_ts,
		)
	retired = row.status == "Retired"
	warning = None
	if retired:
		warning = {
			"code": "EQUIPMENT_RETIRED",
			"title": _("Equipment retired"),
			"reason": _("Equipment {0} is retired and has no process programs in use.").format(row.name),
			"action": _("Choose another machine or call R10."),
		}
	return {
		"ok": True,
		"equipment": {field: row[field] for field in FIELDS},
		"programs": [] if retired else programs.active_programs(row.name),
		"warning": warning,
	}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@station_session("TC R03", "TC R05", "TC R02", "System Manager")
@idempotent
def declare_chemical_lot(equipment, lot, station, client_ts=None, token=None):
	"""Khai lô hóa chất đang dùng trên máy ở T2 (FEAT-052, A-71, FR-M5-07): giải HC-001/HC-003."""
	require_any_role("TC R03", "TC R05", "TC R02", "System Manager")
	equipment = _required_str(equipment, "equipment")
	lot = _required_str(lot, "lot")
	timestamp = parse_client_ts(client_ts)
	return _run(
		station,
		timestamp,
		lambda: {"ok": True, **chemical_lots.declare(equipment, lot, timestamp)},
		"Equipment",
		equipment,
	)
