"""Lịch quan trắc nước thải theo kỳ lịch và nhắc đến hạn/quá hạn (FEAT-095; FR-M15-09, .1; BRU-ENV-006; A-153 W3, W8).

Không có DocType lịch: kỳ tính từ tần suất của từng dòng GPMT (3 / 6 / 12 tháng, khối tính từ 01/01). Kỳ của điểm = tần
suất nhỏ nhất trong các dòng không tự động. Trong kỳ P của điểm, thông số "phải có" là thông số có kỳ riêng kết thúc cùng
P; thông số đạt khi có đợt ghi sổ trong kỳ riêng của nó có giá trị hoặc KPH (BRU-ENV-006). Trạng thái ô:
``na`` mọi dòng tự động (W8) · ``none`` chưa có GPMT · ``future`` · ``fail`` có đợt Không đạt trong P · ``done`` · ``over``
hết kỳ không có đợt · ``miss`` có đợt nhưng thiếu thông số · ``due`` đang kỳ chưa có đợt.

``run_daily``: còn ``IC Program Settings.wastewater_due_days`` (trống = 15) ngày đến cuối kỳ mà chưa đủ → nhắc R01, R11
và người phụ trách một lần mỗi kỳ (``due_notified_period``); kỳ vừa hết chưa đủ → nhắc R01 một lần
(``overdue_notified_period``).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, today

from tracecore.core import notification
from tracecore.environmental_hygiene import wastewater

DUE_EVENT = "WW_MONITORING_DUE"
OVERDUE_EVENT = "WW_MONITORING_OVERDUE"
DEFAULT_DUE_DAYS = 15
DONE, FAIL, MISS, OVER, DUE, FUTURE, NA, NONE = "done", "fail", "miss", "over", "due", "future", "na", "none"
MONITORED = frozenset({DONE, FAIL})

periods = wastewater.periods
period_of = wastewater.period_of


def due_days():
	return cint(frappe.db.get_single_value("IC Program Settings", "wastewater_due_days")) or DEFAULT_DUE_DAYS


def _points(names=None):
	filters = {"disabled": 0}
	if names:
		filters["name"] = ["in", list(names)]
	return frappe.get_all(
		wastewater.POINT_DOCTYPE,
		filters=filters,
		fields=[
			"name",
			"point_name",
			"point_type",
			"responsible_user",
			"responsible_name",
			"awaiting_remonitor",
			"flag_monitoring",
			"due_notified_period",
			"overdue_notified_period",
		],
		order_by="name asc",
	)


def _rounds(point, start, end):
	rounds = frappe.get_all(
		wastewater.DOCTYPE,
		filters={"wastewater_point": point, "docstatus": 1, "sampled_on": ["between", [start, end]]},
		fields=["name", "sampled_on", "overall_result"],
		order_by="sampled_on asc, creation asc",
	)
	if rounds:
		results = frappe.get_all(
			wastewater.RESULT_DOCTYPE,
			filters={"parenttype": wastewater.DOCTYPE, "parent": ["in", [r.name for r in rounds]]},
			fields=["parent", "parameter", "value", "below_detection"],
		)
		by_round = {}
		for row in results:
			if wastewater.measured(row):
				by_round.setdefault(row.parent, set()).add((row.parameter or "").strip().lower())
		for item in rounds:
			item.sampled_on = getdate(item.sampled_on)
			item.measured = by_round.get(item.name, set())
	return rounds


def _cell(period, rows, rounds, on):
	cell = {
		"index": period["index"],
		"label": period["label"],
		"start": period["start"],
		"end": period["end"],
		"missing": [],
		"date": None,
		"days_left": None,
	}
	start, end = period["start"], period["end"]
	if start > on:
		return {**cell, "status": FUTURE}
	inside = [r for r in rounds if start <= r.sampled_on <= end]
	missing = []
	for row in rows:
		own = period_of(end, cint(row.frequency_months))
		if own["end"] != end:
			continue  # thông số kỳ dài hơn: chỉ bắt buộc ở kỳ kết thúc cùng kỳ riêng của nó
		key = (row.parameter or "").strip().lower()
		if not any(own["start"] <= r.sampled_on <= own["end"] and key in r.measured for r in rounds):
			missing.append(row.parameter)
	cell["missing"] = missing
	cell["date"] = inside[-1].sampled_on if inside else None
	if any(r.overall_result == wastewater.FAIL for r in inside):
		status = FAIL
	elif not missing:
		status = DONE
	elif end < on:
		status = MISS if inside else OVER
	else:
		status = MISS if inside else DUE
	if end >= on:
		cell["days_left"] = date_diff(end, on)
	return {**cell, "status": status}


def point_row(point, year, on):
	"""Một hàng lịch: điểm x kỳ của năm ``year`` nhìn từ ngày ``on``."""
	year_start, year_end = getdate(f"{year}-01-01"), getdate(f"{year}-12-31")
	reference = min(on, year_end) if on >= year_start else on
	permit = wastewater.active_permit(point.name, reference)
	row = {
		"point": point.name,
		"point_name": point.point_name,
		"point_type": point.point_type,
		"responsible_user": point.responsible_user,
		"responsible_name": point.responsible_name,
		"awaiting_remonitor": cint(point.awaiting_remonitor),
		"flag_monitoring": point.flag_monitoring,
		"permit": permit,
		"frequency": None,
		"auto_only": False,
	}
	whole_year = {"index": 0, "label": str(year), "start": year_start, "end": year_end, "missing": []}
	if not permit:
		return {**row, "periods": [{**whole_year, "status": NONE}]}
	rows = wastewater.permit_rows(permit, point.name, include_auto=False)
	rows = [r for r in rows if cint(r.frequency_months) in wastewater.FREQUENCIES]
	if not rows:
		return {**row, "auto_only": True, "periods": [{**whole_year, "status": NA}]}
	frequency = wastewater.point_frequency(rows)
	rounds = _rounds(point.name, year_start, year_end)
	return {
		**row,
		"frequency": frequency,
		"periods": [_cell(period, rows, rounds, on) for period in periods(frequency, year)],
	}


def grid(year=None, on=None, points=None):
	on = getdate(on or today())
	year = cint(year) or on.year
	return [point_row(point, year, on) for point in _points(points)]


def on_time_rate(year=None, on=None):
	"""(kỳ đã quan trắc, kỳ đã kết thúc) của các điểm định kỳ — chỉ số SCR-66 (FR-M15-12.1)."""
	on = getdate(on or today())
	done = total = 0
	for row in grid(year, on):
		for cell in row["periods"]:
			if cell["status"] in (NA, NONE, FUTURE) or cell["end"] >= on:
				continue
			total += 1
			done += 1 if cell["status"] in MONITORED else 0
	return done, total


def overdue_count(on=None):
	return sum(
		1
		for row in grid(None, on)
		for cell in row["periods"]
		if cell["status"] in (OVER, MISS) and cell["end"] < getdate(on or today())
	)


def _key(cell):
	return str(cell["start"])


def _users(point):
	return [point.responsible_user] if point.responsible_user else []


def run_daily(on=None):
	"""Scheduler hằng ngày: nhắc đến hạn (R01, R11, người phụ trách) và quá hạn (R01), mỗi điểm mỗi kỳ một lần."""
	on = getdate(on or today())
	lead = due_days()
	for point in _points():
		row = point_row(point, on.year, on)
		current = next((c for c in row["periods"] if c["start"] <= on <= c["end"]), None)
		if (
			current
			and current["status"] in (DUE, MISS)
			and flt(current["days_left"]) <= lead
			and point.due_notified_period != _key(current)
		):
			notification.emit(
				DUE_EVENT,
				frappe._dict(doctype=wastewater.POINT_DOCTYPE, name=point.name),
				subject=_("Wastewater monitoring due — {0}, {1}").format(point.point_name, current["label"]),
				message=_("{0} days left in {1}. Missing: {2}.").format(
					current["days_left"], current["label"], ", ".join(current["missing"]) or "—"
				),
				users=_users(point),
			)
			frappe.db.set_value(
				wastewater.POINT_DOCTYPE,
				point.name,
				"due_notified_period",
				_key(current),
				update_modified=False,
			)
		if not current:
			continue
		before = add_days(current["start"], -1)
		previous = point_row(point, before.year, on)
		ended = next((c for c in previous["periods"] if c["end"] == before), None)
		if ended and ended["status"] in (OVER, MISS) and point.overdue_notified_period != _key(ended):
			notification.emit(
				OVERDUE_EVENT,
				frappe._dict(doctype=wastewater.POINT_DOCTYPE, name=point.name),
				subject=_("Wastewater monitoring overdue — {0}, {1}").format(
					point.point_name, ended["label"]
				),
				message=_("{0} ended without a complete round. Missing: {1}.").format(
					ended["label"], ", ".join(ended["missing"]) or "—"
				),
			)
			frappe.db.set_value(
				wastewater.POINT_DOCTYPE,
				point.name,
				"overdue_notified_period",
				_key(ended),
				update_modified=False,
			)
