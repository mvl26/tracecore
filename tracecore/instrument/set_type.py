"""Phần đầu loại bộ dụng cụ (M1, FEAT-015; FR-M1-03, FR-M1-03.3, S5, S13; UC-02 bước 1, 4, 6).

- ``validate_header``: gọi trong ``InstrumentSetType.validate`` — thời gian lắp ráp chuẩn 0-600 phút, luật loại
  gói / hạn lưu (``shelf_life``), ``current_bom_version`` chỉ server ghi (cờ ``flags.tc_bom``), đổi phương pháp kiểm
  lại BOM.
- ``check_method_against_boms``: phiên bản BOM hiệu lực hôm nay + đã lên lịch phải tương thích họ phương pháp mới.
- ``derived_max_cycles``: cơ số bộ suy ra từ dụng cụ thấp nhất (chỉ hiển thị, không ghi; A-06 I4).

Phiên bản áp dụng / đã lên lịch theo ``bom_versions`` (S2): ngày theo múi giờ hệ thống, cùng ngày số lớn thắng.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, escape_html

from tracecore.core import ci_class
from tracecore.instrument import bom_versions, catalog, shelf_life

DOCTYPE = "Instrument Set Type"
ASSEMBLY_MINUTES_MAX = 600
CI_GROUP = "Chemical Indicator"
LINE_SEPARATOR = " \u2013 "  # gạch ngang (en dash) giữa các cột của dòng BOM trong thông báo


def usable_ci_items(method, setting=None) -> list[dict]:
	"""Mặt hàng chỉ thị chọn được làm mặc định cho loại bộ phương pháp `method`, loại chỉ thị `setting` (A-122, A-154).

	Item nhóm Chemical Indicator chưa tắt, đúng loại của `setting` (``ci_class.classes_for``: trống → 5/6, Không cần →
	không có mặt hàng nào), phương pháp đúng `method` (lô của chỉ thị trống phương pháp bị T4 từ chối, xem
	``reprocessing.packing.resolve_ci_batch``); theo tên. Trả ``[{"item", "item_name", "ci_class"}]``.
	Cùng tiêu chí với kiểm khi lưu để ô gợi ý không chép luật.
	"""
	classes = ci_class.classes_for(setting)
	if not method or not classes:
		return []
	rows = frappe.get_all(
		"Item",
		filters={
			"tc_item_group_cssd": CI_GROUP,
			"tc_compatible_method": method,
			"tc_ci_class": ["in", list(classes)],
			"disabled": 0,
		},
		fields=["name", "item_name", "tc_ci_class"],
		order_by="item_name asc, name asc",
	)
	return [{"item": row.name, "item_name": row.item_name, "ci_class": row.tc_ci_class} for row in rows]


def _validate_default_ci(doc) -> None:
	"""Chỉ thị mặc định (không bắt buộc) phải nằm trong ``usable_ci_items`` của phương pháp và loại chỉ thị của loại
	bộ (A-122, A-154); loại bộ khai Không cần thì không được có chỉ thị mặc định."""
	item = doc.get("default_ci_item")
	setting = doc.get("ci_class")
	if not item or item in {row["item"] for row in usable_ci_items(doc.get("method"), setting)}:
		return
	if not ci_class.is_required(setting):
		frappe.throw(
			_(
				"This set needs no chemical indicator, so it cannot have a default indicator. Clear Default Indicator Item or choose a class."
			),
			title=_("Default indicator"),
		)
	frappe.throw(
		_(
			"Default indicator {0} cannot be used for this set: choose a class {1} chemical indicator in use for {2}."
		).format(item, "/".join(ci_class.classes_for(setting)), _(doc.get("method") or "")),
		title=_("Default indicator"),
	)


def _validate_route_ci(doc) -> None:
	"""Loại bộ quy trình Khử khuẩn không tiệt khuẩn nên không có loại chỉ thị hóa học 4/5/6 (A-156; trống hoặc Không cần)."""
	if doc.get("method") == catalog.DISINFECTION and doc.get("ci_class") in ci_class.PACK_CLASSES:
		frappe.throw(
			_(
				"A disinfection set is not sterilized, so it takes no chemical indicator class. Choose Not Needed or leave it empty."
			),
			title=_("Chemical indicator class"),
		)


def validate_header(doc) -> None:
	"""Luật phần đầu loại bộ khi lưu (S13, FR-M1-03.3/.4/.5)."""
	minutes = cint(doc.get("assembly_minutes"))
	if not 0 <= minutes <= ASSEMBLY_MINUTES_MAX:
		frappe.throw(
			_("Standard assembly time must be between 0 and {0} minutes.").format(ASSEMBLY_MINUTES_MAX)
		)
	_guard_current_bom_version(doc)
	shelf_life.validate_set_type(doc)
	_validate_default_ci(doc)  # A-122
	_validate_route_ci(doc)  # A-156
	if not doc.is_new():
		before = doc.get_doc_before_save()
		if before is not None and before.get("method") != doc.get("method"):
			check_method_against_boms(doc)


def _guard_current_bom_version(doc) -> None:
	# Phiên bản hiện hành là giá trị suy ra từ các dòng BOM (S1): chỉ dịch vụ BOM (cờ flags.tc_bom) được ghi.
	current = cint(doc.get("current_bom_version"))
	if doc.is_new():
		expected = 1  # loại bộ mới luôn bắt đầu ở v1 (tạo cùng BOM v1 qua bom_versions)
	elif doc.flags.tc_bom:
		return
	else:
		before = doc.get_doc_before_save()
		expected = cint(before.get("current_bom_version")) if before is not None else current
	if current != expected:
		frappe.throw(
			_(
				"Current BOM Version is maintained by the system. Save a new BOM version to change the BOM of this set type."
			)
		)


def live_versions(set_type: str, on=None) -> list[int]:
	"""Phiên bản còn áp dụng từ ngày `on` (mặc định hôm nay): phiên bản hiệu lực + các phiên bản đã lên lịch.

	Theo ``bom_versions.live_map`` (S2): phiên bản đã thay thế và phiên bản bị thay trước hiệu lực (cùng ngày, hoặc số
	lớn hơn vượt lên ở ngày sớm hơn) không tính. Chưa có dòng BOM nào hiệu lực → dùng ``current_bom_version`` của loại bộ.
	"""
	live = bom_versions.live_map([set_type], on).get(set_type) or {"effective": None, "scheduled": []}
	effective = (
		live["effective"] or cint(frappe.db.get_value(DOCTYPE, set_type, "current_bom_version")) or None
	)
	scheduled = [version for version in live["scheduled"] if effective is None or version > effective]
	return ([effective] if effective is not None else []) + scheduled


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
	facts = {
		row.name: row
		for row in frappe.get_all(
			"Instrument",
			filters={"name": ["in", codes]},
			fields=["name", "instrument_name", "spaulding_class"],
		)
	}
	methods = defaultdict(set)
	for row in frappe.get_all(
		"Instrument Compatible Method",
		filters={"parent": ["in", codes], "parenttype": "Instrument", "parentfield": "compatible_methods"},
		fields=["parent", "method"],
	):
		methods[row.parent].add(row.method)

	def spaulding(code):
		return (facts.get(code) or {}).get("spaulding_class")

	bad = [
		line
		for line in lines
		if not catalog.fits_route(doc.method, methods[line.instrument], spaulding(line.instrument))
	]
	if not bad:
		return

	def fact(code):
		# A-156: quy trình Khử khuẩn chặn theo Spaulding, nên cột cuối ghi phân loại thay cho phương pháp
		if doc.method == catalog.DISINFECTION:
			return _(spaulding(code) or "—")
		return ", ".join(catalog.ordered_methods(methods[code])) or "—"

	rows = [
		_("BOM version {0}: {1}").format(
			line.bom_version,
			LINE_SEPARATOR.join(
				(
					str(cint(line.position)),
					line.instrument,
					escape_html((facts.get(line.instrument) or {}).get("instrument_name") or ""),
					fact(line.instrument),
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


# --- A-157 (FR-M1-06.6): sửa Quy trình xử lý / Loại chỉ thị hóa học từ form Set Unit ----------------------------


def choices(fieldname: str) -> list[str]:
	"""Lựa chọn của trường Select trên Loại bộ (``method`` / ``ci_class``) theo meta, không chép vào code/JS."""
	return (frappe.get_meta(DOCTYPE).get_field(fieldname).options or "").split("\n")


def route_ci_context(set_type: str) -> dict:
	"""Dữ liệu hộp thoại sửa trên form Set Unit: lựa chọn, giá trị hiện tại, số bộ cùng loại (chưa hủy) và số bộ đang
	có Cycle ID hiệu lực (gói đã đóng giữ giá trị cũ, giá trị mới áp từ lần đóng gói kế tiếp)."""
	method, setting = frappe.db.get_value(DOCTYPE, set_type, ["method", "ci_class"]) or (None, None)
	units = {"set_type": set_type, "status": ["!=", "Disposed"]}
	return {
		"set_type": set_type,
		"method": method or "",
		"ci_class": setting or "",
		"methods": choices("method"),
		"ci_classes": choices("ci_class"),
		"units": frappe.db.count("Set Unit", units),
		"units_in_cycle": frappe.db.count("Set Unit", {**units, "active_cycle_id": ["is", "set"]}),
	}


def set_route_ci(set_type: str, method: str, setting: str) -> dict:
	"""Đổi ``method`` và ``ci_class`` của loại bộ qua ``save()`` (đủ kiểm FR-M1-03.3/.9/.10, Audit Log qua hook).

	Chỉ thị mặc định không còn hợp với giá trị mới thì bỏ trống cùng lần lưu (``cleared_default_ci``). Không đổi gì →
	không lưu (``changed`` False). Trả ``{set_type, method, ci_class, changed, cleared_default_ci}``.
	"""
	doc = frappe.get_doc(DOCTYPE, set_type)
	result = {"set_type": doc.name, "method": method, "ci_class": setting, "cleared_default_ci": None}
	if (doc.method, doc.ci_class or "") == (method, setting):
		return {**result, "changed": False}
	doc.method, doc.ci_class = method, setting or None
	item = doc.get("default_ci_item")
	if item and item not in {row["item"] for row in usable_ci_items(method, setting)}:
		doc.default_ci_item, result["cleared_default_ci"] = None, item
	doc.save()
	return {**result, "changed": True}
