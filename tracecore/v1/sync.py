"""RPC tracecore.v1.sync.* — đồng bộ offline của trạm/PDA (FEAT-009, ADR-003, A-40 D5).

Phát lại không có RPC riêng: kiosk gọi lại RPC gốc với header ``X-TC-Replay: 1`` (xem `core.sync`).
"""

import frappe

from tracecore.core import sync


@frappe.whitelist(methods=["POST"])
def resolve(name, note=None):
	"""R02/R01 đóng một Sync Conflict kèm cách xử lý (Desk, SCR-33)."""
	return {"ok": True, "name": sync.resolve(name, note)}
