"""Chỉ số NKVM và kháng sinh dự phòng theo kỳ (FEAT-064; FR-M13-09, FR-M13-12; QĐ 38; A-147 h).

Mỗi hàm nhận ``(period "YYYY-MM", department | None)`` và trả ``(tử số, mẫu số, cỡ mẫu)`` cho engine M9 (hook
``tracecore_ic_indicators``); kỳ = tháng của ngày phẫu thuật. Mẫu số 0 → "Không tính" (engine M9). Kết quả KSDP lấy từ
bản chụp trên từng ca (`prophylaxis_timing`) nên kỳ đã khóa không đổi khi ngưỡng đổi (FR-M13-09.2).
"""

import frappe

from tracecore.hai_surveillance import periods, ssi

KEYS = ("SSI_RATE", "SSI_PROPHYLAXIS_RATE", "SSI_PROPHYLAXIS_ON_TIME")
NNIS_BUCKETS = (0, 1, 2, 3)


def _filters(period, department=None, **extra):
	filters = {"reporting_period": periods.check_month(period), **extra}
	if department:
		filters["department"] = department
	return filters


def _count(period, department=None, **extra):
	return frappe.db.count(ssi.DOCTYPE, _filters(period, department, **extra))


def ssi_rate(period, department=None):
	"""% ca NKVM / ca phẫu thuật giám sát có ngày mổ trong tháng."""
	total = _count(period, department)
	return _count(period, department, outcome=ssi.SSI), total, total


def prophylaxis_rate(period, department=None):
	"""% ca có kháng sinh dự phòng."""
	total = _count(period, department)
	return _count(period, department, prophylaxis_given=1), total, total


def prophylaxis_on_time(period, department=None):
	"""% ca dùng KSDP đúng thời điểm / ca có KSDP đã đánh giá được (đủ phút và ngưỡng)."""
	assessed = _count(period, department, prophylaxis_timing=["in", [ssi.ON_TIME, ssi.LATE, ssi.TOO_EARLY]])
	return _count(period, department, prophylaxis_timing=ssi.ON_TIME), assessed, assessed


def register():
	"""Hook ``tracecore_ic_indicators``."""
	return dict(zip(KEYS, (ssi_rate, prophylaxis_rate, prophylaxis_on_time), strict=True))


def _pct(numerator, denominator):
	return round(numerator / denominator * 100, 2) if denominator else None


def months_between(period_from, period_to):
	start, end = periods.check_month(period_from), periods.check_month(period_to)
	if start > end:
		start, end = end, start
	months = [start]
	while months[-1] < end:
		year, month = map(int, months[-1].split("-"))
		months.append(f"{year + month // 12:04d}-{month % 12 + 1:02d}")
	return months


def summary(period_from, period_to=None):
	"""NKVM theo nhóm phẫu thuật và NNIS (SCR-58, Script Report, xuất `ssi_summary`): chỉ số liệu tổng hợp."""
	months = months_between(period_from, period_to or period_from)
	rows = frappe.get_all(
		ssi.DOCTYPE,
		filters={"reporting_period": ["in", months]},
		fields=[
			"procedure_group",
			"group_name",
			"nnis_index",
			"outcome",
			"prophylaxis_given",
			"prophylaxis_timing",
		],
		limit_page_length=0,
	)
	groups = {}
	for row in rows:
		key = row.procedure_group
		item = groups.setdefault(
			key,
			{
				"procedure_group": key,
				"group_name": row.group_name or key,
				"surgeries": 0,
				"ssi": 0,
				"prophylaxis": 0,
				"on_time": 0,
				"assessed": 0,
				**{f"nnis_{bucket}": 0 for bucket in NNIS_BUCKETS},
				**{f"ssi_nnis_{bucket}": 0 for bucket in NNIS_BUCKETS},
				"nnis_unknown": 0,
			},
		)
		item["surgeries"] += 1
		is_ssi = row.outcome == ssi.SSI
		item["ssi"] += int(is_ssi)
		if row.nnis_index is None or row.nnis_index == "":
			item["nnis_unknown"] += 1
		else:
			item[f"nnis_{int(row.nnis_index)}"] += 1
			item[f"ssi_nnis_{int(row.nnis_index)}"] += int(is_ssi)
		item["prophylaxis"] += int(bool(row.prophylaxis_given))
		item["on_time"] += int(row.prophylaxis_timing == ssi.ON_TIME)
		item["assessed"] += int(row.prophylaxis_timing in (ssi.ON_TIME, ssi.LATE, ssi.TOO_EARLY))
	out = []
	for item in sorted(groups.values(), key=lambda value: value["group_name"]):
		item["ssi_rate"] = _pct(item["ssi"], item["surgeries"])
		item["prophylaxis_rate"] = _pct(item["prophylaxis"], item["surgeries"])
		item["on_time_rate"] = _pct(item["on_time"], item["assessed"])
		for bucket in NNIS_BUCKETS:
			item[f"ssi_rate_nnis_{bucket}"] = _pct(item[f"ssi_nnis_{bucket}"], item[f"nnis_{bucket}"])
		out.append(item)
	return out


def totals(period_from, period_to=None):
	"""Toàn viện trong khoảng kỳ: số ca, ca NKVM, tỷ lệ, KSDP."""
	rows = summary(period_from, period_to)
	keys = ("surgeries", "ssi", "prophylaxis", "on_time", "assessed")
	total = {key: sum(row[key] for row in rows) for key in keys}
	total["ssi_rate"] = _pct(total["ssi"], total["surgeries"])
	total["prophylaxis_rate"] = _pct(total["prophylaxis"], total["surgeries"])
	total["on_time_rate"] = _pct(total["on_time"], total["assessed"])
	return total
