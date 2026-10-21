"""RPC tracecore.v1.equipment.*: tra thiết bị theo mã QR và chương trình đang dùng (FR-M5-02.2, FEAT-038).

Chỉ đọc, không `@idempotent`. Từ chối nghiệp vụ qua `reject_block` (Audit Log `Reject`); thiết bị đã ngừng sử dụng
là cảnh báo trong body thành công chứ không phải lỗi HTTP.
"""

import frappe
from frappe import _

from tracecore.core import gs1
from tracecore.core.errors import Block
from tracecore.equipment import programs
from tracecore.v1._common import reject_block

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
