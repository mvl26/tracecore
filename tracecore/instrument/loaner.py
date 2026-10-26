"""Bộ mượn (FEAT-017, A-38; UC-04, SCR-04; FR-M1-05.5, FR-M1-07, FR-M1-08).

- Nhận (ghi sổ `Loaner Set`, R02): mỗi dòng BOM nhanh tạo (hoặc dùng lại theo hãng + tên) một `Instrument`
  ``LNI-#####``; loại bộ mượn ``LN#####`` (dùng lại theo GTIN của hãng, BOM khác → phiên bản mới hiệu lực hôm nay);
  một Set Unit ``is_loaner`` có Set ID GIAI ``<tiền tố>LN<6 số>``. Bộ đi T1→T5 như bộ thường: cổng bước hiện có chặn
  đóng gói / cấp phát trước khi tái xử lý đủ (FR-M1-07.1, FR-M1-08).
- Trả hãng (R02): chỉ khi bộ Vô khuẩn (đã tái xử lý sau lần dùng cuối); ghi số trả/hỏng từng dòng;
  ``step_gate.return_loaner`` → Đã trả hãng; Set ID vô hiệu; thiếu dụng cụ → hook ``tracecore_loaner_returned``
  (M2 tạo NC; M1 không import M2). Gói còn trong kho do M2 hủy qua hook ``tracecore_after_set_status``.
- Gia hạn có lý do; quá hạn nhắc R02 mỗi ngày một lần (FR-M1-07.4).
Trường dịch vụ của `Loaner Set` chỉ ghi ở đây (cờ ``flags.tc_loaner`` hoặc ``db_set`` kèm Audit Log).
"""

import json

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import cint, cstr, getdate, now_datetime, today

from tracecore.core import audit, code_registry, extension, gs1, step_gate
from tracecore.core.errors import Block, BlockedError
from tracecore.instrument import bom_versions, set_units
from tracecore.instrument.count_sheet import DATETIME_FORMAT, token_values

DOCTYPE = "Loaner Set"
ROLE = "TC R02"
FLAG = "tc_loaner"
RECEIPT_FORMAT = "TC Loaner Receipt"
RETURN_FORMAT = "TC Loaner Return"
INSTRUMENT_SERIES = "LNI-.#####"
SET_TYPE_SERIES = "LN.#####"
SET_TYPE_PREFIX = "LN"
# phương pháp tương thích ghi cho dụng cụ của hãng theo phương pháp của bộ (họ phương pháp, A-06 I2)
INSTRUMENT_METHOD = {"Steam": "Steam 134", "Plasma": "Plasma"}
RETURNED_HOOK = "tracecore_loaner_returned"
SERVICE_FIELDS = (
	"status",
	"set_unit",
	"set_type",
	"extension_reason",
	"last_reminded_on",
	"returned_on",
	"returned_by",
	"return_note",
	"missing_count",
	"damaged_count",
	"incident",
)
ITEM_SERVICE_FIELDS = ("instrument", "returned_qty", "damaged_qty", "note")


def _blocked(code, title, reason, action, items=None):
	return BlockedError(Block(code, title, reason, action, items=items))


def _require_role():
	if ROLE not in frappe.get_roles():
		raise _blocked(
			"LOANER_NOT_ALLOWED",
			_("Not allowed"),
			_("Only R02 can receive, return or extend a loaner set."),
			_("Ask R02 to do this step."),
		)


def _dates_block(received_on, expected_return):
	return _blocked(
		"LOANER_DATES_INVALID",
		_("Return date not accepted"),
		_("The expected return date {0} is before the received date {1}.").format(
			frappe.format(expected_return, {"fieldtype": "Date"}),
			frappe.format(received_on, {"fieldtype": "Date"}),
		),
		_("Choose a return date on or after the received date."),
	)


# --- Phiếu nháp ----------------------------------------------------------------------------------------------------


def _reset_service_fields(doc):
	"""Người dùng không gõ được trường dịch vụ: phiếu mới về rỗng, phiếu đã lưu giữ giá trị trước đó."""
	before = None if doc.is_new() else doc.get_doc_before_save()
	for fieldname in SERVICE_FIELDS:
		doc.set(fieldname, before.get(fieldname) if before else None)
	if not before:
		doc.status = "Draft"
	old_rows = {row.name: row for row in (before.get("items") if before else [])}
	for row in doc.get("items") or []:
		old = old_rows.get(row.name)
		for fieldname in ITEM_SERVICE_FIELDS:
			row.set(fieldname, old.get(fieldname) if old else None)


