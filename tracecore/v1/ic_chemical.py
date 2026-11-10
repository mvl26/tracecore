"""RPC tracecore.v1.ic_chemical.* — màn SCR-54 Hóa chất KSNK & đơn vị thuê ngoài (FEAT-066; FR-M12-12, FR-M12-13; UC-46;
A-142).

- ``overview`` (GET, chỉ đọc): tổng hợp quý theo loại x khoa (bộ Chờ xác nhận tách riêng), đơn vị thuê ngoài + giấy
  phép + phiếu giám sát gần nhất, đơn vị chưa giám sát trong quý, hồ sơ ánh xạ để import, Item hóa chất để nhập tay.
- ``manual_preview`` (POST, không ghi) / ``manual_entry`` (POST, ``@idempotent``): nhập tay có ghi nguồn, bước xác
  nhận; Audit Log ``Manual Entry`` (UC-46 bước 3).
- ``choose_source`` (POST, ``@idempotent``): R09/R01 chọn nguồn giữ khi trùng (FR-M12-12.1).

Import file dùng ``tracecore.v1.imports.check/run`` với loại ``ic_chemical``. Lỗi nghiệp vụ trả body
``{ok: false, error: {title, reason, action}}`` để màn hiện ``alert-error`` inline.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, today

from tracecore.compliance_audit import chemical_import, chemicals, vendors
from tracecore.core import audit, importer
from tracecore.core.client_time import parse_client_ts
from tracecore.core.idempotency import idempotent
from tracecore.ui import ksnk
from tracecore.v1._common import require_any_role

REPORT = "IC Chemical Consumption by Department"
WRITE_ROLES = ("TC R01", "TC R09", "System Manager")
VALUE_FIELDS = ("period", "department", "item", "qty", "source_note")


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == chemicals.SCREEN_SLUG)
	if not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(_("You are not allowed to open the chemicals screen."), frappe.PermissionError)


def _can_write() -> bool:
	return bool(set(frappe.get_roles()) & set(WRITE_ROLES)) and bool(
		frappe.has_permission(chemicals.DOCTYPE, "create")
	)


def _block(title, reasons, action):
	return {"ok": False, "error": {"title": title, "reason": " ".join(reasons), "action": action}}


def _quarter(year, quarter):
	now = getdate(today())
	return cint(year) or now.year, cint(quarter) or (now.month - 1) // 3 + 1


@frappe.whitelist(methods=["GET"])
def overview(year=None, quarter=None):
	"""Dữ liệu màn SCR-54 (chỉ đọc)."""
	_require_screen()
	year, quarter = _quarter(year, quarter)
	can_write = _can_write()
	can_import = chemical_import.can_import()
	result = {
		"ok": True,
		"year": year,
		"quarter": quarter,
		"can_write": can_write,
		"can_import": can_import,
		"import_kind": chemical_import.KEY,
		"profiles": [],
		"items": [],
		"summary": chemicals.summary(year, quarter),
		"vendors": vendors.overview(),
		"unaudited": vendors.unaudited(year, quarter),
		"report": f"/app/query-report/{REPORT}",
	}
	if can_import:
		# R09 không đọc DocType Import Mapping Profile (R10/R11 soạn hồ sơ); tên hồ sơ không nhạy cảm
		result["profiles"] = frappe.get_all(
			importer.PROFILE_DOCTYPE,
			filters={"import_kind": chemical_import.KEY},
			fields=["name", "file_format"],
			order_by="name asc",
		)
	if can_write:
		result["items"] = frappe.get_all(
			"Item",
			filters={"tc_ic_chemical_type": ["is", "set"], "disabled": 0},
			fields=["name", "item_name", "stock_uom", "tc_ic_chemical_type"],
			order_by="item_name asc",
		)
	return result


def _manual_values(values):
	require_any_role(*WRITE_ROLES)
	if not frappe.has_permission(chemicals.DOCTYPE, "create"):
		raise frappe.PermissionError(_("You are not allowed to record chemical consumption."))
	if isinstance(values, str):
		values = json.loads(values or "{}")
	values = {field: (values or {}).get(field) for field in VALUE_FIELDS}
	values["qty"] = flt(values["qty"])
	values["source"] = chemicals.MANUAL
	return values


def _other_sources(values):
	return sorted(
		set(
			frappe.get_all(
				chemicals.DOCTYPE,
				filters={
					"period": values["period"],
					"department": values["department"],
					"item": values["item"],
					"docstatus": 1,
					"source": ["!=", chemicals.MANUAL],
				},
				pluck="source",
			)
		)
	)


@frappe.whitelist(methods=["POST"])
def manual_preview(values=None):
	"""Kiểm một dòng nhập tay, không ghi: ``{ok: true, preview}`` để người nhập xác nhận."""
	_require_screen()
	values = _manual_values(values)
	reasons = chemicals.problems(values)
	if reasons:
		return _block(_("Entry not valid"), reasons, _("Correct the entry and check it again."))
	litres = chemicals.to_litre(values["item"], values["qty"])
	return {
		"ok": True,
		"preview": {
			"period": values["period"],
			"department_name": frappe.db.get_value("Department", values["department"], "department_name"),
			"item_name": frappe.db.get_value("Item", values["item"], "item_name"),
			"chemical_type": chemicals.chemical_type(values["item"]),
			"qty": values["qty"],
			"uom": frappe.db.get_value("Item", values["item"], "stock_uom"),
			"litres": litres,
			"source_note": values["source_note"],
			"other_sources": _other_sources(values),
		},
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def manual_entry(values=None, confirm=0, client_ts=None):
	"""Ghi sổ một dòng nhập tay đã xác nhận: ``{ok: true, name, duplicate_status}``."""
	_require_screen()
	timestamp = parse_client_ts(client_ts)
	values = _manual_values(values)
	if not cint(confirm):
		return _block(
			_("Confirmation needed"),
			[_("A manually entered quantity is saved only after the person entering it confirms it.")],
			_("Check the summary and choose Confirm and save."),
		)
	reasons = chemicals.problems(values)
	if reasons:
		return _block(_("Entry not saved"), reasons, _("Correct the entry and check it again."))
	values.pop("source")
	doc = chemicals.record(values, chemicals.MANUAL)
	audit.log(
		"Manual Entry",
		chemicals.DOCTYPE,
		doc.name,
		new={"item": doc.item, "department": doc.department, "qty": doc.qty, "source_note": doc.source_note},
		reason="confirmed manual chemical consumption",
		client_ts=timestamp,
	)
	return {
		"ok": True,
		"name": doc.name,
		"duplicate_status": frappe.db.get_value(chemicals.DOCTYPE, doc.name, "duplicate_status"),
	}


@frappe.whitelist(methods=["POST"])
@idempotent
def choose_source(period=None, department=None, item=None, source=None, reason=None, client_ts=None):
	"""Chọn nguồn giữ cho bộ (tháng, khoa, item) đang Chờ xác nhận: ``{ok: true, cancelled: [tên]}``."""
	_require_screen()
	parse_client_ts(client_ts)
	require_any_role(*WRITE_ROLES)
	if not frappe.has_permission(chemicals.DOCTYPE, "cancel"):
		raise frappe.PermissionError(_("You are not allowed to cancel chemical consumption."))
	try:
		cancelled = chemicals.choose_source(period, department, item, source, reason)
	except frappe.ValidationError as error:
		frappe.clear_last_message()
		return _block(
			_("Source not chosen"), [frappe.utils.strip_html(str(error))], _("Check the entry and try again.")
		)
	return {"ok": True, "cancelled": cancelled}
