"""Phần đầu loại bộ dụng cụ (M1, FEAT-015; FR-M1-03, FR-M1-03.3, S5, S13; UC-02 bước 1, 4, 6).

- ``validate_header``: gọi trong ``InstrumentSetType.validate`` — thời gian lắp ráp chuẩn 0-600 phút, luật loại
  gói / hạn lưu (``shelf_life``), ``current_bom_version`` chỉ server ghi (cờ ``flags.tc_bom``), đổi phương pháp kiểm
  lại BOM.
- ``check_method_against_boms``: phiên bản BOM hiệu lực hôm nay + đã lên lịch phải tương thích họ phương pháp mới.
- ``derived_max_cycles``: cơ số bộ suy ra từ dụng cụ thấp nhất (chỉ hiển thị, không ghi; A-06 I4).

Phiên bản áp dụng tại ngày D = phiên bản số lớn nhất có ``effective_from ≤ D`` (S2); dòng cũ chưa có ngày hiệu lực
coi như hiệu lực từ đầu. Ngày lấy theo múi giờ hệ thống (``nowdate``), không theo giờ tiến trình.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, escape_html, getdate, nowdate

from tracecore.instrument import catalog, shelf_life

DOCTYPE = "Instrument Set Type"
ASSEMBLY_MINUTES_MAX = 600
LINE_SEPARATOR = " \u2013 "  # gạch ngang (en dash) giữa các cột của dòng BOM trong thông báo


def validate_header(doc) -> None:
	"""Luật phần đầu loại bộ khi lưu (S13, FR-M1-03.3/.4/.5)."""
	minutes = cint(doc.get("assembly_minutes"))
	if not 0 <= minutes <= ASSEMBLY_MINUTES_MAX:
		frappe.throw(
			_("Standard assembly time must be between 0 and {0} minutes.").format(ASSEMBLY_MINUTES_MAX)
		)
	_guard_current_bom_version(doc)
	shelf_life.validate_set_type(doc)
	if not doc.is_new():
		before = doc.get_doc_before_save()
		if before is not None and before.get("method") != doc.get("method"):
			check_method_against_boms(doc)


def _guard_current_bom_version(doc) -> None:
	# Phiên bản hiện hành là giá trị suy ra từ các dòng BOM (S1): chỉ dịch vụ BOM (cờ flags.tc_bom) được ghi.
	if doc.flags.tc_bom:
		return
	current = cint(doc.get("current_bom_version"))
	if doc.is_new():
		expected = 1
	else:
		before = doc.get_doc_before_save()
		expected = cint(before.get("current_bom_version")) if before is not None else current
	if current != expected:
		frappe.throw(
			_(
				"Current BOM Version is maintained by the system. Save a new BOM version to change the BOM of this set type."
			)
		)


def _version_dates(set_type: str) -> dict[int, object]:
	"""``{phiên bản: ngày hiệu lực | None}`` của các phiên bản BOM đã có."""
	rows = frappe.db.sql(
		"""
		select bom_version, min(effective_from) as effective_from
		from `tabSet BOM Item`
		where set_type = %s
		group by bom_version
		""",
		(set_type,),
		as_dict=True,
	)
	return {cint(row.bom_version): row.effective_from for row in rows}


def _effective(dates: dict, on) -> int | None:
	started = [version for version, day in dates.items() if day is None or getdate(day) <= on]
	return max(started) if started else None


def live_versions(set_type: str, on=None) -> list[int]:
	"""Phiên bản còn áp dụng từ ngày `on` (mặc định hôm nay): phiên bản hiệu lực + các phiên bản đã lên lịch.

	Phiên bản đã thay thế không tính; cùng một ngày hiệu lực thì chỉ phiên bản số lớn nhất (S2: phiên bản thua
	không bao giờ áp dụng). Chưa có dòng BOM nào hiệu lực → dùng ``current_bom_version`` của loại bộ.
	"""
	on = getdate(on or nowdate())
	dates = _version_dates(set_type)
	effective = _effective(dates, on)
	if effective is None:
		effective = cint(frappe.db.get_value(DOCTYPE, set_type, "current_bom_version")) or None
	by_day: dict = {}
	for version, day in dates.items():
		if effective is not None and version <= effective:
			continue
		if day is not None and getdate(day) > on:
			by_day[getdate(day)] = max(version, by_day.get(getdate(day), 0))
	versions = sorted(by_day.values())
	return ([effective] if effective is not None else []) + versions


def _lines(set_type: str, versions: list[int]) -> list[dict]:
	if not versions:
		return []
	return frappe.get_all(
		"Set BOM Item",
		filters={"set_type": set_type, "bom_version": ["in", versions]},
		fields=["bom_version", "instrument", "position"],
		order_by="bom_version asc, position asc, name asc",
	)


def check_method_against_boms(doc) -> None:
	"""Đổi phương pháp loại bộ: mọi dòng của phiên bản hiệu lực + đã lên lịch phải tương thích (FR-M1-03.3).

	So ở mức họ phương pháp (``Steam``/``Plasma``, S5). Không tương thích → ``frappe.ValidationError`` liệt kê từng
	dòng ``vị trí - mã - tên - phương pháp của dụng cụ`` (theo phiên bản), không lưu gì.
	"""
	if doc.is_new() or not doc.get("method"):
		return
	lines = _lines(doc.name, live_versions(doc.name))
	if not lines:
		return
	codes = list({line.instrument for line in lines})
	names = dict(
		frappe.get_all(
			"Instrument", filters={"name": ["in", codes]}, fields=["name", "instrument_name"], as_list=True
		)
	)
	methods = defaultdict(set)
	for row in frappe.get_all(
		"Instrument Compatible Method",
		filters={"parent": ["in", codes], "parenttype": "Instrument", "parentfield": "compatible_methods"},
		fields=["parent", "method"],
	):
		methods[row.parent].add(row.method)
	bad = [line for line in lines if doc.method not in catalog.families(methods[line.instrument])]
	if not bad:
		return
	rows = [
		_("BOM version {0}: {1}").format(
			line.bom_version,
			LINE_SEPARATOR.join(
				(
					str(cint(line.position)),
					line.instrument,
					escape_html(names.get(line.instrument) or ""),
					", ".join(catalog.ordered_methods(methods[line.instrument])) or "—",
				)
			),
		)
		for line in bad
	]
	frappe.throw(
		_(
			"The sterilization method cannot be changed to {0}: these BOM lines are not compatible with it."
		).format(_(doc.method))
		+ "<br>"
		+ "<br>".join(rows),
		title=_("Incompatible BOM lines"),
	)


def derived_max_cycles(set_type: str, version: int | None = None) -> dict:
	"""Cơ số bộ suy ra (UC-02 bước 6) từ BOM phiên bản `version` (mặc định: phiên bản hiệu lực hôm nay).

	Trả ``{"value": min cơ số > 0 | None, "undefined": [mã có cơ số Chưa xác định], "limiting": [mã có cơ số = value]}``
	(mã sắp tăng dần). Chỉ đọc, không ghi; nguồn sự thật cơ số vẫn theo A-06 I4 / FEAT-031.
	"""
	if version is None:
		live = live_versions(set_type)
		version = live[0] if live else None
	result = {"value": None, "undefined": [], "limiting": []}
	if version is None:
		return result
	codes = set(
		frappe.get_all(
			"Set BOM Item", filters={"set_type": set_type, "bom_version": cint(version)}, pluck="instrument"
		)
	)
	if not codes:
		return result
	cycles = {
		row.name: cint(row.max_cycles)
		for row in frappe.get_all(
			"Instrument", filters={"name": ["in", list(codes)]}, fields=["name", "max_cycles"]
		)
	}
	defined = {code: value for code, value in cycles.items() if value > 0}
	result["undefined"] = sorted(code for code in codes if cycles.get(code, 0) <= 0)
	if defined:
		result["value"] = min(defined.values())
		result["limiting"] = sorted(code for code, value in defined.items() if value == result["value"])
	return result