def validate(doc):
	"""Luật phiếu: ngày trả ≥ ngày nhận, GTIN-14 hợp lệ, BOM ≥ 1 dòng, tên không trùng, số lượng 1..999."""
	if not doc.flags.get(FLAG):
		_reset_service_fields(doc)
	if doc.received_on and doc.expected_return and getdate(doc.expected_return) < getdate(doc.received_on):
		raise _dates_block(doc.received_on, doc.expected_return)
	doc.gtin = cstr(doc.gtin).strip()
	if not gs1.is_valid_gtin14(doc.gtin):
		frappe.throw(_("GTIN-14 must be 14 digits with a valid check digit."))
	if not doc.get("items"):
		frappe.throw(_("Enter at least one instrument of the loaner set."))
	seen = set()
	for row in doc.items:
		row.instrument_name = cstr(row.instrument_name).strip()
		key = row.instrument_name.casefold()
		if not row.instrument_name:
			frappe.throw(_("Row {0}: enter the instrument name.").format(row.idx))
		if key in seen:
			frappe.throw(
				_("Row {0}: instrument {1} is listed twice. Combine the quantities in one line.").format(
					row.idx, row.instrument_name
				)
			)
		seen.add(key)
		if not 1 <= cint(row.qty) <= bom_versions.MAX_QTY:
			frappe.throw(
				_("Row {0}: quantity must be a whole number from 1 to {1}.").format(
					row.idx, bom_versions.MAX_QTY
				)
			)


def guard_cancel(doc):
	frappe.throw(_("A received loaner set cannot be cancelled; return it to the vendor instead."))


# --- Nhận ----------------------------------------------------------------------------------------------------------


def _instrument(supplier, name, method):
	"""Dụng cụ của hãng theo (hãng, tên); chưa có thì tạo mã ``LNI-#####``."""
	existing = frappe.db.get_value(
		"Instrument",
		{"manufacturer": supplier, "instrument_name": name, "instrument_code": ("like", "LNI-%")},
		"name",
	)
	if existing:
		return existing
	code = make_autoname(INSTRUMENT_SERIES)
	frappe.get_doc(
		{
			"doctype": "Instrument",
			"instrument_code": code,
			"instrument_name": name,
			"manufacturer": supplier,
			"spaulding_class": "Critical",
			"compatible_methods": [{"method": INSTRUMENT_METHOD[method]}],
			"max_cycles": 0,
		}
	).insert(ignore_permissions=True)
	return code


def _set_type(doc, lines):
	"""Loại bộ mượn theo GTIN của hãng; chưa có thì tạo ``LN#####`` với BOM v1, BOM khác thì thêm phiên bản."""
	existing = frappe.db.get_value("Instrument Set Type", {"gtin": doc.gtin}, "name")
	if existing and not existing.startswith(SET_TYPE_PREFIX):
		raise _blocked(
			"LOANER_GTIN_IN_USE",
			_("GTIN already used"),
			_("GTIN {0} belongs to set type {1} of the hospital, not to a loaner set.").format(
				doc.gtin, existing
			),
			_("Check the GTIN-14 on the vendor's set."),
		)
	if not existing:
		header = {
			"type_code": make_autoname(SET_TYPE_SERIES),
			"set_type_name": f"{doc.set_name} ({doc.supplier})",
			"method": doc.method,
			"department": doc.department,
			"default_pack_type": doc.pack_type,
			"gtin": doc.gtin,
		}
		return bom_versions.create_set_type(header, lines, _("Loaner set {0}").format(doc.name))
	current = cint(frappe.db.get_value("Instrument Set Type", existing, "current_bom_version"))
	wanted = sorted((line["instrument"], line["qty"]) for line in lines)
	if sorted(bom_versions._version_lines(existing, current)) != wanted:
		bom_versions.create_version(existing, lines, today(), _("Loaner set {0}").format(doc.name), current)
	return existing


def on_submit(doc):
	"""Ghi sổ = nhận bộ mượn: dụng cụ, loại bộ, Set ID LN; trạng thái Đã nhận."""
	_require_role()
	for row in doc.items:
		row.instrument = _instrument(doc.supplier, row.instrument_name, doc.method)
		frappe.db.set_value(row.doctype, row.name, "instrument", row.instrument, update_modified=False)
	lines = [{"instrument": row.instrument, "qty": cint(row.qty)} for row in doc.items]
	set_type = _set_type(doc, lines)
	set_unit = set_units._insert_units(
		set_type, 1, doc.department, set_units.MAX_CYCLES_LIMIT, fields={"is_loaner": 1}
	)[0]
	doc.db_set({"status": "Received", "set_type": set_type, "set_unit": set_unit})
	audit.log(
		"Update", DOCTYPE, doc.name, new={"status": "Received", "set_type": set_type, "set_unit": set_unit}
	)


