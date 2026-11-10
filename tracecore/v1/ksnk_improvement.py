"""RPC tracecore.v1.ksnk_improvement.* — khối cải tiến chất lượng & tự đánh giá của SCR-49 (FEAT-072; FR-M11-12,
FR-M11-13, FR-M11-13.1; UC-42 bước 5, 6; A-149).

- ``status`` (GET, chỉ đọc): dự án cải tiến / đề tài của năm (giai đoạn PDCA có chữ), số Hoàn thành và đang làm; tự
  đánh giá chất lượng năm nay cạnh năm trước theo từng mục; mẫu tự đánh giá đang hiệu lực để mở phiếu mới; quyền ghi
  dự án của người gọi. Vai trò như màn ``dao-tao`` (R01, R10, R11, R13, System Manager).
"""

import frappe
from frappe import _
from frappe.utils import nowdate

from tracecore.infection_program import improvement, quality_review, training
from tracecore.ui import ksnk


def _require_screen():
	screen = next(item for item in ksnk.SCREENS if item["slug"] == training.SCREEN_SLUG)
	if not set(frappe.get_roles()) & set(screen["roles"]):
		frappe.throw(
			_("You are not allowed to open the infection control training screen."), frappe.PermissionError
		)


@frappe.whitelist(methods=["GET"])
def status(year=None):
	"""Dữ liệu khối cải tiến & tự đánh giá của SCR-49 cho năm (mặc định năm nay)."""
	year = training.check_year(year or nowdate()[:4])
	_require_screen()
	return {
		"year": year,
		"improvement": improvement.rows(year),
		"self_assessment": quality_review.compare(year),
		"template": quality_review.active_template(),
		"can_edit": bool(frappe.has_permission(improvement.DOCTYPE, "create")),
	}
