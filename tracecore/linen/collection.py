"""Thu gom đồ vải theo khoa: quy đổi số chiếc ↔ kg, lệch 15 %, kiểm phiếu (FEAT-033, UC-16, FR-M3-01, .1, .3, .4;
BRU-LIN-001, BRU-LIN-002; architecture §5.3 DT-LINENCOL, A-49 L2-L6).

Controller `Linen Collection` chỉ chuyển sang `validate`. Số chiếc và kg quy đổi qua khối lượng chuẩn của `Linen Type`;
không quản lý mã từng chiếc (FR-M3-01.1).
"""

import frappe
from frappe import _
from frappe.utils import now_datetime

from tracecore.core.errors import Block, BlockedError

TOLERANCE = 0.15  # FR-M3-01.4: lệch quá 15 % so với khối lượng quy đổi thì cần ghi chú
WEIGHT_DIGITS = 3
SOURCE_CONVERTED = "Converted"
SOURCE_MANUAL = "Manual"


def _given(value):
	return value not in (None, "")


def number_error(std_weight_kg, qty=None, weight_kg=None):
	"""Câu lỗi (đã dịch) nếu cặp số chiếc/kg không dùng được, ngược lại None (FR-M3-01.1, FR-M3-01.3)."""
	if not (_given(qty) or _given(weight_kg)):
		return _("Enter the number of pieces or the weight.")
	if _given(qty) and qty <= 0:
		return _("The number of pieces must be greater than 0.")
	if _given(weight_kg) and weight_kg <= 0:
		return _("The weight must be greater than 0.")
	if _given(weight_kg) and not _given(qty) and round(weight_kg / std_weight_kg) < 1:
		return _("The weight is less than one piece of this linen type.")
	return None


def convert(std_weight_kg, qty=None, weight_kg=None):
	"""Số chiếc và kg đủ cặp: ``(qty, weight_kg, source)``; chỉ nhập một giá trị thì tính giá trị còn lại theo khối lượng chuẩn
	(``source = "Converted"``), nhập đủ hai thì giữ nguyên (``source = None``). Cặp không dùng được (`number_error`) →
	`ValidationError`."""
	error = number_error(std_weight_kg, qty, weight_kg)
	if error:
		frappe.throw(error)
	if _given(qty) and _given(weight_kg):
		return qty, weight_kg, None
	if _given(qty):
		return qty, round(qty * std_weight_kg, WEIGHT_DIGITS), SOURCE_CONVERTED
	return round(weight_kg / std_weight_kg), weight_kg, SOURCE_CONVERTED


def variance(std_weight_kg, qty, weight_kg):
	"""Độ lệch tương đối của kg nhập so với kg quy đổi (``qty nhân khối lượng chuẩn``)."""
	expected = qty * std_weight_kg
	return abs(weight_kg - expected) / expected


def over_tolerance(std_weight_kg, qty, weight_kg):
	"""Lệch lớn hơn 15 %; đúng 15 % chưa vượt (so sau khi làm tròn để tránh sai số số thực)."""
	return round(variance(std_weight_kg, qty, weight_kg), 9) > TOLERANCE


def allocate_total(total_kg, rows):
	"""Chia kg tổng của xe cho các dòng ``(khối lượng chuẩn, số chiếc)`` theo ``chuẩn nhân số chiếc``; phần dư vào dòng cuối
	để tổng khớp (UC-16 A1)."""
	if not rows or not total_kg or total_kg <= 0:
		frappe.throw(_("Enter the total weight and at least one linen type."))
	shares = [std * qty for std, qty in rows]
	if any(share <= 0 for share in shares):
		frappe.throw(_("Every line needs a positive number of pieces."))
	whole = sum(shares)
	weights = [round(total_kg * share / whole, WEIGHT_DIGITS) for share in shares[:-1]]
	weights.append(round(total_kg - sum(weights), WEIGHT_DIGITS))
	return weights


def _linen_type(name):
	return frappe.db.get_value("Linen Type", name, ["std_weight_kg", "is_active"], as_dict=True)


