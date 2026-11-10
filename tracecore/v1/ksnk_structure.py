"""RPC tracecore.v1.ksnk_structure.* — màn SCR-47 Cơ cấu KSNK (FEAT-057; FR-M11-01..03; UC-40; plan D6).

- ``status`` (GET, chỉ đọc): bảng cơ cấu của ``infection_program.structure.compute`` + cài đặt + quyền của người gọi.
- ``save_settings`` (POST): R10/R01 lưu số giường, tuyến, nội trú, tỷ lệ giám sát viên; đi qua ``doc.save()`` nên DocPerm
  quyết định ai được ghi.
- ``submit_committee`` (POST): R01 ghi sổ Hội đồng Nháp; cảnh báo thiếu khối đại diện trả về ``warnings``.

FEAT-094 (A-138 h): ``status`` thêm ``profile``, ``profile_notice``, ``can_open_profile``, ``settings.director``,
``settings.director_name``, ``settings.surveillance_rounding``; ``save_settings`` nhận thêm ``director``,
``surveillance_rounding``. Không bỏ khóa cũ.

Lỗi nghiệp vụ trả body ``{ok: false, error: {title, reason, action}}`` để màn hiện ``alert-error`` inline (design.md
§6) — không để Frappe bật hộp thoại msgprint.
"""

import json

import frappe
from frappe import _
from frappe.utils import strip_html

from tracecore.infection_program import structure
from tracecore.ui import ksnk

SETTINGS = structure.SETTINGS
COMMITTEE = structure.COMMITTEE
SCREEN_SLUG = structure.SCREEN_SLUG
EDITABLE_SETTINGS = (
	"bed_count",
	"facility_level",
	"has_inpatient",
	"surveillance_ratio_beds",
	"surveillance_rounding",  # FEAT-094
	"director",
)
SETTINGS_FIELDS = (*EDITABLE_SETTINGS, "doc_review_months", "ic_department")
PROFILE = "IC Structure Profile"  # FEAT-094


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == SCREEN_SLUG)
	if not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(_("You are not allowed to open the IC structure screen."), frappe.PermissionError)


def _drain_messages():
	messages = [strip_html(str(row.get("message") or "")) for row in frappe.get_message_log()]
	frappe.clear_messages()
	return [message for message in messages if message]


def _block(title, error, action):
	reason = strip_html(str(error)) or title
	frappe.clear_messages()
	return {"ok": False, "error": {"title": title, "reason": reason, "action": action}}


def _status():
	result = structure.compute()
	settings = frappe.get_single(SETTINGS)
	result["settings"] = {field: settings.get(field) for field in SETTINGS_FIELDS}
	result["can_edit_settings"] = bool(frappe.has_permission(SETTINGS, "write"))
	result["can_submit_committee"] = bool(frappe.has_permission(COMMITTEE, "submit"))
	result["can_open_profile"] = bool(frappe.has_permission(PROFILE, "read"))
	result["settings"]["director_name"] = (
		frappe.db.get_value("Employee", settings.director, "employee_name") if settings.director else None
	)
	drafts = frappe.get_list(
		COMMITTEE, filters={"docstatus": 0}, pluck="name", order_by="creation desc", limit_page_length=1
	)
	result["draft_committee"] = drafts[0] if drafts else None
	return result


@frappe.whitelist(methods=["GET"])
def status():
	"""Bảng cơ cấu KSNK cho SCR-47 (FR-M11-01): thành phần Đủ/Thiếu, Hội đồng hiệu lực, mạng lưới theo khoa."""
	_require_screen()
	return _status()


@frappe.whitelist(methods=["POST"])
def save_settings(values):
	"""R10/R01 lưu cài đặt chương trình (UC-40 bước 1); chỉ nhận các trường của khối Cài đặt trên SCR-47."""
	_require_screen()
	if isinstance(values, str):
		values = json.loads(values or "{}")
	doc = frappe.get_single(SETTINGS)
	doc.update({field: values[field] for field in EDITABLE_SETTINGS if field in values})
	if "director" in values and not values["director"]:
		doc.director = None
	frappe.db.savepoint("ksnk_structure_settings")
	try:
		doc.save()
	except frappe.PermissionError:
		frappe.db.rollback(save_point="ksnk_structure_settings")
		raise
	except frappe.ValidationError as error:
		frappe.db.rollback(save_point="ksnk_structure_settings")
		return _block(_("Settings not saved"), error, _("Correct the value and save again."))
	frappe.clear_messages()
	return {"ok": True, "status": _status()}


@frappe.whitelist(methods=["POST"])
def submit_committee(name):
	"""R01 ghi sổ thành phần Hội đồng (UC-40 bước 4; BRU-ICP-002); thiếu khối đại diện → ``warnings``."""
	_require_screen()
	doc = frappe.get_doc(COMMITTEE, name)
	doc.check_permission("submit")
	frappe.db.savepoint("ksnk_structure_committee")
	try:
		doc.submit()
	except frappe.PermissionError:
		frappe.db.rollback(save_point="ksnk_structure_committee")
		raise
	except frappe.ValidationError as error:
		frappe.db.rollback(save_point="ksnk_structure_committee")
		return _block(
			_("Committee not recorded"),
			error,
			_("Open the committee, correct the members and record it again."),
		)
	return {"ok": True, "name": doc.name, "warnings": _drain_messages(), "status": _status()}
