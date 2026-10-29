"""Tồn khoa và đối chiếu thu - trả - hủy theo khoa/loại/kỳ (FEAT-035, UC-18, FR-M3-05.2, FR-M3-06, .1, .4; BRU-LIN-004;
architecture §5.3 DT-LINENISS, A-50 G3, G5, G6).

- Chênh lệch = thu gom - trả - hủy (chiếc và kg); cấp mới (`New`) không tính vào chênh lệch.
- Tồn khoa = Σ(trả + cấp mới) - Σ thu gom, cộng dồn đến hết kỳ (đồ sạch đang ở khoa).
- Chỉ phiếu đã ghi sổ (`docstatus = 1`) được tính; kỳ không có dữ liệu cho giá trị 0.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, today

from tracecore.core import notification

VARIANCE_LIMIT = 0.05  # FR-M3-06.1: lệch tháng lớn hơn 5 % số chiếc thì báo R02 (đúng 5 % chưa vượt)
EVENT = "LINEN_VARIANCE"
RETURN, NEW, DISPOSE = "Return", "New", "Dispose"
KINDS = (RETURN, NEW, DISPOSE)


def _conditions(alias, date_field, department, linen_type, from_date, to_date):
	conditions, values = [f"{alias}.docstatus = 1"], {}
	if department:
		conditions.append(f"{alias}.department = %(department)s")
		values["department"] = department
	if linen_type:
		conditions.append("l.linen_type = %(linen_type)s")
		values["linen_type"] = linen_type
	if from_date:
		conditions.append(f"DATE({alias}.{date_field}) >= %(from_date)s")
		values["from_date"] = getdate(from_date)
	if to_date:
		conditions.append(f"DATE({alias}.{date_field}) <= %(to_date)s")
		values["to_date"] = getdate(to_date)
	return " AND ".join(conditions), values


def _empty():
	return {
		"collected": 0,
		"collected_kg": 0.0,
		"returned": 0,
		"returned_kg": 0.0,
		"disposed": 0,
		"disposed_kg": 0.0,
		"new": 0,
		"new_kg": 0.0,
	}


def flows(department=None, linen_type=None, from_date=None, to_date=None):
	"""``{(khoa, loại): {collected, returned, disposed, new, *_kg}}`` của phiếu đã ghi sổ trong kỳ."""
	result = {}
	where, values = _conditions("c", "collected_at", department, linen_type, from_date, to_date)
	for row in frappe.db.sql(
		f"""SELECT c.department, l.linen_type, SUM(l.qty) AS qty, SUM(l.weight_kg) AS kg
		FROM `tabLinen Collection` c JOIN `tabLinen Collection Line` l ON l.parent = c.name
		WHERE {where} GROUP BY c.department, l.linen_type""",  # nosec B608 - chỉ ghép điều kiện cố định, giá trị qua tham số
		values,
		as_dict=True,
	):
		entry = result.setdefault((row.department, row.linen_type), _empty())
		entry["collected"] += cint(row.qty)
		entry["collected_kg"] += row.kg or 0
	where, values = _conditions("i", "issued_at", department, linen_type, from_date, to_date)
	for row in frappe.db.sql(
		f"""SELECT i.department, l.linen_type, i.kind, SUM(l.qty) AS qty, SUM(l.weight_kg) AS kg
		FROM `tabLinen Issue` i JOIN `tabLinen Issue Line` l ON l.parent = i.name
		WHERE {where} GROUP BY i.department, l.linen_type, i.kind""",  # nosec B608
		values,
		as_dict=True,
	):
		key = {RETURN: "returned", NEW: "new", DISPOSE: "disposed"}[row.kind]
		entry = result.setdefault((row.department, row.linen_type), _empty())
		entry[key] += cint(row.qty)
		entry[key + "_kg"] += row.kg or 0
	return result


def stock_of(entry):
	"""Tồn khoa (chiếc) của một dòng `flows`: trả + cấp mới - thu gom (G3)."""
	return entry["returned"] + entry["new"] - entry["collected"]


def quotas(department=None):
	"""``{(khoa, loại): (min_qty, max_qty)}`` từ `Linen Dept Quota` (cả khoa nếu `department` là None)."""
	filters = {"parenttype": "Linen Type"}
	if department:
		filters["department"] = department
	return {
		(row.department, row.parent): (row.min_qty, row.max_qty)
		for row in frappe.get_all(
			"Linen Dept Quota", filters=filters, fields=["parent", "department", "min_qty", "max_qty"]
		)
	}


def variance_ratio(entry):
	"""Tỷ lệ chênh lệch trên số chiếc thu gom; không thu gom thì 0 (không chia cho 0)."""
	if not entry["collected"]:
		return 0.0
	return (entry["collected"] - entry["returned"] - entry["disposed"]) / entry["collected"]


def over_variance(entry):
	"""Chênh lệch lớn hơn 5 %; đúng 5 % chưa vượt (làm tròn để tránh sai số số thực)."""
	return round(abs(variance_ratio(entry)), 9) > VARIANCE_LIMIT


# --- Bảng đối chiếu (Script Report) ---------------------------------------------------------------------------


def rows(department=None, linen_type=None, from_date=None, to_date=None):
	"""Dòng đối chiếu theo khoa/loại: thu, trả, hủy, cấp mới, chênh lệch, %, tồn khoa (đến hết `to_date`), định mức."""
	period = flows(department, linen_type, from_date, to_date)
	cumulative = flows(department, linen_type, None, to_date) if from_date else period
	limits = quotas(department)
	result = []
	for key in sorted(set(period) | set(cumulative)):
		entry = period.get(key) or _empty()
		minimum, maximum = limits.get(key, (None, None))
		result.append(
			{
				"department": key[0],
				"linen_type": key[1],
				**entry,
				"variance": entry["collected"] - entry["returned"] - entry["disposed"],
				"variance_kg": round(entry["collected_kg"] - entry["returned_kg"] - entry["disposed_kg"], 3),
				"variance_pct": round(variance_ratio(entry) * 100, 1),
				"stock": stock_of(cumulative.get(key) or _empty()),
				"min_qty": minimum,
				"max_qty": maximum,
			}
		)
	return result


# --- Màn trạm: chưa trả, tồn khoa, định mức ---------------------------------------------------------------------


def balance(department):
	"""Theo loại đang dùng: chưa trả (thu - trả - hủy, chiếc và kg), tồn khoa, định mức min/max của `department`."""
	cumulative = flows(department)
	limits = quotas(department)
	result = []
	for linen_type in frappe.get_all(
		"Linen Type", filters={"is_active": 1}, pluck="name", order_by="name asc"
	):
		entry = cumulative.get((department, linen_type)) or _empty()
		minimum, maximum = limits.get((department, linen_type), (None, None))
		result.append(
			{
				"linen_type": linen_type,
				"collected": entry["collected"],
				"unreturned": entry["collected"] - entry["returned"] - entry["disposed"],
				"unreturned_kg": round(
					entry["collected_kg"] - entry["returned_kg"] - entry["disposed_kg"], 3
				),
				"stock": stock_of(entry),
				"min_qty": minimum,
				"max_qty": maximum,
			}
		)
	return result


def quota_warnings(department, kind, lines):
	"""Cảnh báo vượt định mức tối đa khi cấp (FR-M3-05.2): tồn khoa hiện tại + số cấp > `max_qty`. Khoa chưa có định mức
	cho loại thì không cảnh báo (UC-18 E1). Hủy không cấp thêm nên không kiểm."""
	if kind == DISPOSE:
		return []
	issued = {}
	for row in lines:
		if row.linen_type:
			issued[row.linen_type] = issued.get(row.linen_type, 0) + (row.qty or 0)
	cumulative = flows(department)
	limits = quotas(department)
	warnings = []
	for linen_type, qty in issued.items():
		maximum = limits.get((department, linen_type), (None, None))[1]
		if not maximum:
			continue
		stock = stock_of(cumulative.get((department, linen_type)) or _empty())
		if stock + qty > maximum:
			warnings.append({"linen_type": linen_type, "stock": stock, "qty": qty, "max_qty": maximum})
	return warnings


def warning_text(warnings):
	return "\n".join(
		_("{0}: stock {1} + issued {2} exceeds the maximum {3}.").format(
			row["linen_type"], row["stock"], row["qty"], row["max_qty"]
		)
		for row in warnings
	)


# --- Cảnh báo cuối ngày (G6) ------------------------------------------------------------------------------------


def _already_sent(message):
	return frappe.db.exists(
		"Notification Delivery", {"event_code": EVENT, "message": message, "creation": [">=", today()]}
	)


def run_daily(on=None):
	"""Job 00:00: tính từ đầu tháng đến hôm qua. Khoa có chênh lệch tháng > 5 % số chiếc, hoặc tồn dưới `min_qty` của loại
	có định mức, thì báo R02 (một thông báo mỗi khoa mỗi ngày). Trả danh sách khoa đã báo."""
	end = add_days(getdate(on or today()), -1)
	start = end.replace(day=1)
	period = flows(None, None, start, end)
	cumulative = flows(None, None, None, end)
	limits = quotas()
	by_department = {}
	for (department, _type), entry in period.items():
		total = by_department.setdefault(department, _empty())
		for key, value in entry.items():
			total[key] += value
	alerted = []
	for department in sorted(set(by_department) | {key[0] for key in limits}):
		problems = []
		total = by_department.get(department)
		if total and over_variance(total):
			problems.append(
				_("Variance {0} % of {1} pieces collected.").format(
					round(variance_ratio(total) * 100, 1), total["collected"]
				)
			)
		for (dept, linen_type), (minimum, _max) in sorted(limits.items()):
			if dept != department or not minimum:
				continue
			stock = stock_of(cumulative.get((dept, linen_type)) or _empty())
			if stock < minimum:
				problems.append(
					_("{0}: stock {1} is below the minimum {2}.").format(linen_type, stock, minimum)
				)
		if not problems:
			continue
		message = (
			_("Linen reconciliation of {0} up to {1}:").format(department, end) + "\n" + "\n".join(problems)
		)
		if _already_sent(message):
			continue
		notification.emit(
			EVENT,
			subject=_("Linen reconciliation variance: {0}").format(department),
			message=message,
			link="/app/query-report/Linen Reconciliation-department=" + department,
		)
		alerted.append(department)
	return alerted
