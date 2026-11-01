"""Khối Đồ vải của dashboard SCR-32 (ux-foundations DASH-02); số liệu lấy từ phiếu và lô đã có, không lưu thêm.

Kỳ là ``[start, end)``. Số liệu theo khoa chịu bộ lọc khoa; lô giặt không gắn với khoa nên chỉ chịu bộ lọc máy.
"""

from datetime import timedelta

import frappe
from frappe.utils import flt, getdate

from tracecore.linen import laundry, machine_usage, reconcile

KG_DIGITS = 3


def _flows_by_department(from_date, to_date, department):
	"""Kg thu, trả, chênh lệch theo khoa; cộng các loại đồ vải của từng khoa."""
	totals = {}
	for (ward, _type), entry in reconcile.flows(department, None, from_date, to_date).items():
		total = totals.setdefault(ward, {"collected_kg": 0, "returned_kg": 0, "disposed_kg": 0})
		for field in total:
			total[field] += flt(entry[field])
	names = dict(
		frappe.get_all(
			"Department",
			filters={"name": ["in", list(totals) or [""]]},
			fields=["name", "department_name"],
			as_list=True,
		)
	)
	return [
		{
			"department": ward,
			"department_name": names.get(ward) or ward,
			"collected_kg": flt(total["collected_kg"], KG_DIGITS),
			"returned_kg": flt(total["returned_kg"], KG_DIGITS),
			"variance_kg": flt(
				total["collected_kg"] - total["returned_kg"] - total["disposed_kg"], KG_DIGITS
			),
		}
		for ward, total in sorted(totals.items())
	]


def _uses_machine(row, equipment):
	return not equipment or equipment in (row.equipment, row.dryer)


def _batches(start, end, equipment):
	rows = frappe.get_all(
		laundry.DOCTYPE,
		filters=[["docstatus", "=", 1], ["ended_at", ">=", start], ["ended_at", "<", end]],
		fields=["name", "equipment", "dryer", "weight_kg", "cost_total", "norm_deviation_pct"],
		order_by="ended_at asc",
	)
	return [row for row in rows if _uses_machine(row, equipment)]


def _running(equipment):
	rows = frappe.get_all(
		laundry.DOCTYPE,
		filters={"status": laundry.RUNNING, "docstatus": 0},
		fields=["equipment", "dryer"],
	)
	return sum(1 for row in rows if _uses_machine(row, equipment))


def _failed_waiting(equipment):
	"""Lô Không đạt chưa có lô giặt lại còn hiệu lực; không theo kỳ: còn tồn thì còn phải xử lý."""
	redone = set(
		frappe.get_all(
			laundry.DOCTYPE, filters={"redo_of": ["is", "set"], "docstatus": ["<", 2]}, pluck="redo_of"
		)
	)
	rows = frappe.get_all(
		laundry.DOCTYPE,
		filters={"status": laundry.FAILED, "docstatus": 1},
		fields=["name", "equipment", "dryer"],
		order_by="name asc",
	)
	return [row.name for row in rows if row.name not in redone and _uses_machine(row, equipment)]


def _over_quota(start, end, department):
	filters = [
		["docstatus", "=", 1],
		["issued_at", ">=", start],
		["issued_at", "<", end],
		["quota_warning", "is", "set"],
	]
	if department:
		filters.append(["department", "=", department])
	return sorted(set(frappe.get_all("Linen Issue", filters=filters, pluck="department")))


def _machines(from_date, to_date, equipment):
	totals = {}
	for stage in machine_usage.stages(from_date, to_date, equipment=equipment):
		machine_usage.add(totals.setdefault(stage["machine"], machine_usage.empty_total()), stage)
	names = dict(
		frappe.get_all(
			"Equipment",
			filters={"name": ["in", list(totals) or [""]]},
			fields=["name", "equipment_name"],
			as_list=True,
		)
	)
	return [
		{
			"machine": machine,
			"machine_name": names.get(machine) or machine,
			"batches": total["batches"],
			"weight_kg": flt(total["weight_kg"], KG_DIGITS),
			"cost": round(total["cost_actual"]),
		}
		for machine, total in sorted(totals.items())
	]


def dashboard(start, end, department=None, equipment=None):
	from_date, to_date = getdate(start), getdate(end - timedelta(days=1))
	by_department = _flows_by_department(from_date, to_date, department)
	batches = _batches(start, end, equipment)
	weight = sum(flt(row.weight_kg) for row in batches)
	limit = laundry.deviation_threshold()
	return {
		"collected_kg": flt(sum(row["collected_kg"] for row in by_department), KG_DIGITS),
		"returned_kg": flt(sum(row["returned_kg"] for row in by_department), KG_DIGITS),
		"running": _running(equipment),
		"cost_per_kg": round(sum(flt(row.cost_total) for row in batches) / weight) if weight else 0,
		"failed_waiting": _failed_waiting(equipment),
		"over_deviation": [row.name for row in batches if flt(row.norm_deviation_pct) > limit],
		"over_quota_departments": _over_quota(start, end, department),
		"by_department": by_department,
		"machines": _machines(from_date, to_date, equipment),
	}
