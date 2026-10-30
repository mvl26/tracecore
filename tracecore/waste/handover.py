"""Phiếu bàn giao chất thải (FEAT-049, UC-36, FR-M10-03.5, FR-M10-04, .1-.6, BRU-WST-003, BRU-WST-004, A-62).

Trạm lập theo bốn bước: `create` chọn đơn vị, `add`/`add_type` thêm túi đang lưu giữ, `sign` ghi kg, chứng từ và chữ ký,
`submit` kiểm và ghi sổ. Chênh lệch vượt ngưỡng cần lý do và R02 duyệt bằng thẻ + PIN trên kiosk; NC tạo trong lúc ghi
sổ. Giá lấy lúc ghi sổ và lưu vào dòng nên đổi giá sau đó không tính lại phiếu cũ (BRU-CST-002). Chi phí M7 đi qua hook.
"""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, now_datetime

from tracecore.core import extension, notification
from tracecore.core.errors import Block, BlockedError
from tracecore.waste import vendors
from tracecore.waste.collection import NC_HOOK
from tracecore.waste.storage import DEFAULT_VARIANCE_PERCENT, SETTINGS, STORED

DOCTYPE = "Waste Handover"
CONTAINER = "Waste Container"
HANDED_OVER = "Handed Over"
WEIGHT_DIGITS = 3
HAZARD_COLORS = ("Yellow", "Black")
AFTER_HOOK = "tracecore_after_waste_handover"
AFTER_CANCEL_HOOK = "tracecore_after_waste_handover_cancel"
POSTED_EVENT = "WASTE_HANDOVER_POSTED"
SCALE, MANUAL = "Scale", "Manual"


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _not_permitted(waste_types, vendor):
	return _blocked(
		"WASTE_VENDOR_NOT_PERMITTED",
		_("The vendor cannot take this waste"),
		_("{0} has no valid license and contract for: {1}.").format(vendor, ", ".join(waste_types) or "-"),
		_("Choose another vendor, or ask R09 to update the license and contract."),
	)


def _draft(name):
	doc = frappe.get_doc(DOCTYPE, name, for_update=True) if name and frappe.db.exists(DOCTYPE, name) else None
	if not doc or doc.docstatus != 0:
		raise _blocked(
			"WASTE_HANDOVER_INVALID",
			_("Handover is not open"),
			_("Handover {0} cannot be changed.").format(name or "-"),
			_("Start a new handover."),
		)
	return doc


def _save(doc):
	doc.flags.ignore_permissions = True
	doc.save()
	return doc


# --- lập phiếu --------------------------------------------------------------------------------------------------------


def create(station, employee, vendor):
	if (
		not vendor
		or not frappe.db.exists("Waste Treatment Vendor", vendor)
		or not vendors.permitted_types(vendor)
	):
		raise _not_permitted([], vendor or "-")
	doc = frappe.get_doc({"doctype": DOCTYPE, "vendor": vendor, "station": station, "prepared_by": employee})
	doc.flags.ignore_permissions = True
	return doc.insert()


def _stored_row(container):
	row = (
		frappe.db.get_value(
			CONTAINER,
			container,
			["name", "status", "waste_type", "weight_kg", "department", "collected_at"],
			as_dict=True,
		)
		if container
		else None
	)
	if not row or row.status != STORED:
		raise _blocked(
			"WASTE_BAG_NOT_STORED",
			_("Bag is not in the store"),
			_("Bag {0} is not stored.").format(container or "-"),
			_("Store the bag first, or check the code."),
		)
	return row


def _check_not_on_handover(container):
	parents = frappe.get_all(
		"Waste Handover Container", filters={"container": container, "parenttype": DOCTYPE}, pluck="parent"
	)
	if parents and frappe.get_all(DOCTYPE, filters={"name": ["in", parents], "docstatus": 0}, limit=1):
		raise _blocked(
			"WASTE_BAG_ALREADY_ON_HANDOVER",
			_("Bag is already on a handover"),
			_("Bag {0} is already on an open handover.").format(container),
			_("Remove it from that handover first."),
		)


def _append(doc, row):
	doc.append(
		"containers",
		{
			"container": row.name,
			"waste_type": row.waste_type,
			"weight_kg": row.weight_kg,
			"department": row.department,
			"collected_at": row.collected_at,
		},
	)


