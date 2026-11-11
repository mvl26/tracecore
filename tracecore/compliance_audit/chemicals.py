"""Hóa chất KSNK theo khoa-tháng từ 3 nguồn (FEAT-066; FR-M12-12, FR-M12-12.1, FR-M12-12.2; UC-46; A-142).

- Nguồn 1 — ``Stock Entry`` ERPNext ghi sổ có dòng tới kho thuộc khoa (``Warehouse.tc_department``) và Item có
  ``tc_ic_chemical_type`` (hook ``doc_events``, ADR-009; M12 không import M6): mỗi dòng một bản ghi.
- Nguồn 2 — file khoa Dược qua Import Mapping Profile (``chemical_import``).
- Nguồn 3 — nhập tay có ghi nguồn và người xác nhận (RPC ``tracecore.v1.ic_chemical``).

Mỗi chứng từ nguồn là một bản ``IC Chemical Consumption`` đã ghi sổ; tổng hợp cộng dồn. Cùng (tháng, khoa, item) có
bản ghi từ ≥ 2 nguồn → "Chờ xác nhận", không vào tổng cho tới khi R09/R01 chọn nguồn giữ; bản nguồn bỏ bị Hủy có lý do
(Audit Log qua ``doc_events``). Lít = số lượng theo UOM kho ÷ hệ số UOM "Litre" của Item; thiếu quy đổi → không có lít.
Lít dung dịch VST nhanh / 1.000 ngày nằm viện đọc mẫu số ``Ward Daily Census`` (M13) qua ``frappe.db`` khi DocType có.
"""

import re

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, get_last_day, getdate, now_datetime

from tracecore.core import audit

DOCTYPE = "IC Chemical Consumption"
STOCK_ENTRY, IMPORT, MANUAL = "Stock Entry", "Import", "Manual Entry"
SOURCES = (STOCK_ENTRY, IMPORT, MANUAL)
TYPES = ("Hand Rub", "Soap", "Surface Disinfectant", "Instrument Disinfectant", "Other")
HAND_RUB = "Hand Rub"
AWAITING, KEPT = "Awaiting Confirmation", "Kept"
LITRE_UOMS = ("Litre", "Liter", "L")
INDICATOR = "HAND_RUB_PER_1000_PATIENT_DAYS"
CENSUS = "Ward Daily Census"
SCREEN_SLUG = "hoa-chat"
SCREEN_ROLES = ("TC R01", "TC R02", "TC R09", "TC R10", "TC R11", "TC R13", "System Manager")
PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# --- Quy đổi -------------------------------------------------------------------------------------------------------


def uom_factor(item, uom) -> float | None:
	"""Số đơn vị kho trong một ``uom`` của Item (UOM kho → 1); không khai báo quy đổi → None."""
	stock_uom = frappe.db.get_value("Item", item, "stock_uom")
	if not uom or uom == stock_uom:
		return 1.0
	factor = frappe.db.get_value(
		"UOM Conversion Detail", {"parent": item, "parenttype": "Item", "uom": uom}, "conversion_factor"
	)
	return flt(factor) or None


def litre_factor(item) -> float | None:
	"""Số đơn vị kho trong một lít của Item; UOM kho là lít → 1; không có quy đổi lít → None."""
	if frappe.db.get_value("Item", item, "stock_uom") in LITRE_UOMS:
		return 1.0
	factor = frappe.db.get_value(
		"UOM Conversion Detail",
		{"parent": item, "parenttype": "Item", "uom": ["in", LITRE_UOMS]},
		"conversion_factor",
	)
	return flt(factor) or None


def to_litre(item, stock_qty) -> float | None:
	factor = litre_factor(item)
	return flt(stock_qty) / factor if factor else None


# --- Bản ghi -------------------------------------------------------------------------------------------------------


def valid_period(period) -> bool:
	return isinstance(period, str) and bool(PERIOD.match(period))


def chemical_type(item) -> str | None:
	return frappe.db.get_value("Item", item, "tc_ic_chemical_type") if item else None


