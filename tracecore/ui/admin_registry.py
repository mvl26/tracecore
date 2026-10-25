"""Navigation contracts for the independent TraceCore administration UI."""
# ruff: noqa: RUF001 -- labels keep the en dash of the source document.
# Labels are English source strings; admin_ui translates them per request with context "TraceCore Admin"
# (translations/vi.csv), never at import time.

ROLES = {
	"R01": (
		"Head of infection control",
		"Approvals, monitoring and reports",
		[
			"dashboard",
			"overrides",
			"recalls",
			"incidents",
			"costs",
			"equipment",
			"people",
			"sterilization-book",
		],
	),
	"R02": (
		"CSSD supervisor",
		"Shift coordination and exceptions",
		["dashboard", "loads", "instruments", "set-types", "set-units", "competencies", "incidents", "sync"],
	),
	"R03": ("Dirty zone technician", "Receiving and washing–disinfection", ["receipts", "wash-batches"]),
	"R04": (
		"Clean zone technician",
		"Inspection, assembly and packing",
		["assembly", "packs", "instruments", "overrides"],
	),
	"R05": (
		"Sterilization technician",
		"Daily tests, operation and unloading",
		["equipment", "daily-tests", "loads"],
	),
	"R06": (
		"Sterile store / issuing",
		"Locations, FEFO and issuing to departments",
		["putaways", "sterile-stock", "issues"],
	),
	"R07": (
		"Linen & waste",
		"Collection, processing and handover",
		[
			"linen-collections",
			"laundry",
			"linen-issues",
			"waste-collections",
			"waste-storage",
			"waste-handover",
		],
	),
	"R08": (
		"User department",
		"Receive, use and return instruments",
		["department-stock", "usage", "returns", "requests", "recalls", "linen-issues", "trace"],
	),
	"R09": (
		"Accounting / supplies",
		"Supplies, expenses and costing",
		["items", "stock-entries", "cost-entries", "rates", "costs"],
	),
	"R10": (
		"System administration",
		"Configuration, accounts and audit",
		["zones", "printers", "labels", "accounts", "audit", "instruments", "set-types", "set-units"],
	),
}

# Only these fields can leave the read API. Credentials and patient identifiers are absent.
# A missing DocType is unavailable, never represented by invented records.
SCREENS = {
	"instruments": (
		"Instrument catalogue",
		"Instrument",
		["instrument_name", "instrument_group", "status", "version_no", "max_cycles", "image"],
	),
	"set-types": (
		"Set types & BOM",
		"Instrument Set Type",
		["type_code", "set_type_name", "method", "department", "current_bom_version", "shelf_life_days"],
	),
	"set-units": (
		"Instrument sets / Set ID",
		"Set Unit",
		[
			"set_type",
			"status",
			"cycles_used",
			"max_cycles",
			"current_cycle_no",
			"cycle_bom_version",
			"department",
		],
	),
	"overrides": (
		"Cycle limit overrides",
		"Par Override",
		["set_unit", "status", "reason", "extra_cycles", "valid_until"],
	),
	"recalls": ("Recalls", "Recall Order", ["status", "reason", "sterilization_load"]),
	"incidents": (
		"Incidents / NC-CAPA",
		"Incident CAPA",
		["status", "incident_type", "severity", "description"],
	),
	"equipment": (
		"Equipment & programs",
		"Equipment",
		["equipment_name", "equipment_type", "status", "zone_in", "zone_out", "serial_no"],
	),
	"people": ("Staff & certificates", "Employee", ["employee_name", "department", "designation", "status"]),
	"competencies": (
		"Station competencies",
		"Station Competency",
		["employee", "station", "valid_until", "is_active"],
	),
	"receipts": (
		"T1 · Receiving",
		"Dirty Receipt",
		["department", "deliverer_name", "receiver", "station", "received_at", "docstatus"],
	),
	"wash-batches": (
		"T2 · Washing–disinfection",
		"Wash Batch",
		["equipment", "program", "status", "cycle_result", "started_at"],
	),
	"assembly": (
		"T3 · Inspection–assembly",
		"Assembly Record",
		["set_unit", "result", "station", "assembled_at", "docstatus"],
	),
	"packs": ("T4 · Packing", "Pack", ["set_unit", "status", "method", "expiry", "packed_by_user"]),
	"loads": (
		"T5 / T5b · Sterilization loads",
		"Sterilization Load",
		["equipment", "program", "status", "cycle_result", "bi_result", "docstatus"],
	),
	"daily-tests": ("Daily tests", "Daily Test", ["equipment", "test_type", "result", "test_date"]),
	"putaways": ("T6 · Putaway", "Sterile Putaway", ["pack", "action", "location", "station", "putaway_at"]),
	"sterile-stock": ("Sterile stock", "Pack", ["set_unit", "status", "expiry", "location"]),
	"issues": (
		"T7 · Issuing",
		"Issue Note",
		["department", "recipient_name", "pack_count", "issued_at", "docstatus"],
	),
	"linen-collections": ("Linen collection", "Linen Collection", ["department", "status", "total_weight"]),
	"laundry": ("Laundry batches", "Laundry Batch", ["equipment", "status", "total_weight"]),
	"linen-issues": ("Linen issuing", "Linen Issue", ["department", "status", "docstatus"]),
	"waste-collections": (
		"Waste collection",
		"Waste Collection",
		["department", "waste_type", "weight", "status"],
	),
	"waste-storage": ("Waste storage", "Waste Storage", ["waste_type", "location", "status"]),
	"waste-handover": ("Waste handover", "Waste Handover", ["contractor", "status", "docstatus"]),
	"department-stock": ("Department sets & par levels", None, []),
	"usage": ("T8 · Usage scan", "Usage Record", ["pack", "department", "used_at", "surgery_code"]),
	"returns": ("Return used sets", None, []),
	"requests": ("Supply requests", None, []),
	"trace": ("Pack trace", None, []),
	"items": ("Supply catalogue", "Item", ["item_name", "item_group", "stock_uom", "disabled"]),
	"stock-entries": (
		"Supply receipts / issues",
		"Stock Entry",
		["stock_entry_type", "posting_date", "total_incoming_value", "docstatus"],
	),
	"cost-entries": ("Expenses", "Cost Entry", ["cost_type", "amount", "posting_date"]),
	"rates": ("Rate tables", "Cost Rate Version", ["status", "effective_from"]),
	"costs": (
		"Reprocessing cost",
		"Cost Sheet",
		["set_unit", "sterilization_load", "total_cost", "status"],
	),
	"zones": (
		"Zones & stations",
		"Zone Station",
		["zone_station_name", "station_step", "parent_zone", "is_zone", "is_active"],
	),
	"printers": ("Printers", "Printer", ["printer_name", "station", "is_active", "label_type_loaded"]),
	"labels": ("Label templates", "Label Template", ["template_name", "label_object", "is_active"]),
	"accounts": ("Accounts & permissions", "User", ["full_name", "enabled", "user_type"]),
	"audit": (
		"Audit trail",
		"Audit Log",
		["timestamp", "user", "action", "ref_doctype", "ref_name", "reason"],
	),
	"sync": ("Sync conflicts", "Sync Conflict", ["station", "status", "ref_doctype", "ref_name"]),
	"sterilization-book": (
		"Electronic sterilization log",
		"Sterilization Load",
		["equipment", "program", "status", "cycle_result", "bi_result", "docstatus"],
	),
}