def add(name, container):
	doc = _draft(name)
	if container:
		_check_not_on_handover(container)
	row = _stored_row(container)
	if not vendors.permitted(doc.vendor, row.waste_type):
		raise _not_permitted([row.waste_type], doc.vendor)
	_append(doc, row)
	return _save(doc)


def add_type(name, waste_type):
	"""UC-36 bước 2: lấy cả tồn của một loại theo FIFO; túi đã nằm trên phiếu mở khác thì bỏ qua."""
	doc = _draft(name)
	if not vendors.permitted(doc.vendor, waste_type):
		raise _not_permitted([waste_type], doc.vendor)
	taken = {row.container for row in doc.containers}
	for item in fifo(waste_type):
		if item["name"] in taken or item["on_handover"]:
			continue
		_append(doc, _stored_row(item["name"]))
	return _save(doc)


def remove(name, container):
	doc = _draft(name)
	doc.set("containers", [row for row in doc.containers if row.container != container])
	return _save(doc)


def _open_on_handover():
	rows = frappe.db.sql(
		"""select c.container from `tabWaste Handover Container` c
		inner join `tabWaste Handover` h on h.name = c.parent and c.parenttype = 'Waste Handover'
		where h.docstatus = 0""",
		as_dict=True,
	)
	return {row.container for row in rows}


def fifo(waste_type):
	"""FR-M10-03.4, .5: túi quá hạn lên đầu, rồi thu gom sớm nhất trước."""
	busy = _open_on_handover()
	rows = frappe.get_all(
		CONTAINER,
		filters={"status": STORED, "waste_type": waste_type},
		fields=[
			"name",
			"waste_type",
			"weight_kg",
			"collected_at",
			"storage_due",
			"overdue_at",
			"storage_location",
		],
	)
	rows.sort(key=lambda row: (0 if row.overdue_at else 1, row.collected_at, row.name))
	return [{**row, "on_handover": row.name in busy} for row in rows]


def _skipped(doc):
	"""Túi cùng loại thu gom sớm hơn mà phiếu không lấy (FR-M10-03.5, UC-35 E5)."""
	chosen = {row.container for row in doc.containers}
	skipped = []
	for waste_type in {row.waste_type for row in doc.containers}:
		mine = [row.collected_at for row in doc.containers if row.waste_type == waste_type]
		latest = max(frappe.utils.get_datetime(value) for value in mine)
		for item in fifo(waste_type):
			if (
				item["name"] not in chosen
				and not item["on_handover"]
				and frappe.utils.get_datetime(item["collected_at"]) < latest
			):
				skipped.append(item["name"])
	return sorted(skipped)


def validate(doc):
	"""Dòng tổng theo loại luôn dựng lại từ các túi; kg bàn giao đã nhập được giữ."""
	old = {row.waste_type: row for row in doc.get("lines") or []}
	grouped = {}
	for row in doc.containers:
		grouped.setdefault(row.waste_type, []).append(row)
	lines = []
	for waste_type, rows in grouped.items():
		before = old.get(waste_type)
		collected = round(sum(flt(row.weight_kg) for row in rows), WEIGHT_DIGITS)
		handed = flt(before.handover_kg) if before else 0
		lines.append(
			{
				"waste_type": waste_type,
				"qty": len(rows),
				"collected_kg": collected,
				"handover_kg": handed,
				"weight_source": before.weight_source if before else None,
				"weight_confirmed": cint(before.weight_confirmed) if before else 0,
				"difference_kg": round(handed - collected, WEIGHT_DIGITS) if handed else 0,
				"difference_percent": abs(handed - collected) * 100 / collected
				if handed and collected
				else 0,
			}
		)
	doc.set("lines", lines)
	doc.total_containers = len(doc.containers)
	doc.total_collected_kg = round(sum(line["collected_kg"] for line in lines), WEIGHT_DIGITS)
	doc.total_handover_kg = round(sum(line["handover_kg"] for line in lines), WEIGHT_DIGITS)


# --- kg, chứng từ, chữ ký ---------------------------------------------------------------------------------------------


