"""Thu gom chất thải theo khoa (FEAT-047, UC-34, FR-M10-02, .1, .3-.6, FR-M10-01.5, A-60 W1, W3, W4, W9-W12).

Cùng cách làm với thu gom đồ vải nhưng không import M3 (R1). Người giao và khoa lấy từ thẻ, người thu gom là Employee
của phiên thẻ. Ghi sổ phiếu sinh một `Waste Container` mã `CT-` cho từng túi, in nhãn, bắt đầu tính giờ lưu từ lúc thu
gom. Túi phân loại sai bị giữ (`Held`), không tính vào tổng kg, có NC qua hook, chỉ R02 mở.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, cstr, flt, get_datetime, now_datetime

from tracecore.core import code_registry, extension, station_auth
from tracecore.core import label_pdf as core_label_pdf
from tracecore.core import print as core_print
from tracecore.core.errors import Block, BlockedError

WEIGHT_DIGITS = 3
SCALE, MANUAL, CONVERTED = "Scale", "Manual", "Converted"
COLLECTED, HELD, CANCELLED = "Collected", "Held", "Cancelled"
NC_HOOK = "tracecore_waste_nc"
LABEL_OBJECT = "Waste Container"


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


# --- người giao -------------------------------------------------------------------------------------------------------


def _giver_rejected():
	return _blocked(
		"WASTE_GIVER_INVALID",
		_("Delivering card is not valid"),
		_("The card does not belong to an active employee of a ward."),
		_("Ask the ward staff for their employee card, or call R02."),
	)


def giver(card):
	"""Người giao theo thẻ: ``{"employee", "employee_name", "department"}``; thẻ lạ, tắt hoặc không thuộc khoa → chặn."""
	card = station_auth.normalize_card_id(card) if isinstance(card, str) else None
	row = (
		frappe.db.get_value(
			"Employee",
			{"tc_card_id": card},
			["name", "employee_name", "department", "status", "tc_card_enabled"],
			as_dict=True,
		)
		if card
		else None
	)
	if not row or row.status != "Active" or not cint(row.tc_card_enabled) or not row.department:
		raise _giver_rejected()
	if not frappe.db.get_value("Department", row.department, "tc_is_ward"):
		raise _giver_rejected()
	return {"employee": row.name, "employee_name": row.employee_name, "department": row.department}


# --- danh mục ---------------------------------------------------------------------------------------------------------


def catalog():
	"""Loại đang dùng cho màn thu gom (E4: loại ngừng dùng không chọn được)."""
	return frappe.get_all(
		"Waste Type",
		filters={"is_active": 1},
		fields=["name", "waste_group", "color_code", "std_weight_kg"],
		order_by="name asc",
	)


# --- kiểm dòng --------------------------------------------------------------------------------------------------------


def _type_error(value):
	return _blocked(
		"WASTE_TYPE_INVALID",
		_("Waste type is not valid"),
		_("Waste type {0} is not an active type. A line holds exactly one type.").format(
			value if isinstance(value, str) else "-"
		),
		_("Choose one active waste type for this line."),
	)


def _qty_error():
	return _blocked(
		"WASTE_QTY_INVALID",
		_("Quantity is not valid"),
		_("Bags must be a whole number above 0 and weight cannot be negative."),
		_("Correct the bags and the weight of the line."),
	)


def _number(value):
	if value in (None, ""):
		return None
	if isinstance(value, bool) or not isinstance(value, int | float | str):
		raise _qty_error()
	try:
		return float(value)
	except ValueError:
		raise _qty_error() from None


def _prepare_line(row):
	name = row.get("waste_type")
	info = (
		frappe.db.get_value("Waste Type", name, ["std_weight_kg", "is_active"], as_dict=True)
		if isinstance(name, str) and name
		else None
	)
	if not info or not cint(info.is_active):
		raise _type_error(name)
	qty = _number(row.get("qty"))
	if qty is None or qty <= 0 or qty != int(qty):
		raise _qty_error()
	weight = _number(row.get("weight_kg"))
	if weight is not None and weight <= 0:
		raise _qty_error()
	misclassified = 1 if row.get("misclassified") else 0
	note = cstr(row.get("misclass_note")).strip()
	if misclassified and not note:
		raise _blocked(
			"WASTE_NOTE_REQUIRED",
			_("Note required"),
			_("A misclassified bag needs a note on what is wrong."),
			_("Enter the note, then confirm again."),
		)
	line = {
		"waste_type": name,
		"qty": int(qty),
		"misclassified": misclassified,
		"misclass_note": note or None,
		"std_weight_kg": flt(info.std_weight_kg),
	}
	if weight is None:
		line.update(weight_kg=None, weight_source=CONVERTED, weight_confirmed=0)
		return line
	source = row.get("weight_source")
	confirmed = 1 if row.get("weight_confirmed") else 0
	# nguồn lạ tính là nhập tay; nhập tay phải tick xác nhận ở server, không chỉ ở client (FR-M10-02.1)
	if source != SCALE and not confirmed:
		raise _blocked(
			"WASTE_WEIGHT_UNCONFIRMED",
			_("Manual weight is not confirmed"),
			_("A weight typed by hand needs the confirmation tick."),
			_("Tick the confirmation or take the weight from the scale."),
		)
	line.update(
		weight_kg=weight, weight_source=SCALE if source == SCALE else MANUAL, weight_confirmed=confirmed
	)
	return line


def _allocate(lines, total_kg):
	"""UC-34 A2: chia kg tổng của xe theo số túi nhân kg chuẩn; phần dư vào dòng cuối để tổng khớp."""
	total = _number(total_kg)
	shares = [line["std_weight_kg"] * line["qty"] for line in lines]
	if total is None or total <= 0 or sum(shares) <= 0:
		raise _blocked(
			"WASTE_TOTAL_INVALID",
			_("Total weight is not valid"),
			_("The total weight must be greater than 0."),
			_("Enter the weight of the whole cart."),
		)
	whole = sum(shares)
	weights = [round(total * share / whole, WEIGHT_DIGITS) for share in shares[:-1]]
	weights.append(round(total - sum(weights), WEIGHT_DIGITS))
	for line, weight in zip(lines, weights, strict=True):
		line.update(weight_kg=weight, weight_source=CONVERTED, weight_confirmed=0)


def _prepare(lines, total_kg):
	if not lines:
		raise _blocked(
			"WASTE_EMPTY",
			_("Nothing to record"),
			_("The collection has no line."),
			_("Add at least one waste type."),
		)
	prepared = [_prepare_line(row) for row in lines]
	if total_kg not in (None, ""):
		_allocate(prepared, total_kg)
	for line in prepared:
		if line["weight_kg"] is None:
			line["weight_kg"] = round(line["std_weight_kg"] * line["qty"], WEIGHT_DIGITS)
		line.pop("std_weight_kg")
	return prepared


# --- phiếu ------------------------------------------------------------------------------------------------------------


def record(station, employee, giver_card, lines, total_kg=None, note=None):
	"""Tạo và ghi sổ phiếu thu gom; `employee` là người thu gom (Employee của phiên thẻ)."""
	person = giver(giver_card)
	doc = frappe.get_doc(
		{
			"doctype": "Waste Collection",
			"delivered_by": person["employee"],
			"collected_by": employee,
			"station": station,
			"note": note,
			"lines": _prepare(lines, total_kg),
		}
	)
	doc.insert()
	doc.submit()
	return doc


def validate(doc):
	doc.department = frappe.db.get_value("Employee", doc.delivered_by, "department")
	doc.collected_at = doc.collected_at or now_datetime()
	doc.total_containers = sum(cint(row.qty) for row in doc.lines)
	doc.total_weight_kg = round(
		sum(flt(row.weight_kg) for row in doc.lines if not row.misclassified), WEIGHT_DIGITS
	)
	doc.held_kg = round(sum(flt(row.weight_kg) for row in doc.lines if row.misclassified), WEIGHT_DIGITS)


def _split(weight, qty):
	each = round(flt(weight) / qty, WEIGHT_DIGITS)
	weights = [each] * (qty - 1)
	weights.append(round(flt(weight) - sum(weights), WEIGHT_DIGITS))
	return weights


def on_submit(doc):
	"""Sinh mã `CT-` cho từng túi, tạo NC cho túi phân loại sai, xếp lệnh in nhãn (W1, W3, W11)."""
	jobs = []
	warning = None
	for line in doc.lines:
		hours = frappe.db.get_value("Waste Type", line.waste_type, "max_storage_hours")
		due = add_to_date(doc.collected_at, hours=cint(hours))
		for weight in _split(line.weight_kg, cint(line.qty)):
			container = _create_container(doc, line, weight, due)
			if line.misclassified:
				_report_misclassified(doc, line, container)
			job = _queue_label(doc, line, container)
			jobs.append(job)
			warning = warning or job.get("warning")
	doc.flags.tc_labels = {"jobs": jobs, "warning": warning}
	# FR-M10-08.1 (FEAT-050): import trong hàm vì analysis dùng storage, storage dùng hằng của file này
	from tracecore.waste import analysis

	analysis.check_anomaly(doc)


def _create_container(doc, line, weight, due):
	code = code_registry.next_container_code(doc.collected_at, doc.station)
	container = frappe.get_doc(
		{
			"doctype": "Waste Container",
			"waste_type": line.waste_type,
			"status": HELD if line.misclassified else COLLECTED,
			"weight_kg": weight,
			"collection": doc.name,
			"department": doc.department,
			"collected_at": doc.collected_at,
			"storage_due": due,
			"misclass_note": line.misclass_note,
		}
	)
	container.flags.tc_waste = True
	return container.insert(ignore_permissions=True, set_name=code)


def _report_misclassified(doc, line, container):
	extension.run(
		NC_HOOK,
		{
			"container": container.name,
			"waste_type": line.waste_type,
			"department": doc.department,
			"employee": doc.delivered_by,
			"station": doc.station,
			"note": line.misclass_note,
		},
	)


def on_cancel(doc):
	for name in frappe.get_all("Waste Container", filters={"collection": doc.name}, pluck="name"):
		frappe.db.set_value("Waste Container", name, "status", CANCELLED)


def release_held(container, note, user):
	"""R02 xác nhận túi đã phân loại lại: `Held` → `Collected`, kg cộng vào phiếu (FR-M10-02.4, W12)."""
	row = frappe.db.get_value(
		"Waste Container", container, ["status", "weight_kg", "collection"], as_dict=True, for_update=True
	)
	if not row or row.status != HELD:
		raise _blocked(
			"WASTE_NOT_HELD",
			_("Container is not on hold"),
			_("Waste container {0} is not waiting for confirmation.").format(container),
			_("Check the container code."),
		)
	if not cstr(note).strip():
		raise _blocked(
			"WASTE_NOTE_REQUIRED",
			_("Note required"),
			_("Releasing a held bag needs a note."),
			_("Enter how the bag was sorted again."),
		)
	frappe.db.set_value(
		"Waste Container",
		container,
		{"status": COLLECTED, "released_by": user, "release_note": cstr(note).strip()},
	)
	doc = frappe.get_doc("Waste Collection", row.collection)
	doc.db_set(
		{
			"total_weight_kg": round(flt(doc.total_weight_kg) + flt(row.weight_kg), WEIGHT_DIGITS),
			"held_kg": round(flt(doc.held_kg) - flt(row.weight_kg), WEIGHT_DIGITS),
		}
	)


def acknowledge(name, card):
	"""Biên nhận (W4): người giao hoặc đồng nghiệp cùng khoa quét lại thẻ."""
	person = giver(card)
	doc = frappe.get_doc("Waste Collection", name)
	if person["department"] != doc.department:
		raise _giver_rejected()
	doc.db_set({"acknowledged_by": person["employee"], "acknowledged_at": now_datetime()})
	return doc


# --- nhãn -------------------------------------------------------------------------------------------------------------


def _collected_text(doc):
	return f"{get_datetime(doc.collected_at):%d/%m/%Y %H:%M}" if doc.collected_at else ""


def _queue_label(doc, line, container):
	"""Print Job ``Queued`` nhãn QR của túi tại trạm thu gom (A-114: in PDF bằng máy in nhãn chung, không chờ máy in).

	Phiếu lập trên Desk không có trạm thì không tạo job (in lại từ Desk).
	"""
	if not doc.station:
		return {"print_job": None, "status": None, "warning": None}
	return core_print.queue_object_label(
		LABEL_OBJECT, container.name, line.waste_type, _collected_text(doc), doc.station
	)


def label_pdf(collection, station):
	"""PDF nhãn QR các túi/thùng của lượt thu gom cho hộp thoại In của trạm (FR-M10-01.5, A-114), mỗi túi một trang.

	Dùng Print Job của từng túi ở trạm này (``Queued``, hoặc đã in để in lại), xong ghi ``Printed``/``Browser``. Không có
	lượt thu gom → ``WASTE_COLLECTION_NOT_FOUND``; không còn nhãn nào in được ở trạm → ``LABEL_NOT_QUEUED``; lỗi sinh PDF →
	``LABEL_PDF_FAILED``, job giữ nguyên. Trả ``{"pdf_b64", "filename", "print_jobs"}``.
	"""
	doc = (
		frappe.db.get_value("Waste Collection", collection, ["name", "collected_at", "docstatus"], as_dict=True)
		if isinstance(collection, str) and collection
		else None
	)
	if not doc or doc.docstatus != 1:
		raise _blocked(
			"WASTE_COLLECTION_NOT_FOUND",
			_("Collection not found"),
			_("Waste collection {0} does not exist or is not submitted.").format(collection or "-"),
			_("Check the collection code."),
		)
	containers = frappe.get_all(
		"Waste Container",
		filters={"collection": doc.name, "status": ["!=", CANCELLED]},
		fields=["name", "waste_type"],
		order_by="name asc",
	)
	pages, jobs = [], []
	for container in containers:
		try:
			job = core_print.label_output_job(LABEL_OBJECT, container.name, station)
		except BlockedError:
			continue
		pages.append(core_label_pdf.object_pdf(container.name, container.waste_type, _collected_text(doc)))
		jobs.append(job)
	if not pages:
		raise _blocked(
			"LABEL_NOT_QUEUED",
			_("Label is not ready to print"),
			_("Collection {0} has no container label to print at this station.").format(doc.name),
			_("Print the labels from the station that recorded the collection, or call R02."),
		)
	filename = f"{doc.name}.pdf"
	pdf = core_label_pdf.merge(pages)
	for job in jobs:
		core_print.mark_browser_output(job.name, filename)
	return {**core_label_pdf.encode(pdf, filename), "print_jobs": [str(job.name) for job in jobs]}


def labels_of(doc):
	return doc.flags.tc_labels or {"jobs": [], "warning": None}


def view(doc):
	"""Dữ liệu màn trạm sau khi ghi sổ."""
	return {
		"name": doc.name,
		"department": doc.department,
		"delivered_by": doc.delivered_by,
		"total_containers": doc.total_containers,
		"total_weight_kg": doc.total_weight_kg,
		"held_kg": doc.held_kg,
		"containers": frappe.get_all(
			"Waste Container",
			filters={"collection": doc.name},
			fields=["name", "waste_type", "status", "weight_kg", "storage_due"],
			order_by="name asc",
		),
		"label_warning": labels_of(doc)["warning"],
		# A-114: số nhãn sẵn sàng in; màn trạm hiện nút In nhãn khi > 0
		"label_jobs": len([job for job in labels_of(doc)["jobs"] if job.get("print_job")]),
	}
