"""Phân ca theo khu (FEAT-037, FR-M4-04, UC-20): HRMS Shift Assignment + Custom Field ``tc_zone``.

Xếp nhân viên vào ca của một khu chỉ được khi nhân viên có năng lực còn hiệu lực ở ít nhất một trạm của khu đó trong
các ngày của ca và chứng chỉ bắt buộc của năng lực còn hạn (FR-M4-04.1). Xếp trùng ca do HRMS chặn
(``OverlappingShiftError``, FR-M4-04.3).
"""

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate

from tracecore.hr import competency


def validate_assignment(doc, method=None):
	zone = doc.get("tc_zone")
	if not zone:
		return
	if not frappe.db.get_value("Zone Station", zone, "is_zone"):
		frappe.throw(_("Choose a zone, not a station."))
	stations = frappe.get_all(
		"Zone Station", filters={"parent_zone": zone, "is_zone": 0, "is_active": 1}, pluck="name"
	)
	start = getdate(doc.start_date)
	end = getdate(doc.end_date or doc.start_date)
	if not has_competency_in(doc.employee, stations, start, end):
		frappe.throw(
			_(
				"{0} has no valid station competency in zone {1} for these dates. Grant it in the competency matrix first."
			).format(doc.employee_name or doc.employee, zone)
		)


def has_competency_in(employee, stations, start, end) -> bool:
	"""Có năng lực còn hiệu lực ở một trong `stations` suốt ngày `start`…`end` và chứng chỉ bắt buộc còn hạn vào `start`."""
	if not stations:
		return False
	for row in frappe.get_all(
		"Station Competency",
		filters={
			"employee": employee,
			"station": ["in", stations],
			"is_active": 1,
			"valid_from": ["<=", get_datetime(f"{end} 23:59:59")],
			"valid_until": [">=", get_datetime(f"{start} 00:00:00")],
		},
		pluck="name",
	):
		if not competency.missing_certificate_types(employee, row, at=start):
			return True
	return False