def problems(values) -> list[str]:
	"""Lỗi của một bản ghi (dùng chung validate, nhập tay, import): chuỗi đã qua ``_()``."""
	out = []
	if not valid_period(values.get("period")):
		out.append(_("Period must be in the form YYYY-MM, for example 2026-10."))
	if not values.get("department") or not frappe.db.exists("Department", values.get("department")):
		out.append(_("Choose an existing department."))
	item = values.get("item")
	if not item or not frappe.db.exists("Item", item):
		out.append(_("Choose an existing item."))
	elif not chemical_type(item):
		out.append(_("Item {0} has no infection control chemical type.").format(item))
	if flt(values.get("qty")) <= 0:
		out.append(_("Quantity must be greater than 0."))
	if values.get("source") == MANUAL and not (values.get("source_note") or "").strip():
		out.append(_("Write where the manually entered quantity comes from."))
	return out


def validate(doc):
	"""``IC Chemical Consumption.validate``: kiểm giá trị, điền loại, tên, UOM kho, lít; khóa nguồn không trùng."""
	reasons = problems(doc.as_dict())
	if doc.source not in SOURCES:
		reasons.append(_("Source must be one of {0}.").format(", ".join(_(s) for s in SOURCES)))
	if reasons:
		frappe.throw(" ".join(reasons), title=_("Chemical consumption not valid"))
	doc.chemical_type = chemical_type(doc.item)
	doc.item_name = frappe.db.get_value("Item", doc.item, "item_name")
	doc.uom = frappe.db.get_value("Item", doc.item, "stock_uom")
	doc.qty_litre = to_litre(doc.item, doc.qty)
	doc.posting_date = doc.posting_date or get_first_day(f"{doc.period}-01")
	if doc.source_row and frappe.db.exists(
		DOCTYPE,
		{"source": doc.source, "source_row": doc.source_row, "docstatus": ["<", 2], "name": ["!=", doc.name]},
	):
		frappe.throw(_("This source row is already recorded."), frappe.DuplicateEntryError)


def before_cancel(doc):
	if not (doc.cancel_reason or "").strip():
		frappe.throw(_("Write the reason for cancelling this chemical consumption."))


def record(values, source, import_batch=None):
	"""Tạo và ghi sổ một bản ghi (dịch vụ: nơi gọi đã kiểm quyền); nhập tay ghi người xác nhận = người gọi."""
	doc = frappe.get_doc({"doctype": DOCTYPE, **values, "source": source, "import_batch": import_batch})
	if source == MANUAL:
		doc.confirmed_by = frappe.session.user
		doc.confirmed_on = now_datetime()
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	return doc


def cancel(name, reason):
	doc = frappe.get_doc(DOCTYPE, name)
	doc.cancel_reason = reason
	doc.flags.ignore_permissions = True
	doc.cancel()
	return doc


# --- Nguồn Stock Entry (ADR-009) -------------------------------------------------------------------------------------


def department_of(warehouse):
	return frappe.db.get_value("Warehouse", warehouse, "tc_department") if warehouse else None


def on_stock_entry_submit(doc, method=None):
	"""Dòng tới kho thuộc khoa, Item hóa chất KSNK → một bản ghi ``source`` = Stock Entry (idempotent theo dòng)."""
	for row in doc.items:
		department = department_of(row.t_warehouse)
		if not department or department_of(row.s_warehouse) == department or not chemical_type(row.item_code):
			continue
		if frappe.db.exists(DOCTYPE, {"source": STOCK_ENTRY, "source_row": row.name, "docstatus": ["<", 2]}):
			continue
		record(
			{
				"period": str(getdate(doc.posting_date))[:7],
				"posting_date": doc.posting_date,
				"department": department,
				"item": row.item_code,
				"qty": flt(row.transfer_qty) or flt(row.qty) * flt(row.conversion_factor or 1),
				"source_ref": doc.name,
				"source_row": row.name,
			},
			STOCK_ENTRY,
		)


def on_stock_entry_cancel(doc, method=None):
	for name in frappe.get_all(
		DOCTYPE, filters={"source": STOCK_ENTRY, "source_ref": doc.name, "docstatus": 1}, pluck="name"
	):
		cancel(name, _("Stock Entry {0} was cancelled.").format(doc.name))


# --- Trùng nguồn (FR-M12-12.1) ---------------------------------------------------------------------------------------


def _posted(period, department, item):
	return frappe.get_all(
		DOCTYPE,
		filters={"period": period, "department": department, "item": item, "docstatus": 1},
		fields=["name", "source", "duplicate_status"],
		order_by="creation asc",
	)


