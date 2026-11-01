"""Quy tắc vùng - trạm - chức năng đọc từ cấu hình (FEAT-002 E3, E5; A-64, FEAT-051).

``Zone Type`` giữ chức năng được phép và chiều đi qua máy hai cửa; ``Station Function`` giữ màn và cổng của chức năng;
trạm giữ danh sách chức năng ở bảng con. Desk/JS lấy từ server, không chép lại. Mã cổng T1..T5 của ``core.step_gate`` là
mã nội bộ: màn hình dùng ``gate_label``.
"""

import frappe
from frappe import _
from frappe.utils import cint

DEFAULT_COLOR_CLASS = "web"
COLOR_CLASSES = {
	"Default color": DEFAULT_COLOR_CLASS,
	"Dirty zone": "dirty",
	"Clean zone": "clean",
	"Sterile zone": "sterile",
	"Department zone": "dept",
	"Waste zone": "waste",
}


def _zone_type_label(zone_type: str | None) -> str:
	return _(zone_type, context="Zone Station") if zone_type else ""


def _functions_in_order(names) -> list[str]:
	"""``names`` theo ``process_order``; tên không có trong danh mục bị bỏ."""
	if not names:
		return []
	return frappe.get_all(
		"Station Function",
		filters={"name": ["in", list(names)]},
		pluck="name",
		order_by="process_order asc, name asc",
	)


def _function_name(name: str) -> str:
	"""Tên chức năng trên màn trạm; context riêng để "Lắp bộ" không đụng từ "Assembly" của các app khác (#1834 T3-06)."""
	return _(name, context="Station Function")


def function_label(function: str) -> str:
	name = frappe.db.get_value("Station Function", function, "function_name")
	return _function_name(name) if name else function


def allowed_functions(zone_type: str | None) -> tuple[str, ...]:
	"""Chức năng được đặt trong loại vùng ``zone_type``, theo thứ tự quy trình; loại lạ → ``()``."""
	if not zone_type:
		return ()
	rows = frappe.get_all(
		"Zone Type Function",
		filters={"parent": zone_type, "parenttype": "Zone Type"},
		pluck="station_function",
	)
	return tuple(_functions_in_order(rows))


def check_functions(zone_type: str | None, functions) -> None:
	"""Chặn chức năng ngoài danh sách cho phép của loại vùng; danh sách rỗng luôn hợp lệ."""
	functions = [function for function in functions or () if function]
	if not functions:
		return
	allowed = allowed_functions(zone_type)
	wrong = [function for function in functions if function not in allowed]
	if not wrong:
		return
	zone_label = _zone_type_label(zone_type)
	wrong_labels = ", ".join(function_label(function) for function in wrong)
	if not allowed:
		frappe.throw(
			_("Zone {0} has no station functions yet, so {1} cannot be set.").format(
				zone_label, wrong_labels
			),
			frappe.ValidationError,
		)
	frappe.throw(
		_("Zone {0} only allows these functions: {1}. {2} cannot be set.").format(
			zone_label, ", ".join(function_label(function) for function in allowed), wrong_labels
		),
		frappe.ValidationError,
	)


def station_functions(station: str | None) -> list[str]:
	"""Chức năng của trạm theo thứ tự quy trình; khu hoặc tên lạ → ``[]``."""
	if not station or not isinstance(station, str):
		return []
	rows = frappe.get_all(
		"Zone Station Function",
		filters={"parent": station, "parenttype": "Zone Station"},
		pluck="station_function",
	)
	return _functions_in_order(rows)


def station_has_function(station: str | None, *functions: str) -> bool:
	"""Trạm có ít nhất một trong ``functions``. Chỉ kiểm chức năng; ``is_active`` do nơi gọi kiểm."""
	if not station or not isinstance(station, str):
		return False
	return bool(
		frappe.db.exists(
			"Zone Station Function",
			{"parent": station, "parenttype": "Zone Station", "station_function": ["in", list(functions)]},
		)
	)


