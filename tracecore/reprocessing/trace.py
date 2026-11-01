"""Truy xuất hai chiều (M2, FEAT-028, UC-14 bước 1 và 2, FR-M2-19, NFR-PERF-04, NFR-SEC-02).

Một chuỗi là một chu trình của một bộ (Set ID, số chu trình). Tiêu chí (mã BN, Set ID, Cycle ID, mẻ, máy, người,
khoảng ngày) được quy về tập chuỗi rồi lấy giao; mỗi chuỗi trả sự kiện theo thời gian với người, thời điểm, trạm,
thiết bị: cổng T1 đến T5 từ ``Step Gate Result``, T6 nhập kho, T7 cấp phát, T8 sử dụng. Mã bệnh nhân tra bằng hash
(``core.crypto.patient_hash``) và chỉ trả ở dạng che. R01/R02 xem mọi chuỗi, R08 chỉ chuỗi của khoa mình.
"""

import frappe
from frappe import _
from frappe.utils import add_days, format_datetime, formatdate, get_datetime, getdate

from tracecore.core import crypto
from tracecore.reprocessing import cycle_time, washing

MAX_CHAINS = 50
ALL_ROLES = ("TC R01", "TC R02", "System Manager")
WARD_ROLE = "TC R08"
STEP_LABELS = {
	"T1": "Receiving",
	"T2": "Washing",
	"T3": "Assembly",
	"T4": "Packing",
	"T5": "Sterilization",
	"T6": "Sterile storage",
	"T7": "Issuing",
	"T8": "Usage",
}
EQUIPMENT_REFS = ("Wash Batch", "Sterilization Load")


def _scope():
	"""None = mọi khoa; tên khoa = chỉ khoa đó (R08); không được xem → PermissionError."""
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or roles & set(ALL_ROLES):
		return None
	if WARD_ROLE in roles:
		department = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "department")
		return department or "-"
	frappe.throw(_("Only R01, R02 or department staff can trace sets."), frappe.PermissionError)


# --- Tiêu chí → chuỗi ------------------------------------------------------------------------------------


def _keys(rows):
	return {(row.set_unit, int(row.cycle_no or 0)) for row in rows if row.set_unit and row.cycle_no}


def _packs(filters):
	return frappe.get_all("Pack", filters={"docstatus": 1, **filters}, fields=["set_unit", "cycle_no"])


def _gates(filters):
	return frappe.get_all("Step Gate Result", filters=filters, fields=["set_unit", "cycle_no"])


def _by_patient(code):
	packs = frappe.get_all(
		"Usage Record", filters={"patient_code_hash": crypto.patient_hash(code)}, pluck="pack"
	)
	return _keys(_packs({"name": ["in", packs]})) if packs else set()


def _by_equipment(equipment):
	keys = set()
	for doctype in EQUIPMENT_REFS:
		refs = frappe.get_all(doctype, filters={"equipment": equipment}, pluck="name")
		if refs:
			keys |= _keys(_gates({"ref_doctype": doctype, "ref_name": ["in", refs]}))
			if doctype == "Sterilization Load":
				keys |= _keys(_packs({"load": ["in", refs]}))
	return keys


def _by_user(user):
	keys = _keys(_gates({"recorded_by": user}))
	for doctype, field in (("Sterile Putaway", "putaway_by_user"), ("Usage Record", "scanned_by_user")):
		packs = frappe.get_all(doctype, filters={field: user}, pluck="pack")
		if packs:
			keys |= _keys(_packs({"name": ["in", packs]}))
	notes = frappe.get_all("Issue Note", filters={"issued_by_user": user, "docstatus": 1}, pluck="name")
	if notes:
		packs = frappe.get_all("Issue Note Pack", filters={"parent": ["in", notes]}, pluck="pack")
		keys |= _keys(_packs({"name": ["in", packs]})) if packs else set()
	return keys


