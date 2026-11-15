"""RPC tracecore.v1.lead.* — khu Trưởng khoa KSNK trên Page tc-flow (FEAT-102, A-162, FR-M9-33, SCR-73).

Phiên Desk, chỉ đọc (GET), cho R01, R02 và System Manager. Bảy mục của prototype #17: tổng quan hôm nay, ghi đè cơ số,
thu hồi và sự cố, giá thành tái xử lý, thiết bị và test hằng ngày, nhân sự và chứng chỉ, sổ tiệt khuẩn điện tử. Số liệu
ghép ở `tracecore.v1.lead_board`. Duyệt / từ chối ghi đè không ở đây: trang gọi RPC hiện có
`tracecore.v1.par.override.approve` / `reject` (UC-31, PIN). Không trả mã người bệnh đầy đủ.
"""

import re
from datetime import date as iso_date

import frappe
from frappe import _
from frappe.utils import today

from tracecore.v1 import lead_board
from tracecore.v1._common import BadRequestError, require_any_role
from tracecore.v1.par import override as par_override

HEAD_ROLES = ("TC R01", "TC R02", "System Manager")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _open(doctype):
	"""Vai trò của khu Trưởng khoa và quyền đọc DocType nguồn của mục."""
	require_any_role(*HEAD_ROLES)
	frappe.has_permission(doctype, "read", throw=True)


@frappe.whitelist(methods=["GET"])
def overview():
	"""Tổng quan hôm nay: ``{"ok", "date", "decisions", "kpis", "output", "departments"}``."""
	_open("Set Unit")
	return {"ok": True, **lead_board.overview()}


@frappe.whitelist(methods=["GET"])
def overrides():
	"""Ghi đè cơ số: đề nghị chờ duyệt, bộ đã đạt / sắp đạt cơ số kèm dự báo thay thế, ``can_decide``."""
	_open("Par Override")
	return {
		"ok": True,
		**lead_board.overrides(),
		"can_decide": bool(set(par_override.DECIDE_ROLES) & set(frappe.get_roles())),
	}


@frappe.whitelist(methods=["GET"])
def recalls():
	"""Thu hồi và sự cố: lệnh thu hồi đang mở với từng gói (mã bệnh nhân dạng che), sự cố / NC chưa đóng."""
	_open("Recall Order")
	return {"ok": True, **lead_board.recalls()}


@frappe.whitelist(methods=["GET"])
def costs(month=None):
	"""Giá thành tái xử lý của tháng ``YYYY-MM`` (mặc định tháng này) so với tháng trước."""
	_open("Cost Sheet")
	month = month or today()[:7]
	if not lead_board.month_range(month):
		raise BadRequestError(_("month must be in the form YYYY-MM."))
	return {"ok": True, **lead_board.costs(month)}


@frappe.whitelist(methods=["GET"])
def equipment():
	"""Thiết bị và test hằng ngày: máy chưa thanh lý, test hôm nay, hạn kiểm định, chương trình."""
	_open("Equipment")
	return {"ok": True, "inspection_days": lead_board.INSPECTION_DAYS, **lead_board.equipment()}


@frappe.whitelist(methods=["GET"])
def staff():
	"""Nhân sự, chứng chỉ và năng lực trạm của nhân viên đang làm."""
	_open("Certificate")
	return {"ok": True, **lead_board.staff()}


@frappe.whitelist(methods=["GET"])
def sterilization_log(equipment=None, date=None):
	"""Sổ tiệt khuẩn điện tử của một máy (bỏ trống = mọi máy tiệt khuẩn) trong một ngày (mặc định hôm nay)."""
	_open("Sterilization Load")
	date = date or today()
	if not isinstance(date, str) or not ISO_DATE.match(date):
		raise BadRequestError(_("date must be in the form YYYY-MM-DD."))
	try:
		iso_date.fromisoformat(date)
	except ValueError:
		raise BadRequestError(_("date must be in the form YYYY-MM-DD.")) from None
	if equipment and not frappe.db.exists("Equipment", equipment):
		raise BadRequestError(_("Equipment {0} does not exist.").format(equipment))
	return {"ok": True, **lead_board.sterilization_log(equipment or None, date)}
