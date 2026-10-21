"""Quy tắc khu - trạm: chức năng (bước T1-T8) theo loại khu và máy hai cửa (FEAT-002 E3, E5).

Nơi duy nhất giữ bảng "chức năng trạm theo loại khu"; Desk/JS lấy từ server, không chép lại.
Chỉ ``check_pass_through`` đọc DB (hai dòng Zone Station); phần còn lại thuần Python.
"""

import frappe
from frappe import _

STEPS_BY_ZONE_TYPE: dict[str, tuple[str, ...]] = {
	"Dirty": ("T1", "T2"),
	"Clean": ("T3", "T4", "T5"),
	"Sterile": ("T5b", "T6", "T7"),
	"Department": ("T8",),
	"Linen": (),
	"Waste": (),
}
# Chiều đi của dụng cụ qua máy hai cửa: Bẩn → Sạch → Vô khuẩn.
ZONE_FLOW: tuple[str, ...] = ("Dirty", "Clean", "Sterile")


def next_zone_type(zone_type: str | None) -> str | None:
	"""Loại khu kế tiếp theo ``ZONE_FLOW``; khu cuối hoặc loại ngoài luồng → ``None``."""
	if zone_type not in ZONE_FLOW:
		return None
	index = ZONE_FLOW.index(zone_type) + 1
	return ZONE_FLOW[index] if index < len(ZONE_FLOW) else None


def allowed_steps(zone_type: str) -> tuple[str, ...]:
	"""Các bước trạm được phép đặt trong khu loại ``zone_type``; loại lạ → ``()``."""
	return STEPS_BY_ZONE_TYPE.get(zone_type, ())


def _zone_type_label(zone_type: str | None) -> str:
	return _(zone_type, context="Zone Station") if zone_type else ""


def check_step(zone_type: str | None, step: str | None) -> None:
	"""Chặn bước nằm ngoài chức năng của khu; bước ``None``/rỗng luôn hợp lệ, khu chưa có loại không có chức năng."""
	if not step:
		return
	steps = allowed_steps(zone_type or "")
	if step in steps:
		return
	zone_label = _zone_type_label(zone_type)
	if not steps:
		frappe.throw(
			_("Zone {0} has no station functions yet, so step {1} cannot be set.").format(zone_label, step),
			frappe.ValidationError,
		)
	frappe.throw(
		_("Zone {0} only has these functions: {1}. Step {2} cannot be set.").format(
			zone_label, ", ".join(steps), step
		),
		frappe.ValidationError,
	)


def _zone_type_of(zone: str | None) -> str | None:
	"""Loại khu của ``zone`` nếu nó là một khu (``is_zone``); ngược lại ném ``ValidationError``."""
	row = frappe.db.get_value("Zone Station", zone, ["is_zone", "zone_type"], as_dict=True) if zone else None
	if not row or not row.is_zone:
		frappe.throw(_("{0} is not a zone.").format(zone or _("(empty)")), frappe.ValidationError)
	return row.zone_type


def check_pass_through(zone_in: str, zone_out: str | None) -> None:
	"""Máy hai cửa: cửa ra phải là khu kế tiếp của cửa vào theo chiều Bẩn → Sạch → Vô khuẩn.

	``zone_out`` rỗng = máy một cửa (luôn hợp lệ nếu ``zone_in`` là khu). Tham số là tên Zone Station
	loại khu; trạm hoặc tên không tồn tại bị từ chối.
	"""
	type_in = _zone_type_of(zone_in)
	if not zone_out:
		return
	type_out = _zone_type_of(zone_out)
	if type_in in ZONE_FLOW:
		index = ZONE_FLOW.index(type_in)
		if index + 1 < len(ZONE_FLOW) and ZONE_FLOW[index + 1] == type_out:
			return
	frappe.throw(
		_(
			"A two-door machine must go from zone {0} to the next zone in the order Dirty, Clean, Sterile, not to zone {1}."
		).format(_zone_type_label(type_in), _zone_type_label(type_out)),
		frappe.ValidationError,
	)