def validate(doc):
	"""Kiểm phiếu thu gom và điền giá trị suy ra. Chạy trước kiểm bắt buộc/liên kết của Frappe nên bỏ qua dòng thiếu loại
	hoặc loại không tồn tại để Frappe báo đúng lỗi."""
	if not doc.lines:
		frappe.throw(_("Add at least one line."))
	if not doc.collected_at:
		doc.collected_at = now_datetime()
	for row in doc.lines:
		info = _linen_type(row.linen_type) if row.linen_type else None
		if not info:
			continue
		if not info.is_active:
			frappe.throw(_("Row {0}: linen type {1} is no longer in use.").format(row.idx, row.linen_type))
		row.qty, row.weight_kg, source = convert(info.std_weight_kg, row.qty, row.weight_kg)
		if source:
			row.weight_source = source
		elif not row.weight_source:
			row.weight_source = SOURCE_MANUAL
		if (
			source is None
			and over_tolerance(info.std_weight_kg, row.qty, row.weight_kg)
			and not (row.variance_note or "").strip()
		):
			frappe.throw(
				_(
					"Row {0}: the weight differs from the standard weight by more than 15 %. Enter a note to keep it."
				).format(row.idx)
			)
	doc.total_qty = sum(row.qty or 0 for row in doc.lines)
	doc.total_weight_kg = round(sum(row.weight_kg or 0 for row in doc.lines), WEIGHT_DIGITS)


# --- Màn trạm đồ vải (RPC tracecore.v1.linen.*, A-49 L8, L9, L12) ------------------------------------------


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def departments():
	"""Khoa chọn được ở màn thu gom: khoa lá, chưa tắt, đánh dấu `tc_is_ward` (A-22), theo tên."""
	return frappe.get_all(
		"Department",
		filters={"is_group": 0, "disabled": 0, "tc_is_ward": 1},
		fields=["name", "department_name"],
		order_by="department_name asc",
	)


def catalog(department=None):
	"""Loại đồ vải đang dùng kèm khối lượng chuẩn, giá trị/chiếc và định mức của `department` (nếu có)."""
	types = frappe.get_all(
		"Linen Type",
		filters={"is_active": 1},
		fields=["name", "std_weight_kg", "unit_value"],
		order_by="name asc",
	)
	quotas = {}
	if department:
		quotas = {
			row.parent: row
			for row in frappe.get_all(
				"Linen Dept Quota",
				filters={"parenttype": "Linen Type", "department": department},
				fields=["parent", "min_qty", "max_qty"],
			)
		}
	return [
		{
			**row,
			"min_qty": quotas[row.name].min_qty if row.name in quotas else None,
			"max_qty": quotas[row.name].max_qty if row.name in quotas else None,
		}
		for row in types
	]


def _number(value, row, field):
	"""Số hoặc None (để trống); chuỗi/bool/vô cực không phải số → LINEN_QTY_INVALID."""
	if value is None or value == "":
		return None
	try:
		if isinstance(value, bool):
			raise ValueError
		number = float(value)
		if number != number or number in (float("inf"), float("-inf")):
			raise ValueError
	except (TypeError, ValueError):
		raise _blocked(
			"LINEN_QTY_INVALID",
			_("Pieces or weight are not valid"),
			_("Row {0}: {1} is not a number.").format(row, field),
			_("Correct the pieces or weight and try again."),
		) from None
	return number


def _station_rows(lines, total_kg, note):
	if not isinstance(lines, list) or not lines:
		raise _blocked(
			"LINEN_EMPTY",
			_("Nothing to record"),
			_("The collection has no lines."),
			_("Add at least one linen type with pieces or weight."),
		)
	prepared = []
	for index, line in enumerate(lines, 1):
		line = line if isinstance(line, dict) else {}
		type_name = line.get("linen_type")
		info = _linen_type(type_name) if isinstance(type_name, str) and type_name else None
		if not info or not info.is_active:
			raise _blocked(
				"LINEN_TYPE_INVALID",
				_("Linen type is not valid"),
				_("Row {0}: linen type {1} does not exist or is no longer in use.").format(
					index, type_name or "-"
				),
				_("Choose a linen type from the list."),
			)
		prepared.append(
			(
				index,
				line,
				info,
				_number(line.get("qty"), index, _("pieces")),
				_number(line.get("weight_kg"), index, _("weight")),
			)
		)
	if total_kg is not None:
		return _allocated_rows(prepared, _number(total_kg, 0, _("total weight")), note)
	return [_station_row(index, line, info, qty, weight) for index, line, info, qty, weight in prepared]


def _qty_whole(index, qty):
	if qty is not None and qty != int(qty):
		raise _blocked(
			"LINEN_QTY_INVALID",
			_("Pieces or weight are not valid"),
			_("Row {0}: the number of pieces must be a whole number.").format(index),
			_("Correct the pieces or weight and try again."),
		)
	return None if qty is None else int(qty)