def _candidates(patient_code, set_id, cycle_id, load, equipment, user, start, end):
	sets = []
	if patient_code:
		sets.append(_by_patient(patient_code))
	if cycle_id:
		sets.append(_keys(_packs({"name": cycle_id})))
	if set_id:
		sets.append(_keys(_gates({"set_unit": set_id})) | _keys(_packs({"set_unit": set_id})))
	if load:
		sets.append(
			_keys(_packs({"load": load}))
			| _keys(_gates({"ref_doctype": "Sterilization Load", "ref_name": load}))
		)
	if equipment:
		sets.append(_by_equipment(equipment))
	if user:
		sets.append(_by_user(user))
	if not sets:
		sets.append(_keys(_gates({"recorded_at": ["between", [start, end]]})))
	keys = sets[0]
	for other in sets[1:]:
		keys &= other
	return keys


# --- Chuỗi sự kiện ---------------------------------------------------------------------------------------


def _event(step, at, user, station, ref_doctype, ref_name, **extra):
	return {
		"step": step,
		"label": _(STEP_LABELS[step], context="Pack Trace"),
		"at": get_datetime(at) if at else None,
		"user": user,
		"user_name": frappe.utils.get_fullname(user) if user else None,
		"station": station,
		"ref_doctype": ref_doctype,
		"ref_name": ref_name,
		**extra,
	}


def cycle_detail(ref_doctype, ref_name):
	"""Giờ bắt đầu/kết thúc, thời lượng so với chuẩn, người nạp và người dỡ của lô rửa / mẻ tiệt khuẩn (A-73); {} nếu khác."""
	if ref_doctype not in EQUIPMENT_REFS or not ref_name:
		return {}
	# mẻ tiệt khuẩn cũ chưa có `unloaded_by`: người giải phóng (A-86)
	fallback = [] if ref_doctype == "Wash Batch" else ["released_by"]
	doc = frappe.db.get_value(
		ref_doctype,
		ref_name,
		["program", "operator", "started_at", "ended_at", "unloaded_by", *fallback],
		as_dict=True,
	)
	if not doc:
		return {}
	detail = {
		"operator": doc.operator,
		"unloaded_by": doc.unloaded_by or doc.get("released_by"),
		"started_at": doc.started_at,
		"ended_at": doc.ended_at,
		"duration": cycle_time.for_doc(doc),
	}
	if ref_doctype == "Wash Batch":
		detail["indicator"] = washing.wash_indicator_of(ref_name)  # A-77
	return detail


def wash_indicator_line(indicator):
	"""Một dòng chữ về chỉ thị rửa cho báo cáo: vật tư · lô · hạn · kết quả · người đọc · giờ đọc (A-77)."""
	if not indicator:
		return None
	parts = [
		indicator["item"],
		_("Lot {0}").format(indicator["lot"]) if indicator["lot"] else None,
		_("Expires {0}").format(formatdate(indicator["lot_expiry"])) if indicator["lot_expiry"] else None,
		_(indicator["result"]),
		indicator["read_by_name"] or indicator["read_by"],
		format_datetime(indicator["read_at"], "dd/MM/yyyy HH:mm") if indicator["read_at"] else None,
	]
	return " · ".join(part for part in parts if part)


def wash_indicator_text(set_unit, cycle_no):
	"""Dòng chỉ thị rửa của chu trình `cycle_no` của bộ `set_unit`, hoặc None (dòng lệnh thu hồi, A-77)."""
	batch = frappe.db.get_value(
		"Step Gate Result",
		{"set_unit": set_unit, "cycle_no": cycle_no, "step": "T2", "ref_doctype": "Wash Batch"},
		"ref_name",
	)
	return wash_indicator_line(washing.wash_indicator_of(batch)) if batch else None


def _equipment(ref_doctype, ref_name):
	if ref_doctype in EQUIPMENT_REFS and ref_name:
		return frappe.db.get_value(ref_doctype, ref_name, "equipment")
	return None