def refresh_duplicates(period, department, item):
	"""Đặt lại ``duplicate_status`` của bộ (tháng, khoa, item) sau mỗi lần ghi sổ/hủy."""
	docs = _posted(period, department, item)
	sources = {doc.source for doc in docs}
	kept = {doc.source for doc in docs if doc.duplicate_status == KEPT}
	for doc in docs:
		if len(sources) > 1 and not (kept and sources <= kept):
			status = AWAITING
		else:
			status = KEPT if doc.source in kept else ""
		if (doc.duplicate_status or "") != status:
			frappe.db.set_value(DOCTYPE, doc.name, "duplicate_status", status, update_modified=False)


def choose_source(period, department, item, keep_source, reason):
	"""R09/R01 chọn nguồn giữ cho bộ đang "Chờ xác nhận": hủy bản của nguồn khác (có lý do); trả tên bản đã hủy."""
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("Write why this source is kept."))
	docs = _posted(period, department, item)
	if not any(doc.duplicate_status == AWAITING for doc in docs):
		frappe.throw(
			_("This department and item have no duplicate sources to resolve in {0}.").format(period)
		)
	if keep_source not in {doc.source for doc in docs}:
		frappe.throw(_("Source {0} has no record to keep.").format(_(keep_source)))
	text = _("Duplicate source; kept {0}: {1}").format(_(keep_source), reason)
	cancelled = []
	for doc in docs:
		if doc.source != keep_source:
			cancel(doc.name, text)
			cancelled.append(doc.name)
	kept = [doc.name for doc in docs if doc.source == keep_source]
	for name in kept:
		frappe.db.set_value(DOCTYPE, name, "duplicate_status", KEPT, update_modified=False)
	audit.log(
		"Update",
		DOCTYPE,
		kept[0],
		new={"duplicate_status": KEPT, "kept_source": keep_source, "cancelled": cancelled},
		reason=reason,
	)
	return cancelled


# --- Tổng hợp (FR-M12-12, .2) --------------------------------------------------------------------------------------


def quarter_of(period) -> tuple[int, int]:
	year, month = (int(part) for part in period.split("-"))
	return year, (month - 1) // 3 + 1


def quarter_periods(year, quarter) -> list[str]:
	year, quarter = cint(year), cint(quarter)
	if not 1 <= quarter <= 4:
		frappe.throw(_("Quarter must be 1 to 4."))
	return [f"{year}-{month:02d}" for month in range(quarter * 3 - 2, quarter * 3 + 1)]


def monthly(period_from, period_to, department=None) -> list:
	"""Dòng (tháng, khoa, item) đã ghi sổ: lít, số lượng, nguồn, cờ chờ xác nhận, số bản thiếu quy đổi lít."""
	filters = [["docstatus", "=", 1], ["period", ">=", period_from], ["period", "<=", period_to]]
	if department:
		filters.append(["department", "=", department])
	rows = frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=[
			"period",
			"department",
			"item",
			"item_name",
			"chemical_type",
			"qty",
			"qty_litre",
			"source",
			"duplicate_status",
		],
		order_by="period asc, department asc, item asc",
	)
	out: dict[tuple, frappe._dict] = {}
	for row in rows:
		key = (row.period, row.department, row.item)
		entry = out.setdefault(
			key,
			frappe._dict(
				period=row.period,
				department=row.department,
				item=row.item,
				item_name=row.item_name,
				chemical_type=row.chemical_type or "Other",
				qty=0.0,
				qty_litre=0.0,
				no_litre=0,
				sources=[],
				awaiting=False,
			),
		)
		entry.qty += flt(row.qty)
		if row.qty_litre is None or (not flt(row.qty_litre) and flt(row.qty)):
			entry.no_litre += 1
		entry.qty_litre += flt(row.qty_litre)
		if row.source not in entry.sources:
			entry.sources.append(row.source)
		entry.awaiting = entry.awaiting or row.duplicate_status == AWAITING
	return list(out.values())


