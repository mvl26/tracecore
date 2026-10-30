"""RPC dashboard vận hành SCR-32 và ô quét List View (FEAT-006, FR-M9-01, FR-M9-01.1, FR-M9-01.2, FR-M9-13; A-54).

`summary` ghép khối theo vai trò (D2): mỗi khối còn cần quyền đọc DocType nguồn. Kết quả cache 30 s theo (người dùng,
bộ lọc) trong Redis (D13), ngắn hơn chu kỳ polling 60 s của Page nên lần làm mới kế tiếp luôn đọc dữ liệu mới.
"""

import hashlib
import json

import frappe
from frappe import _

from tracecore.admin_reports import dashboard as board
from tracecore.core import gs1
from tracecore.inventory import alerts as inventory_alerts
from tracecore.reprocessing import storage
from tracecore.v1 import par
from tracecore.v1._common import BadRequestError, require_any_role, server_time

ALL_ROLES = ("TC R01", "TC R02", "System Manager")
DASHBOARD_ROLES = (*ALL_ROLES, "TC R09", "TC R10")
CACHE_PREFIX = "tc_dashboard"
CACHE_SECONDS = 30
PAR_LIMIT = 50
# khối → DocType nguồn phải đọc được (D2)
BLOCK_SOURCES = {
	"sets": "Set Unit",
	"output": "Step Gate Result",
	"failures": "Sterilization Load",
	"sterile": "Pack",
	"par": "Set Unit",
	"overrides": "Par Override",
	"recalls": "Recall Order",
	"certificates": "Certificate",
	"equipment": "Equipment",
	"stock": "Item",
}
ROLE_BLOCKS = {
	"TC R09": ("sterile", "stock", "par"),
	"TC R10": ("equipment", "certificates"),
}
# D11: List View có ô quét; trường mã ngoài `name` (Set ID, mã dụng cụ, mã lô)
SCAN_DOCTYPES = {
	"Set Unit": "set_id",
	"Pack": None,
	"Sterilization Load": None,
	"Wash Batch": None,
	"Dirty Receipt": None,
	"Issue Note": None,
	"Usage Record": None,
	"Instrument": "instrument_code",
	"Equipment": "serial_no",
	"Recall Order": None,
	"Incident CAPA": None,
	"Par Override": None,
	"Item": "item_code",
	"Batch": "batch_id",
}


def clear_cache():
	frappe.cache.delete_keys(CACHE_PREFIX)


def _blocks_for(roles):
	if set(ALL_ROLES) & roles:
		wanted = list(BLOCK_SOURCES)
	else:
		wanted = [block for role, blocks in ROLE_BLOCKS.items() if role in roles for block in blocks]
	return [block for block in BLOCK_SOURCES if block in wanted and frappe.has_permission(BLOCK_SOURCES[block], "read")]


def _filters(period, zone, equipment, department):
	if period not in board.PERIODS:
		raise BadRequestError(_("period must be one of {0}.").format(", ".join(board.PERIODS)))
	if zone and not frappe.db.exists("Zone Station", {"name": zone, "is_zone": 1}):
		raise BadRequestError(_("Zone {0} does not exist.").format(zone))
	if equipment and not frappe.db.exists("Equipment", equipment):
		raise BadRequestError(_("Equipment {0} does not exist.").format(equipment))
	if department and not frappe.db.exists("Department", department):
		raise BadRequestError(_("Department {0} does not exist.").format(department))
	return {"period": period, "zone": zone or None, "equipment": equipment or None, "department": department or None}


def _sterile():
	overview = storage.overview()
	return {
		"total": sum(row["count"] for row in overview["by_set_type"]),
		"by_set_type": overview["by_set_type"],
		"expiring": overview["expiring"],
	}


def _par():
	sets = par.check(states=["warn", "blocked"], limit=PAR_LIMIT)["sets"]
	return {"count": len(sets), "rows": sets[: board.LIST_LIMIT]}


def _stock():
	overview = inventory_alerts.overview()
	return {"below_minimum": overview["below_minimum"], "expiring": overview["expiring"]}


