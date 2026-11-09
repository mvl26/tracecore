"""RPC tracecore.v1.micro.* — màn SCR-59 Vi sinh & đa kháng (FEAT-067; FR-M14-01..05, FR-M14-08; UC-51; A-136).

- ``overview`` (GET, chỉ đọc): hồ sơ ánh xạ để import, chủng đa kháng chưa xử lý, chủng mới trong 7 ngày (mã BN đã
  che, nhãn tiền sử đa kháng), kháng sinh đồ quý của một vi khuẩn (chỉ chủng đầu tiên), số quy tắc đã duyệt/Nháp.
  R13 chỉ nhận phần tổng hợp (không đọc DocType có người bệnh, ADR-010).
- ``manual_preview`` (POST, không ghi): kiểm một kết quả nhập tay, trả bản xem lại đã che mã BN để người nhập xác nhận.
- ``manual_entry`` (POST, ``@idempotent``): ghi kết quả nhập tay khi ``confirm`` = 1; ``source`` = Nhập tay, người xác
  nhận, Audit Log ``Manual Entry`` (FR-M14-02.1).
- ``mdro_history`` (GET): nhãn đa kháng đã từng có theo hash mã BN — cho module khác (M13) gọi, không giải mã.

Import file dùng ``tracecore.v1.imports.check/run`` với loại ``microbiology``. Lỗi nghiệp vụ trả body
``{ok: false, error: {title, reason, action}}`` để màn hiện ``alert-error`` inline.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, getdate, now_datetime, today

from tracecore.core import audit, importer, patient_code
from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.microbiology import alerts, imports, isolates, resistance, rules
from tracecore.ui import ksnk
from tracecore.v1._common import require_any_role

SCREEN_SLUG = alerts.SCREEN_SLUG
RECENT_DAYS = 7
RECENT_LIMIT = 50
REPORT = "Antimicrobial Resistance by Quarter"
WRITE_ROLES = ("TC R11", "System Manager")
HISTORY_ROLES = ("TC R01", "TC R11", "TC R12", "System Manager")
RECENT_FIELDS = (
	"name",
	"lab_sample_id",
	"patient_code_masked",
	"patient_code_hash",
	"department",
	"department_name",
	"specimen_type",
	"organism",
	"organism_name",
	"collected_on",
	"is_mdro",
	"mdro_flags",
	"is_first_isolate",
	"source",
)


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == SCREEN_SLUG)
	if not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(_("You are not allowed to open the microbiology screen."), frappe.PermissionError)


def _json(value, default):
	if isinstance(value, str):
		return json.loads(value or "null") or default
	return value or default


def _block(title, reasons, action):
	return {"ok": False, "error": {"title": title, "reason": " ".join(reasons), "action": action}}


def _quarter(year, quarter):
	now = getdate(today())
	return cint(year) or now.year, cint(quarter) or (now.month - 1) // 3 + 1


def _recent():
	rows = frappe.get_list(
		isolates.DOCTYPE,
		filters={"creation": [">=", add_to_date(now_datetime(), days=-RECENT_DAYS)]},
		fields=list(RECENT_FIELDS),
		order_by="creation desc",
		limit_page_length=RECENT_LIMIT,
	)
	history = isolates.mdro_history(rows)
	waiting = set(alerts.pending()["isolates"])
	for row in rows:
		row["history"] = history.get(row.name, [])
		row["pending"] = row.name in waiting
		row.pop("patient_code_hash")
	return rows


def _antibiogram(year, quarter, organism):
	counts = frappe.get_all(
		isolates.DOCTYPE,
		filters={"period_key": resistance.period(year, quarter), "is_first_isolate": 1},
		fields=["organism", "organism_name", "count(name) as first_isolates"],
		group_by="organism, organism_name",
		order_by="first_isolates desc, organism asc",
	)
	chosen = (
		organism if organism in {row.organism for row in counts} else (counts[0].organism if counts else None)
	)
	head = next((row for row in counts if row.organism == chosen), None)
	return counts, {
		"organism": chosen,
		"organism_name": head.organism_name if head else None,
		"first_isolates": head.first_isolates if head else 0,
		"threshold": resistance.min_isolates(),
		"rows": resistance.compute(year, quarter, organism=chosen) if chosen else [],
	}


@frappe.whitelist(methods=["GET"])
def overview(year=None, quarter=None, organism=None):
	"""Dữ liệu màn SCR-59 (chỉ đọc)."""
	_require_screen()
	year, quarter = _quarter(year, quarter)
	can_read = bool(frappe.has_permission(isolates.DOCTYPE, "read"))
	can_write = bool(set(frappe.get_roles()) & set(WRITE_ROLES)) and bool(
		frappe.has_permission(isolates.DOCTYPE, "create")
	)
	organisms, antibiogram = _antibiogram(year, quarter, organism)
	result = {
		"ok": True,
		"year": year,
		"quarter": quarter,
		"can_read_isolates": can_read,
		"can_import": can_write,
		"can_manual": can_write,
		"import_kind": imports.KEY,
		"profiles": [],
		"catalog": [],
		"pending": None,
		"recent": [],
		"organisms": organisms,
		"antibiogram": antibiogram,
		"rules": {
			"approved": frappe.db.count(rules.DOCTYPE, {"docstatus": 1, "superseded_by": ["is", "not set"]}),
			"draft": frappe.db.count(rules.DOCTYPE, {"docstatus": 0}),
		},
		"report": f"/app/query-report/{REPORT}",
	}
	if can_write:
		result["profiles"] = frappe.get_list(
			importer.PROFILE_DOCTYPE,
			filters={"import_kind": imports.KEY},
			fields=["name", "file_format"],
			order_by="name asc",
		)
		result["catalog"] = frappe.get_all(
			"Organism",
			filters={"disabled": 0},
			fields=["name", "organism_name"],
			order_by="organism_name asc",
		)
	if can_read:
		pending = alerts.pending()
		result["pending"] = {"count": pending["count"], "first_sent": pending["first_sent"]}
		result["recent"] = _recent()
	return result


def _manual(values, susceptibility):
	require_any_role(*WRITE_ROLES)
	if not frappe.has_permission(isolates.DOCTYPE, "create"):
		raise frappe.PermissionError(_("You are not allowed to record microbiology results."))
	values = _json(values, {})
	susceptibility = _json(susceptibility, [])
	return {field: values.get(field) for field in isolates.VALUE_FIELDS}, susceptibility


@frappe.whitelist(methods=["POST"])
def manual_preview(values=None, susceptibility=None):
	"""Kiểm kết quả nhập tay, không ghi: ``{ok: true, preview}`` (mã BN đã che) để người nhập xác nhận."""
	_require_screen()
	values, susceptibility = _manual(values, susceptibility)
	reasons = isolates.problems(values, susceptibility)
	if reasons:
		return _block(_("Result not valid"), reasons, _("Correct the result and check it again."))
	organism = isolates.organism_ref(values["organism"])
	group = frappe.db.get_value("Organism", organism, "organism_group")
	results = {row["antibiotic"]: row["result"] for row in isolates.susceptibility_rows(susceptibility)}
	labels = [
		rule.label
		for rule in rules.active_rules(values["collected_on"])
		if rules.matches(rule, organism, group, results)
	]
	return {
		"ok": True,
		"preview": {
			"lab_sample_id": isolates.sample_id(values["lab_sample_id"]),
			"patient_code_masked": patient_code.mask(values["patient_code"]),
			"organism": organism,
			"organism_name": frappe.db.get_value("Organism", organism, "organism_name"),
			"department_name": frappe.db.get_value("Department", values["department"], "department_name"),
			"collected_on": str(getdate(values["collected_on"])),
			"susceptibility": isolates.susceptibility_rows(susceptibility),
			"mdro_labels": list(dict.fromkeys(labels)),
		},
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def manual_entry(values=None, susceptibility=None, confirm=0, client_ts=None):
	"""Ghi kết quả nhập tay đã xác nhận (FR-M14-02): ``{ok: true, isolate, is_mdro, mdro_flags}``."""
	_require_screen()
	timestamp = parse_client_ts(client_ts)
	values, susceptibility = _manual(values, susceptibility)
	if not cint(confirm):
		return _block(
			_("Confirmation needed"),
			[_("A manually entered result is saved only after the person entering it confirms it.")],
			_("Check the summary and choose Confirm and save."),
		)
	reasons = isolates.problems(values, susceptibility)
	if reasons:
		return _block(_("Result not saved"), reasons, _("Correct the result and check it again."))
	values["organism"] = isolates.organism_ref(values["organism"])
	doc = isolates.create(values, susceptibility, source=isolates.SOURCE_MANUAL, confirmed=True)
	audit.log(
		"Manual Entry",
		isolates.DOCTYPE,
		doc.name,
		new={"lab_sample_id": doc.lab_sample_id, "organism": doc.organism, "confirmed_by": doc.confirmed_by},
		reason="confirmed manual microbiology result",
		client_ts=timestamp,
	)
	return {"ok": True, "isolate": doc.name, "is_mdro": doc.is_mdro, "mdro_flags": doc.mdro_flags}


@frappe.whitelist(methods=["GET"])
def mdro_history(hashes=None):
	"""``{ok: true, history: {hash: [nhãn]}}`` — người bệnh từng mang vi khuẩn đa kháng (FR-M14-05), so bằng hash."""
	require_any_role(*HISTORY_ROLES)
	return {"ok": True, "history": isolates.history_by_hash(_json(hashes, []))}