def stations_with_function(function: str, zone: str | None = None) -> list[str]:
	"""Trạm đang hoạt động có ``function``, theo số trạm (trạm chưa đánh số xếp sau) rồi theo tên."""
	parents = frappe.get_all(
		"Zone Station Function",
		filters={"station_function": function, "parenttype": "Zone Station"},
		pluck="parent",
	)
	if not parents:
		return []
	filters = {"name": ["in", parents], "is_zone": 0, "is_active": 1}
	if zone:
		filters["parent_zone"] = zone
	rows = frappe.get_all("Zone Station", filters=filters, fields=["name", "station_no"])
	rows.sort(key=lambda row: (not cint(row.station_no), cint(row.station_no), row.name))
	return [row.name for row in rows]


def missing_functions() -> list[str]:
	"""Chức năng bắt buộc của chuỗi quy trình chưa có trạm hoạt động: bộ sẽ kẹt nếu đi tới đó."""
	required = frappe.get_all(
		"Station Function",
		filters={"is_required": 1},
		pluck="name",
		order_by="process_order asc, name asc",
	)
	return [function for function in required if not stations_with_function(function)]


def station_screen_tabs(functions) -> list[dict]:
	"""Màn nghiệp vụ của các chức năng: ``[{"key", "label"}]`` theo thứ tự quy trình; chức năng chung màn gộp một tab."""
	if not functions:
		return []
	rows = frappe.get_all(
		"Station Function",
		filters={"name": ["in", list(functions)], "screen_key": ["is", "set"]},
		fields=["screen_key", "function_name"],
		order_by="process_order asc, name asc",
	)
	tabs: dict[str, list[str]] = {}
	for row in rows:
		tabs.setdefault(row.screen_key, []).append(_function_name(row.function_name))
	return [{"key": key, "label": " / ".join(labels)} for key, labels in tabs.items()]


def gate_labels() -> dict[str, str]:
	"""Tên hiển thị của các cổng: ``{"T1": "Tiếp nhận", ...}``."""
	rows = frappe.get_all(
		"Station Function", filters={"gate_step": ["is", "set"]}, fields=["gate_step", "function_name"]
	)
	return {row.gate_step: _function_name(row.function_name) for row in rows}


def gate_label(step: str) -> str:
	"""Tên hiển thị của một cổng; cổng lạ giữ nguyên mã."""
	name = frappe.db.get_value("Station Function", {"gate_step": step}, "function_name")
	return _function_name(name) if name else step


def next_zone_type(zone_type: str | None) -> str | None:
	"""Loại vùng kế tiếp qua máy hai cửa theo cấu hình; vùng cuối hoặc ngoài luồng → ``None``."""
	return frappe.db.get_value("Zone Type", zone_type, "next_zone_type") or None if zone_type else None


def zone_color_class(zone_type: str | None) -> str:
	"""Hậu tố class ``tc-zone-*`` của thanh tiêu đề màn trạm."""
	color = frappe.db.get_value("Zone Type", zone_type, "zone_color") if zone_type else None
	return COLOR_CLASSES.get(color, DEFAULT_COLOR_CLASS)


def _zone_type_of(zone: str | None) -> str | None:
	"""Loại vùng của ``zone`` nếu nó là một vùng (``is_zone``); ngược lại ném ``ValidationError``."""
	row = frappe.db.get_value("Zone Station", zone, ["is_zone", "zone_type"], as_dict=True) if zone else None
	if not row or not row.is_zone:
		frappe.throw(_("{0} is not a zone.").format(zone or _("(empty)")), frappe.ValidationError)
	return row.zone_type


def check_pass_through(zone_in: str, zone_out: str | None) -> None:
	"""Máy hai cửa: cửa ra phải là vùng kế tiếp của cửa vào theo cấu hình ``Zone Type``.

	``zone_out`` rỗng = máy một cửa (luôn hợp lệ nếu ``zone_in`` là vùng). Tham số là tên Zone Station
	loại vùng; trạm hoặc tên không tồn tại bị từ chối.
	"""
	type_in = _zone_type_of(zone_in)
	if not zone_out:
		return
	type_out = _zone_type_of(zone_out)
	if type_out and next_zone_type(type_in) == type_out:
		return
	frappe.throw(
		_(
			"A two-door machine must go from zone {0} to the next zone in the configured flow, not to zone {1}."
		).format(_zone_type_label(type_in), _zone_type_label(type_out)),
		frappe.ValidationError,
	)