def _build(block, start, end, filters):
	if block == "sets":
		return board.set_status_counts(filters["department"])
	if block == "output":
		return {
			"station": board.output_by_station(start, end, filters["zone"]),
			"user": board.output_by_user(start, end, filters["zone"]),
			"equipment": board.output_by_equipment(start, end, filters["zone"], filters["equipment"]),
		}
	if block == "failures":
		return board.failure_rates(start, end, filters["equipment"])
	builders = {
		"sterile": _sterile,
		"par": _par,
		"stock": _stock,
		"overrides": board.pending_overrides,
		"recalls": board.open_recalls,
		"certificates": board.expiring_certificates,
		"equipment": board.equipment_attention,
	}
	return builders[block]()


def _options():
	return {
		"zones": [
			{"value": row.name, "label": row.zone_station_name or row.name}
			for row in frappe.get_all(
				"Zone Station", filters={"is_zone": 1}, fields=["name", "zone_station_name"], order_by="name asc"
			)
		],
		"equipment": [
			{"value": row.name, "label": row.equipment_name or row.name}
			for row in frappe.get_all(
				"Equipment",
				filters={"status": ["!=", "Retired"]},
				fields=["name", "equipment_name"],
				order_by="name asc",
			)
		],
	}


@frappe.whitelist(methods=["GET"])
def summary(period="day", zone=None, equipment=None, department=None):
	"""Số liệu SCR-32 của người gọi: ``{"ok", "period", "range", "filters", "blocks", "options", "generated_at"}``.

	`blocks` chỉ chứa khối người gọi được xem (D2); không dữ liệu → 0 / danh sách rỗng (D10).
	"""
	require_any_role(*DASHBOARD_ROLES)
	filters = _filters(period, zone, equipment, department)
	digest = hashlib.sha1(json.dumps(filters, sort_keys=True).encode()).hexdigest()[:16]  # noqa: S324
	key = f"{CACHE_PREFIX}:{frappe.session.user}:{digest}"
	# khóa có hạn (setex) chỉ đọc được với expires=True: không thì Frappe v15 tra cache cục bộ và luôn trả None
	cached = frappe.cache.get_value(key, expires=True)
	if cached:
		return cached
	start, end = board.period_range(filters["period"])
	result = {
		"ok": True,
		"period": filters["period"],
		"range": [str(start), str(end)],
		"filters": filters,
		"blocks": {block: _build(block, start, end, filters) for block in _blocks_for(set(frappe.get_roles()))},
		"options": _options(),
		"generated_at": server_time(),
	}
	frappe.cache.set_value(key, result, expires_in_sec=CACHE_SECONDS)
	return result


@frappe.whitelist(methods=["GET"])
def find_in_list(doctype, code):
	"""Ô quét List View (D11): mã khớp đúng một bản ghi của `doctype` → ``name`` để mở form; không → ``name: None``.

	``code`` trả lại là mã đã làm sạch (bỏ AIM/FNC1, AI 8004 hoặc nhãn gói → Set ID / Cycle ID) và ``field`` là trường
	mã để client lọc danh sách khi không khớp đúng một bản ghi.
	"""
	if doctype not in SCAN_DOCTYPES:
		raise BadRequestError(_("Scanning is not available for {0}.").format(doctype))
	if not isinstance(code, str) or not gs1.clean_scan(code):
		raise BadRequestError(_("code must be a non-empty scanned code."))
	frappe.has_permission(doctype, "read", throw=True)
	parsed = gs1.parse_scan(code)
	value = parsed["id"] if parsed["type"] in ("set", "pack", "instrument") else gs1.clean_scan(code)
	value = value[: gs1.MAX_SCAN_LENGTH]
	field = SCAN_DOCTYPES[doctype]
	matches = frappe.get_list(doctype, filters={"name": value}, pluck="name", limit=2)
	if not matches and field:
		matches = frappe.get_list(doctype, filters={field: value}, pluck="name", limit=2)
	return {"ok": True, "name": matches[0] if len(matches) == 1 else None, "code": value, "field": field or "name"}
