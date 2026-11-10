"""Dòng tự động của tự đánh giá QĐ 38 thuộc M12 (FEAT-065; FR-M9-29; hook ``tracecore_ic_self_checks``; A-145 D8).

``ic_chemical_quarterly``: mọi quý đã kết thúc của năm đều có `IC Chemical Consumption` đã ghi sổ (FR-M12-12) → Đạt;
thiếu quý nào → Chưa đạt (ghi quý thiếu); năm chưa hết quý đầu → Cần R01 xác nhận.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

DOCTYPE = "IC Chemical Consumption"


def chemical_quarterly(year, on=None):
	year = cint(year)
	on = getdate(on or today())
	ended = [q for q in range(1, 5) if year < on.year or (year == on.year and q * 3 < on.month)]
	if not ended:
		return {"status": "Needs confirmation", "source_ref": DOCTYPE}
	periods = set(
		frappe.get_all(DOCTYPE, filters={"docstatus": 1, "period": ("like", f"{year:04d}-%")}, pluck="period")
	)
	missing = [
		q
		for q in ended
		if not any(f"{year:04d}-{month:02d}" in periods for month in range(q * 3 - 2, q * 3 + 1))
	]
	if missing:
		return {
			"status": "Not met",
			"source_ref": _("{0} — missing quarter {1}").format(DOCTYPE, ", ".join(f"Q{q}" for q in missing)),
		}
	return {"status": "Met", "source_ref": DOCTYPE}


def register():
	return {"ic_chemical_quarterly": chemical_quarterly}