def _apply_weights(doc, weights):
	rows = {row.waste_type: row for row in doc.lines}
	for item in weights or []:
		row = rows.get(item.get("waste_type"))
		if not row:
			continue
		try:
			kg = flt(cstr(item.get("handover_kg")).replace(",", "."))
		except ValueError:
			kg = 0
		source = SCALE if item.get("weight_source") == SCALE else MANUAL
		confirmed = 1 if item.get("weight_confirmed") else 0
		if source == MANUAL and not confirmed:
			raise _blocked(
				"WASTE_WEIGHT_UNCONFIRMED",
				_("Manual weight is not confirmed"),
				_("A weight typed by hand needs the confirmation tick."),
				_("Tick the confirmation or take the weight from the scale."),
			)
		row.update({"handover_kg": kg, "weight_source": source, "weight_confirmed": confirmed})


SIGN_FIELDS = (
	"hazard_document_no",
	"transporter",
	"contract_no",
	"hazard_document_scan",
	"vehicle_plate",
	"vendor_signer",
	"vendor_signature",
	"variance_reason",
	"fifo_reason",
)


def sign(name, employee, weights=None, document_pending=None, **values):
	"""Ghi kg, chứng từ, biển số, chữ ký; R07 ký bằng thẻ của phiên trạm (FR-M10-04.2)."""
	doc = _draft(name)
	_apply_weights(doc, weights)
	for field in SIGN_FIELDS:
		if field in values:
			doc.set(field, cstr(values[field]).strip() or None)
	if document_pending is not None:
		doc.document_pending = 1 if document_pending else 0
	doc.signed_by = employee
	return _save(doc)


def _variance_limit():
	return flt(frappe.db.get_single_value(SETTINGS, "waste_variance_percent")) or DEFAULT_VARIANCE_PERCENT


def over_limit(doc):
	limit = _variance_limit()
	return [row for row in doc.lines if flt(row.difference_percent) > limit]


def _has_hazard(doc):
	colors = {frappe.db.get_value("Waste Type", row.waste_type, "color_code") for row in doc.lines}
	return bool(colors & set(HAZARD_COLORS))


def view(doc):
	return {
		"name": doc.name,
		"vendor": doc.vendor,
		"docstatus": doc.docstatus,
		"waste_types": vendors.permitted_types(doc.vendor),
		"lines": [
			{
				"waste_type": row.waste_type,
				"qty": row.qty,
				"collected_kg": row.collected_kg,
				"handover_kg": row.handover_kg,
				"difference_percent": row.difference_percent,
			}
			for row in doc.lines
		],
		"containers": [row.container for row in doc.containers],
		"fifo_skipped": _skipped(doc) if doc.docstatus == 0 else [],
		"over_limit": [row.waste_type for row in over_limit(doc)],
		"needs_document": _has_hazard(doc),
		"total_cost": doc.total_cost,
	}


# --- ghi sổ -----------------------------------------------------------------------------------------------------------


def _check_before_post(doc, approver):
	if not doc.containers:
		raise _blocked(
			"WASTE_HANDOVER_EMPTY",
			_("Nothing to hand over"),
			_("The handover has no bag."),
			_("Scan the bags, or add a waste type from the store."),
		)
	blocked = [row.waste_type for row in doc.lines if not vendors.permitted(doc.vendor, row.waste_type)]
	if blocked:
		raise _not_permitted(blocked, doc.vendor)
	if any(flt(row.handover_kg) <= 0 for row in doc.lines):
		raise _blocked(
			"WASTE_WEIGHT_MISSING",
			_("Handed over weight is missing"),
			_("Every waste type needs the weight handed over."),
			_("Weigh each type, or type the weight and confirm it."),
		)
	if _skipped(doc) and not cstr(doc.fifo_reason).strip():
		raise _blocked(
			"WASTE_FIFO_REASON",
			_("Older bags were skipped"),
			_("Bags collected earlier stay in the store: {0}.").format(", ".join(_skipped(doc))),
			_("Add the older bags, or enter the reason for skipping them."),
		)
	_check_variance(doc, approver)
	_check_document(doc)
	if not doc.signed_by or not (
		(doc.vendor_signature and cstr(doc.vendor_signer).strip()) or doc.minutes_photo
	):
		raise _blocked(
			"WASTE_SIGNATURE_REQUIRED",
			_("Signatures are missing"),
			_("The handover needs the signature of R07 and of the vendor, or a photo of the signed minutes."),
			_("Ask the vendor representative to sign."),
		)