def patient_days(periods, department=None):
	"""Σ ngày nằm viện (``Ward Daily Census.patient_count``) của các tháng; chưa có DocType/mẫu số → None (UC-46 E3)."""
	if not periods or not frappe.db.exists("DocType", CENSUS):
		return None
	filters = {
		"census_date": [
			"between",
			[get_first_day(f"{periods[0]}-01"), get_last_day(f"{periods[-1]}-01")],
		],
	}
	if department:
		filters["department"] = department
	total = frappe.get_all(CENSUS, filters=filters, fields=["sum(patient_count) as total"])
	return flt(total[0].total) if total and flt(total[0].total) else None


def _per_1000(litres, days):
	return flt(litres) / flt(days) * 1000 if days else None


def _empty_litres():
	return dict.fromkeys(TYPES, 0.0)


def summary(year, quarter, department=None) -> dict:
	"""Báo cáo quý: lít theo loại x khoa (bỏ bộ Chờ xác nhận), toàn viện, VST nhanh / 1.000 ngày nằm viện."""
	periods = quarter_periods(year, quarter)
	by_department: dict[str, dict] = {}
	for row in monthly(periods[0], periods[-1], department):
		dept = by_department.setdefault(
			row.department,
			{
				"department": row.department,
				"litres": _empty_litres(),
				"sources": [],
				"awaiting": 0,
				"awaiting_items": [],
				"no_litre": 0,
			},
		)
		for source in row.sources:
			if source not in dept["sources"]:
				dept["sources"].append(source)
		if row.awaiting:
			dept["awaiting"] += 1
			dept["awaiting_items"].append(
				{"period": row.period, "item": row.item, "item_name": row.item_name, "sources": row.sources}
			)
			continue
		dept["litres"][row.chemical_type] += row.qty_litre
		dept["no_litre"] += row.no_litre
	names = dict(
		frappe.get_all(
			"Department",
			filters={"name": ["in", list(by_department) or [""]]},
			fields=["name", "department_name"],
			as_list=True,
		)
	)
	departments = sorted(
		by_department.values(), key=lambda d: (names.get(d["department"]) or d["department"]).casefold()
	)
	total = {"litres": _empty_litres(), "awaiting": 0, "no_litre": 0}
	for dept in departments:
		dept["department_name"] = names.get(dept["department"]) or dept["department"]
		dept["patient_days"] = patient_days(periods, dept["department"])
		dept["hand_rub_per_1000"] = _per_1000(dept["litres"][HAND_RUB], dept["patient_days"])
		for kind in TYPES:
			total["litres"][kind] += dept["litres"][kind]
		total["awaiting"] += dept["awaiting"]
		total["no_litre"] += dept["no_litre"]
	total["departments"] = len(departments)
	total["patient_days"] = patient_days(periods, department)
	total["hand_rub_per_1000"] = _per_1000(total["litres"][HAND_RUB], total["patient_days"])
	return {
		"year": cint(year),
		"quarter": cint(quarter),
		"periods": periods,
		"departments": departments,
		"total": total,
	}


def litres_by_type(period_from, period_to, department=None) -> dict:
	"""Lít theo loại hóa chất trong khoảng tháng (A1: báo cáo môi trường M15 đọc cùng bảng)."""
	litres = _empty_litres()
	for row in monthly(period_from, period_to, department):
		if not row.awaiting:
			litres[row.chemical_type] += row.qty_litre
	return litres


# --- Chỉ số M9, badge ----------------------------------------------------------------------------------------------


def hand_rub_indicator(period, department=None):
	"""(lít VST nhanh, ngày nằm viện, ngày nằm viện) — engine M9 tính "Rate per 1000"."""
	litres = litres_by_type(period, period, department)[HAND_RUB]
	days = patient_days([period], department) or 0
	return litres, days, days


def register_indicators():
	return {INDICATOR: hand_rub_indicator}


def awaiting_count() -> int:
	rows = frappe.get_all(
		DOCTYPE,
		filters={"docstatus": 1, "duplicate_status": AWAITING},
		fields=["period", "department", "item"],
		distinct=True,
	)
	return len(rows)


def badges(user):
	"""Số bộ hóa chất chờ chọn nguồn + số đơn vị thuê ngoài hết hạn giấy phép (rail SCR-54)."""
	if not set(frappe.get_roles(user)) & set(SCREEN_ROLES):
		return {}
	from tracecore.compliance_audit import vendors

	return {SCREEN_SLUG: awaiting_count() + vendors.expired_count()}