def _pack_events(pack):
	events = []
	for row in frappe.get_all(
		"Sterile Putaway",
		filters={"pack": pack},
		fields=["name", "putaway_by_user", "station", "putaway_at", "location", "action", "creation"],
	):
		events.append(
			_event(
				"T6",
				row.putaway_at or row.creation,
				row.putaway_by_user,
				row.station,
				"Sterile Putaway",
				row.name,
				location=row.location,
			)
		)
	notes = frappe.db.sql(
		"""select note.name, note.department, note.station, note.issued_by_user,
			coalesce(note.issued_at, note.creation) as issued_at, note.recipient_name
		from `tabIssue Note Pack` row join `tabIssue Note` note on note.name = row.parent
		where row.pack = %s and note.docstatus = 1""",
		pack,
		as_dict=True,
	)
	for note in notes:
		events.append(
			_event(
				"T7",
				note.issued_at,
				note.issued_by_user,
				note.station,
				"Issue Note",
				note.name,
				department=note.department,
				recipient=note.recipient_name,
			)
		)
	used = frappe.db.get_value("Usage Record", {"pack": pack, "docstatus": 1}, "name")
	if used:
		record = frappe.get_doc("Usage Record", used)
		events.append(
			_event(
				"T8",
				record.used_at or record.creation,
				record.scanned_by_user,
				record.station,
				"Usage Record",
				record.name,
				department=record.department,
				patient_code_masked=record.patient_code_masked,
				surgery_code=record.surgery_code,
			)
		)
	return events


def _chain(set_unit, cycle_no):
	events = []
	for gate in frappe.get_all(
		"Step Gate Result",
		filters={"set_unit": set_unit, "cycle_no": cycle_no},
		fields=[
			"step",
			"result",
			"ref_doctype",
			"ref_name",
			"station",
			"recorded_by",
			"recorded_at",
			"modified",
		],
	):
		if gate.result == "Pending" or gate.step not in STEP_LABELS:
			continue
		events.append(
			_event(
				gate.step,
				gate.recorded_at or gate.modified,
				gate.recorded_by,
				gate.station,
				gate.ref_doctype,
				gate.ref_name,
				result=gate.result,
				equipment=_equipment(gate.ref_doctype, gate.ref_name),
				**cycle_detail(gate.ref_doctype, gate.ref_name),
			)
		)
	packs = frappe.get_all(
		"Pack",
		filters={"set_unit": set_unit, "cycle_no": cycle_no, "docstatus": 1},
		fields=["name", "status", "load"],
		order_by="creation desc",
	)
	pack = next((row for row in packs if row.status != "Void"), packs[0] if packs else None)
	if pack:
		events += _pack_events(pack.name)
	events.sort(key=lambda event: event["at"] or get_datetime("1900-01-01"))
	usage = next((event for event in events if event["step"] == "T8"), None)
	issued = next((event for event in reversed(events) if event["step"] == "T7"), None)
	return {
		"set_id": set_unit,
		"set_type": frappe.db.get_value("Set Unit", set_unit, "set_type"),
		"cycle_no": cycle_no,
		"cycle_id": pack.name if pack else None,
		"pack_status": pack.status if pack else None,
		"load": pack.load if pack else None,
		"equipment": frappe.db.get_value("Sterilization Load", pack.load, "equipment")
		if pack and pack.load
		else None,
		"department": (usage or issued or {}).get("department"),
		"patient_code_masked": usage.get("patient_code_masked") if usage else None,
		"events": events,
	}


def query(
	patient_code=None,
	set_id=None,
	cycle_id=None,
	load=None,
	equipment=None,
	user=None,
	from_date=None,
	to_date=None,
):
	"""Chuỗi sự kiện theo tiêu chí (FR-M2-19); trả ``{"chains": [...], "suggestion": str | None}``."""
	if not any((patient_code, set_id, cycle_id, load, equipment, user, from_date, to_date)):
		frappe.throw(_("Enter at least one search criterion."))
	scope = _scope()
	start = get_datetime(getdate(from_date)) if from_date else get_datetime("1900-01-01")
	end = get_datetime(add_days(getdate(to_date), 1)) if to_date else get_datetime("2999-01-01")
	chains = []
	for set_unit, cycle_no in _candidates(patient_code, set_id, cycle_id, load, equipment, user, start, end):
		chain = _chain(set_unit, cycle_no)
		if scope is not None and chain["department"] != scope:
			continue
		if (from_date or to_date) and not any(
			event["at"] and start <= event["at"] < end for event in chain["events"]
		):
			continue
		chains.append(chain)
	chains.sort(
		key=lambda chain: max((e["at"] for e in chain["events"] if e["at"]), default=start), reverse=True
	)
	chains = chains[:MAX_CHAINS]
	suggestion = (
		None
		if chains
		else _(
			"No result. Check the code, try only one criterion (Set ID, Cycle ID or load), or widen the date range."
		)
	)
	return {"chains": chains, "suggestion": suggestion}