def _check_variance(doc, approver):
	over = over_limit(doc)
	if not over:
		return
	detail = ", ".join(f"{row.waste_type} {flt(row.difference_percent):.1f} %" for row in over)
	if not cstr(doc.variance_reason).strip():
		raise _blocked(
			"WASTE_VARIANCE_REASON",
			_("Weight difference needs a reason"),
			_("Difference above the limit: {0}.").format(detail),
			_("Enter the reason, then ask R02 to approve."),
		)
	if not approver:
		raise _blocked(
			"WASTE_VARIANCE_APPROVAL",
			_("R02 must approve the weight difference"),
			_("Difference above the limit: {0}.").format(detail),
			_("Ask R02 to scan their card and enter their PIN on this station."),
		)
	doc.variance_approved_by = approver


def _check_document(doc):
	if not _has_hazard(doc) or cint(doc.document_pending):
		return
	missing = [
		doc.meta.get_label(field)
		for field in ("hazard_document_no", "transporter", "contract_no", "hazard_document_scan")
		if not doc.get(field)
	]
	if missing:
		raise _blocked(
			"WASTE_DOCUMENT_REQUIRED",
			_("Hazardous waste document is missing"),
			_("Missing: {0}.").format(", ".join(_(label) for label in missing)),
			_("Enter the document, or tick that the document comes later."),
		)


def submit(name, approver=None):
	"""Ghi sổ; `approver` là Employee R02 đã qua `consume_approver_proof` ở RPC."""
	doc = _draft(name)
	_check_before_post(doc, approver)
	doc.flags.tc_handover_checked = True
	doc.flags.ignore_permissions = True
	doc.submit()
	return doc


def before_submit(doc):
	"""Chốt giá theo ngày bàn giao; đi Desk cũng phải qua đủ kiểm tra."""
	if not doc.flags.tc_handover_checked:
		_check_before_post(doc, doc.variance_approved_by)
	doc.handover_at = now_datetime()
	total = 0
	for row in doc.lines:
		row.rate_per_kg = vendors.rate_for(doc.vendor, row.waste_type, doc.handover_at)
		row.amount = round(flt(row.handover_kg) * flt(row.rate_per_kg))
		total += row.amount
	doc.total_cost = total


def on_submit(doc):
	for row in doc.containers:
		_stored_row(row.container)
		frappe.db.set_value(CONTAINER, row.container, {"status": HANDED_OVER, "handover": doc.name})
	if over_limit(doc):
		extension.run(
			NC_HOOK,
			{
				"kind": "variance",
				"handover": doc.name,
				"employee": doc.signed_by or doc.prepared_by,
				"detail": ", ".join(
					f"{row.waste_type} {flt(row.difference_percent):.1f} %" for row in over_limit(doc)
				),
				"reason": doc.variance_reason,
			},
		)
	results = extension.run(AFTER_HOOK, doc)
	if results:
		doc.db_set("cost_entry", results[0])
	notification.emit(
		POSTED_EVENT,
		doc,
		subject=_("Waste handover {0} posted").format(doc.name),
		message=_("{0} bags, {1} kg to {2}.").format(doc.total_containers, doc.total_handover_kg, doc.vendor),
	)


def on_cancel(doc):
	"""FR-M10-04.6: hủy phiếu thì túi về kho và chi phí bị hủy; lập phiếu mới nếu cần điều chỉnh."""
	for row in doc.containers:
		frappe.db.set_value(CONTAINER, row.container, {"status": STORED, "handover": None})
	extension.run(AFTER_CANCEL_HOOK, doc)


def attach_document(name, document_no, scan, transporter=None, contract_no=None):
	"""UC-36 A4: đính chứng từ CTNH gửi sau vào phiếu đã ghi sổ."""
	doc = frappe.get_doc(DOCTYPE, name)
	if doc.docstatus != 1 or not cstr(document_no).strip() or not scan:
		raise _blocked(
			"WASTE_DOCUMENT_REQUIRED",
			_("Hazardous waste document is missing"),
			_("Enter the document number and attach the scan."),
			_("Enter the document, then save again."),
		)
	doc.db_set(
		{
			"hazard_document_no": cstr(document_no).strip(),
			"hazard_document_scan": scan,
			"transporter": transporter or doc.transporter,
			"contract_no": contract_no or doc.contract_no,
			"document_pending": 0,
		}
	)
	return doc