# --- Trả hãng ------------------------------------------------------------------------------------------------------


def _lines(value):
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			value = None
	return value if isinstance(value, list) and all(isinstance(line, dict) for line in value) else None


def _qty_block(items):
	return _blocked(
		"LOANER_RETURN_QTY_INVALID",
		_("Return quantities not accepted"),
		_("{0} lines of the return have wrong quantities.").format(len(items)),
		_(
			"For every line enter the returned quantity (0 to the received quantity) and the damaged quantity (0 to the returned quantity)."
		),
		items=items,
	)


def _check_lines(doc, lines):
	"""``{idx: (returned, damaged, note)}`` đủ mọi dòng; sai → ``LOANER_RETURN_QTY_INVALID`` kèm các dòng lỗi."""
	given = {cint(line.get("idx")): line for line in _lines(lines) or []}
	values, errors = {}, []
	for row in doc.items:
		line = given.get(row.idx)
		returned = cint(line.get("returned_qty")) if line else None
		damaged = cint(line.get("damaged_qty")) if line else None
		if line is None or not 0 <= returned <= cint(row.qty) or not 0 <= damaged <= returned:
			errors.append({"row": row.idx, "instrument": row.instrument_name})
			continue
		values[row.idx] = (returned, damaged, cstr(line.get("note")).strip()[:140])
	if errors:
		raise _qty_block(errors)
	return values


def return_set(name, lines, note=None):
	"""R02 lập biên bản trả: số trả/hỏng từng dòng; bộ phải Vô khuẩn. Trả ``{name, status, missing, damaged, incident}``."""
	_require_role()
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)
	if doc.docstatus != 1 or doc.status != "Received":
		raise _blocked(
			"LOANER_NOT_RECEIVED",
			_("Loaner set is not on loan"),
			_("Loaner set {0} is {1}; only a received loaner set can be returned.").format(
				doc.name, _(doc.status, context=DOCTYPE)
			),
			_("Open the loaner set that is still on loan."),
		)
	values = _check_lines(doc, lines)
	status = frappe.db.get_value("Set Unit", doc.set_unit, "status")
	if status != "Sterile":
		raise _blocked(
			"LOANER_NOT_REPROCESSED",
			_("Loaner set not reprocessed"),
			_(
				"Set {0} is {1}; a loaner set is returned only after the full reprocessing chain (T1 to T5)."
			).format(doc.set_unit, _(status, context="Set Unit")),
			_("Send the set through receipt, washing, assembly, packing and sterilization, then return it."),
		)
	missing_lines, missing, damaged = [], 0, 0
	for row in doc.items:
		returned, broken, row_note = values[row.idx]
		frappe.db.set_value(
			row.doctype,
			row.name,
			{"returned_qty": returned, "damaged_qty": broken, "note": row_note},
			update_modified=False,
		)
		missing += cint(row.qty) - returned
		damaged += broken
		if returned < cint(row.qty):
			missing_lines.append(
				{"instrument": row.instrument, "name": row.instrument_name, "qty": cint(row.qty) - returned}
			)
	note = cstr(note).strip()
	reason = _("Returned to vendor: {0}").format(doc.name)
	step_gate.return_loaner(doc.set_unit, reason)
	code_registry.disable(doc.set_unit, reason)
	incidents = []
	if missing_lines:
		incidents = extension.run(
			RETURNED_HOOK,
			{"loaner": doc.name, "set_unit": doc.set_unit, "missing": missing_lines, "note": note},
		)
	fields = {
		"status": "Returned",
		"returned_on": now_datetime(),
		"returned_by": frappe.session.user,
		"return_note": note,
		"missing_count": missing,
		"damaged_count": damaged,
		"incident": incidents[0] if incidents else None,
	}
	doc.db_set(fields)
	audit.log(
		"Update",
		DOCTYPE,
		doc.name,
		new={**fields, "returned_on": str(fields["returned_on"])},
		reason=note or None,
	)
	return {
		"name": doc.name,
		"status": "Returned",
		"missing": missing,
		"damaged": damaged,
		"incident": fields["incident"],
	}


