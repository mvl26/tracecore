"""Tỷ lệ kháng thuốc theo quý (FEAT-067; FR-M14-08, FR-M14-08.1; BRU-MDR-002; A-136 Q8).

Chỉ tính chủng đầu tiên (``is_first_isolate``) của quý; mỗi cặp vi khuẩn-kháng sinh (tùy chọn theo khoa) có số chủng
được thử và tỷ lệ S/I/R. Cặp có ít chủng hơn ngưỡng ``IC Program Settings.ast_min_isolates`` (mặc định 30) bị đánh dấu
cỡ mẫu nhỏ. Chỉ số liệu tổng hợp: không có mã người bệnh (BRU-RPT-002, NFR-PRIV-01).
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from tracecore.microbiology import isolates

SETTINGS = "IC Program Settings"
DEFAULT_MIN_ISOLATES = 30


def min_isolates() -> int:
	value = None
	if frappe.db.exists("DocType", SETTINGS):
		value = frappe.db.get_single_value(SETTINGS, "ast_min_isolates")
	return cint(value) or DEFAULT_MIN_ISOLATES


def period(year, quarter) -> str:
	quarter = cint(quarter)
	if not 1 <= quarter <= 4 or cint(year) < 2000:
		frappe.throw(_("Choose a year and a quarter from 1 to 4."))
	return f"{cint(year)}-Q{quarter}"


def _pct(count, total):
	return flt(100.0 * count / total, 1) if total else 0.0


def compute(year, quarter, department=None, organism=None, by_department=False):
	"""Dòng ``{organism, organism_name, antibiotic, antibiotic_name, [department, department_name], tested, s, i, r,
	s_pct, i_pct, r_pct, small_sample}`` sắp theo tên vi khuẩn, mã kháng sinh."""
	filters = {"period_key": period(year, quarter), "is_first_isolate": 1}
	if department:
		filters["department"] = department
	if organism:
		filters["organism"] = organism
	heads = {
		row.name: row
		for row in frappe.get_all(
			isolates.DOCTYPE,
			filters=filters,
			fields=["name", "organism", "organism_name", "department", "department_name"],
		)
	}
	if not heads:
		return []
	groups: dict = {}
	seen = set()
	for row in frappe.get_all(
		"Isolate Susceptibility",
		filters={"parenttype": isolates.DOCTYPE, "parent": ["in", list(heads)]},
		fields=["parent", "antibiotic", "antibiotic_name", "result"],
		order_by="idx asc",
	):
		if (row.parent, row.antibiotic) in seen or row.result not in isolates.RESULTS:
			continue
		seen.add((row.parent, row.antibiotic))
		head = heads[row.parent]
		key = (head.organism, row.antibiotic, head.department if by_department else None)
		group = groups.setdefault(
			key,
			{
				"organism": head.organism,
				"organism_name": head.organism_name,
				"antibiotic": row.antibiotic,
				"antibiotic_name": row.antibiotic_name,
				"S": 0,
				"I": 0,
				"R": 0,
			},
		)
		if by_department:
			group.update(department=head.department, department_name=head.department_name)
		group["antibiotic_name"] = group["antibiotic_name"] or row.antibiotic_name
		group[row.result] += 1
	threshold = min_isolates()
	out = []
	for group in groups.values():
		tested = group["S"] + group["I"] + group["R"]
		out.append(
			{
				**{k: v for k, v in group.items() if k not in ("S", "I", "R")},
				"tested": tested,
				"s_pct": _pct(group["S"], tested),
				"i_pct": _pct(group["I"], tested),
				"r_pct": _pct(group["R"], tested),
				"small_sample": tested < threshold,
			}
		)
	out.sort(
		key=lambda r: (r["organism_name"] or r["organism"], r.get("department_name") or "", r["antibiotic"])
	)
	return out


def first_isolate_count(year, quarter, department=None, organism=None) -> int:
	filters = {"period_key": period(year, quarter), "is_first_isolate": 1}
	if department:
		filters["department"] = department
	if organism:
		filters["organism"] = organism
	return frappe.db.count(isolates.DOCTYPE, filters)


def hai_with_pathogen_rate(year, quarter):
	"""Tỷ lệ % ca NKBV xác định có tác nhân trong quý (FR-M14-08). DocType `HAI Case` làm ở FEAT-063 (A-136 Q8): đến
	lúc đó chưa có dữ liệu, trả None; FEAT-063 thay thân hàm này khi có trạng thái ca và tác nhân."""
	return None
