"""Đồ vải đã nhận nhìn từ khoa (FEAT-101, A-161, FR-M9-32; cổng khoa của Page tc-flow, UC-18 phía khoa).

Chỉ đọc, chỉ phiếu đã ghi sổ. Theo ngày và loại: thu gom, trả về (phiếu `Return`), hủy (phiếu `Dispose`); chênh lệch =
trả về - thu gom (âm là khoa nhận lại ít hơn số đã giao đi). Định mức, tồn khoa và tỷ lệ chênh lệch tháng dùng lại
`linen.reconcile` (cùng công thức bảng đối chiếu, ngưỡng cảnh báo 5 %).
"""

import frappe
from frappe.utils import cint, flt, get_first_day, get_last_day, getdate, today

from tracecore.linen import reconcile


def _month(month):
	"""``YYYY-MM`` → (ngày đầu, ngày cuối); sai định dạng hoặc trống → tháng hiện tại."""
	try:
		first = get_first_day(getdate(f"{month}-01")) if month else get_first_day(today())
	except Exception:
		first = get_first_day(today())
	return first, get_last_day(first)


def daily(department, from_date, to_date):
	"""Dòng theo ngày + loại, ngày mới trước: thu gom, trả về (chiếc, kg), hủy và chênh lệch (trả - thu)."""
	values = {"department": department, "from_date": from_date, "to_date": to_date}
	rows = {}

	def entry(day, linen_type):
		return rows.setdefault(
			(day, linen_type),
			{
				"date": day,
				"linen_type": linen_type,
				"collected": 0,
				"collected_kg": 0.0,
				"returned": 0,
				"returned_kg": 0.0,
				"disposed": 0,
			},
		)

	for row in frappe.db.sql(
		"""select date(c.collected_at) as day, l.linen_type, sum(l.qty) as qty, sum(l.weight_kg) as kg
		from `tabLinen Collection` c join `tabLinen Collection Line` l on l.parent = c.name
		where c.docstatus = 1 and c.department = %(department)s
			and date(c.collected_at) between %(from_date)s and %(to_date)s
		group by date(c.collected_at), l.linen_type""",
		values,
		as_dict=True,
	):
		line = entry(row.day, row.linen_type)
		line["collected"] += cint(row.qty)
		line["collected_kg"] += flt(row.kg)
	for row in frappe.db.sql(
		"""select date(i.issued_at) as day, l.linen_type, i.kind, sum(l.qty) as qty, sum(l.weight_kg) as kg
		from `tabLinen Issue` i join `tabLinen Issue Line` l on l.parent = i.name
		where i.docstatus = 1 and i.department = %(department)s and i.kind in ('Return', 'Dispose')
			and date(i.issued_at) between %(from_date)s and %(to_date)s
		group by date(i.issued_at), l.linen_type, i.kind""",
		values,
		as_dict=True,
	):
		line = entry(row.day, row.linen_type)
		if row.kind == reconcile.RETURN:
			line["returned"] += cint(row.qty)
			line["returned_kg"] += flt(row.kg)
		else:
			line["disposed"] += cint(row.qty)
	names = dict(frappe.get_all("Linen Type", fields=["name", "type_name"], as_list=True))
	result = []
	for key in sorted(rows, key=lambda key: (key[0], key[1]), reverse=True):
		line = rows[key]
		line["type_name"] = names.get(line["linen_type"]) or line["linen_type"]
		line["collected_kg"] = round(line["collected_kg"], 1)
		line["returned_kg"] = round(line["returned_kg"], 1)
		line["difference"] = line["returned"] - line["collected"]
		result.append(line)
	return result


def overview(department, month=None):
	"""Màn Đồ vải đã nhận: dòng theo ngày của tháng, định mức + tồn khoa theo loại, tỷ lệ chênh lệch tháng."""
	first, last = _month(month)
	total = reconcile._empty()
	for entry in reconcile.flows(department, None, first, last).values():
		for key in ("collected", "returned", "disposed"):
			total[key] += entry[key]
	names = dict(frappe.get_all("Linen Type", fields=["name", "type_name"], as_list=True))
	quotas = []
	for row in reconcile.balance(department):
		if row["min_qty"] is None and row["max_qty"] is None:
			continue
		low = row["min_qty"] is not None and row["stock"] < row["min_qty"]
		high = row["max_qty"] is not None and row["stock"] > row["max_qty"]
		quotas.append(
			{
				"linen_type": row["linen_type"],
				"type_name": names.get(row["linen_type"]) or row["linen_type"],
				"stock": row["stock"],
				"min": row["min_qty"],
				"max": row["max_qty"],
				"state": "below" if low else "over" if high else "within",
			}
		)
	return {
		"month": first.strftime("%Y-%m"),
		"rows": daily(department, first, last),
		"quotas": quotas,
		"variance_pct": round(abs(reconcile.variance_ratio(total)) * 100, 1),
		"variance_limit_pct": round(reconcile.VARIANCE_LIMIT * 100, 1),
		"over_variance": reconcile.over_variance(total),
	}