# --- Gia hạn và quá hạn ----------------------------------------------------------------------------------------------


def extend(name, expected_return, reason):
	"""R02 gia hạn ngày trả kèm lý do (UC-04 A2). Trả ``{name, expected_return}``."""
	_require_role()
	reason = cstr(reason).strip()
	if not reason:
		raise _blocked(
			"REASON_REQUIRED",
			_("Reason is required"),
			_("No reason was entered for extending the loan."),
			_("Enter why the loaner set is kept longer."),
		)
	doc = frappe.get_doc(DOCTYPE, name, for_update=True)
	if doc.docstatus != 1 or doc.status != "Received":
		raise _blocked(
			"LOANER_NOT_RECEIVED",
			_("Loaner set is not on loan"),
			_("Loaner set {0} is {1}; only a received loaner set can be extended.").format(
				doc.name, _(doc.status, context=DOCTYPE)
			),
			_("Open the loaner set that is still on loan."),
		)
	new_date = getdate(expected_return)
	if new_date < getdate(doc.received_on):
		raise _dates_block(doc.received_on, new_date)
	old = {"expected_return": str(doc.expected_return)}
	doc.db_set({"expected_return": new_date, "extension_reason": reason, "last_reminded_on": None})
	audit.log("Update", DOCTYPE, doc.name, old=old, new={"expected_return": str(new_date)}, reason=reason)
	return {"name": doc.name, "expected_return": str(new_date)}


def _users_with(role):
	holders = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
	if not holders:
		return []
	return frappe.get_all("User", filters={"name": ["in", holders], "enabled": 1}, pluck="name")


def remind_overdue():
	"""Việc hằng ngày (FR-M1-07.4, UC-04 E1): bộ mượn quá ngày trả chưa có biên bản trả → nhắc R02, mỗi ngày một lần."""
	day = getdate(today())
	users = _users_with(ROLE)
	for row in frappe.get_all(
		DOCTYPE,
		filters={"docstatus": 1, "status": "Received", "expected_return": ("<", day)},
		fields=["name", "set_unit", "expected_return", "last_reminded_on"],
	):
		if row.last_reminded_on and getdate(row.last_reminded_on) >= day:
			continue
		subject = _("Loaner set {0} ({1}) is overdue since {2}").format(
			row.name, row.set_unit, frappe.format(row.expected_return, {"fieldtype": "Date"})
		)
		for user in users:
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": user,
					"type": "Alert",
					"subject": subject,
					"document_type": DOCTYPE,
					"document_name": row.name,
				}
			).insert(ignore_permissions=True)
		frappe.db.set_value(DOCTYPE, row.name, "last_reminded_on", day, update_modified=False)


# --- Biên bản in (Print Format) --------------------------------------------------------------------------------------


def _stamp(value):
	return frappe.utils.get_datetime(value).strftime(DATETIME_FORMAT) if value else ""


def tc_loaner_context(name: str) -> dict:
	"""Ngữ cảnh biên bản nhận / trả bộ mượn; chỉ người đọc được phiếu mới in được."""
	doc = frappe.get_doc(DOCTYPE, name)
	doc.check_permission("read")

	def date(value):
		return frappe.utils.formatdate(value, "dd/mm/yyyy") if value else ""

	return {
		"tc": token_values(),
		"name": doc.name,
		"status": doc.status,
		"draft": doc.docstatus == 0,
		"supplier": frappe.db.get_value("Supplier", doc.supplier, "supplier_name") or doc.supplier,
		"set_name": doc.set_name,
		"set_id": doc.set_unit or "",
		"set_type": doc.set_type or "",
		"method": doc.method,
		"department": frappe.db.get_value("Department", doc.department, "department_name") or doc.department,
		"received_on": date(doc.received_on),
		"expected_return": date(doc.expected_return),
		"returned_on": _stamp(doc.returned_on),
		"returned_by": frappe.db.get_value("User", doc.returned_by, "full_name") or doc.returned_by or "",
		"return_note": doc.return_note or "",
		"missing_count": cint(doc.missing_count),
		"damaged_count": cint(doc.damaged_count),
		"incident": doc.incident or "",
		"items": [
			{
				"index": row.idx,
				"name": row.instrument_name,
				"code": row.instrument or "",
				"qty": cint(row.qty),
				"returned": cint(row.returned_qty),
				"damaged": cint(row.damaged_qty),
				"missing": cint(row.qty) - cint(row.returned_qty),
				"note": row.note or "",
			}
			for row in doc.items
		],
	}