def _station_row(index, line, info, qty, weight, note=None):
	qty = _qty_whole(index, qty)
	error = number_error(info.std_weight_kg, qty, weight)
	if error:
		raise _blocked(
			"LINEN_QTY_INVALID",
			_("Pieces or weight are not valid"),
			_("Row {0}: {1}").format(index, error),
			_("Correct the pieces or weight and try again."),
		)
	qty, weight, source = convert(info.std_weight_kg, qty, weight)
	variance_note = (line.get("variance_note") or note or "").strip()
	if source is None and over_tolerance(info.std_weight_kg, qty, weight) and not variance_note:
		raise _blocked(
			"LINEN_VARIANCE_NOTE_REQUIRED",
			_("The weight differs from the standard"),
			_("Row {0}: the weight differs from the standard weight by more than 15 %.").format(index),
			_("Enter a note to keep the weight, or correct the pieces or weight."),
		)
	if source is None:
		source = (
			line.get("weight_source") if line.get("weight_source") in ("Scale", "Manual") else SOURCE_MANUAL
		)
	return {
		"linen_type": line["linen_type"],
		"qty": qty,
		"weight_kg": weight,
		"contaminated": 0 if str(line.get("contaminated", 1)).strip().lower() in ("0", "false", "") else 1,
		"weight_source": source,
		"variance_note": variance_note or None,
	}


def _allocated_rows(prepared, total_kg, note):
	"""Chỉ có cân tổng của xe (UC-16 A1): chia kg theo ``chuẩn nhân số chiếc`` của từng dòng."""
	if total_kg is None or total_kg <= 0 or any(qty is None or qty <= 0 for *_x, qty, _w in prepared):
		raise _blocked(
			"LINEN_TOTAL_INVALID",
			_("The total weight cannot be shared"),
			_("The total weight and the number of pieces of every line must be greater than 0."),
			_("Enter the total weight and the pieces of each linen type."),
		)
	weights = allocate_total(
		total_kg, [(info.std_weight_kg, _qty_whole(index, qty)) for index, _l, info, qty, _w in prepared]
	)
	rows = []
	for (index, line, info, qty, _weight), weight in zip(prepared, weights, strict=True):
		row = _station_row(index, line, info, qty, weight, note)
		row["weight_source"] = SOURCE_CONVERTED
		rows.append(row)
	return rows


def record(station, employee, department, delivered_by, lines, total_kg=None, note=None):
	"""Ghi sổ một lượt thu gom từ trạm đồ vải: kiểm đầu vào bằng `Block` (mã LINEN_*), rồi tạo và ghi sổ `Linen Collection`.

	`employee` là người nhận (Employee của phiên thẻ). `total_kg` có giá trị thì chia kg tổng cho các dòng (UC-16 A1).
	"""
	row = (
		frappe.db.get_value("Department", department, ["is_group", "disabled"], as_dict=True)
		if isinstance(department, str) and department
		else None
	)
	if not row or row.is_group or row.disabled:
		raise _blocked(
			"DEPARTMENT_INVALID",
			_("Department is not valid"),
			_("Department {0} does not exist, is disabled, or is a group.").format(department or "-"),
			_("Choose the department that hands the linen over."),
		)
	delivered_by = (delivered_by or "").strip() if isinstance(delivered_by, str) else ""
	if not delivered_by:
		raise _blocked(
			"DELIVERER_NAME_REQUIRED",
			_("Deliverer name is required"),
			_("The collection needs the name of the person who hands the linen over."),
			_("Type the name of the person who hands the linen over."),
		)
	rows = _station_rows(lines, total_kg, (note or "").strip())
	doc = frappe.get_doc(
		{
			"doctype": "Linen Collection",
			"department": department,
			"delivered_by": delivered_by,
			"received_by": employee,
			"station": station,
			"note": note,
			"lines": rows,
		}
	)
	doc.insert()
	doc.submit()
	return doc


def view(doc):
	"""Phiếu thu gom đã ghi sổ cho màn trạm."""
	return {
		"collection": doc.name,
		"department": doc.department,
		"collected_at": str(doc.collected_at),
		"delivered_by": doc.delivered_by,
		"total_qty": doc.total_qty,
		"total_weight_kg": doc.total_weight_kg,
		"lines": [
			{
				"linen_type": row.linen_type,
				"qty": row.qty,
				"weight_kg": row.weight_kg,
				"contaminated": row.contaminated,
				"weight_source": row.weight_source,
				"variance_note": row.variance_note,
			}
			for row in doc.lines
		],
	}
