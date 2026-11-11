"""Kỳ báo cáo tháng `IC Reporting Period` (FEAT-063; FR-M13-11, 11.1; BRU-HAI-002, BRU-RPT-003; A-144 Q1, c, e).

- Tên ``KY-<YYYY>-<MM>`` theo ``month``; chỉ R01 khóa/mở khóa; mở khóa bắt buộc lý do, ghi Audit Log.
- Khóa: đặt ``locked`` cho mọi `Ward Daily Census` của tháng (FEAT-062 chặn sửa bản đã khóa). Kỳ đã khóa còn chặn
  tạo mẫu số mới và tạo/sửa/ghi sổ/hủy `HAI Case` có ngày khởi phát trong kỳ (``ensure_open``).
- Tính `IC Indicator Value` không ở đây: lớp RPC (`tracecore.v1.hai_case`) gọi tiếp engine M9 sau khi khóa, vì M13
  không import M9 (architecture §5.2).
"""

import re

import frappe
from frappe import _
from frappe.utils import add_months, cint, get_last_day, getdate, now_datetime, today

from tracecore.core import audit
from tracecore.core.errors import Block, BlockedError

DOCTYPE = "IC Reporting Period"
CENSUS = "Ward Daily Census"
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
LOCK_ROLE = "TC R01"
SERVICE_FLAG = "tc_period"


def blocked(code, title, reason, action, **extra):
	return BlockedError(Block(code, title, reason, action, **extra))


def check_month(month) -> str:
	if not isinstance(month, str) or not MONTH.match(month):
		raise blocked(
			"HAI_PERIOD_INVALID",
			_("Period not valid"),
			_("The period {0} is not a month in the form YYYY-MM.").format(month or "-"),
			_("Choose a month, for example 2026-10."),
		)
	return month


def period_name(month) -> str:
	return f"KY-{check_month(month)}"


def month_of(day) -> str:
	return getdate(day).strftime("%Y-%m")


def bounds(month):
	start = getdate(f"{check_month(month)}-01")
	return start, get_last_day(start)


def is_locked(month) -> bool:
	return bool(cint(frappe.db.get_value(DOCTYPE, {"month": month}, "locked")))


def locked_error(month, doctype=None, name=None):
	return blocked(
		"HAI_PERIOD_LOCKED",
		_("Reporting period locked"),
		_("The reporting period {0} is locked.").format(period_name(month)),
		_("Ask the head of infection control to unlock the period with a reason."),
		object_type=doctype,
		object_name=name,
	)


def ensure_open(day, doctype=None, name=None):
	"""Chặn ghi dữ liệu thuộc kỳ đã khóa (FR-M13-11)."""
	if not day:
		return
	month = month_of(day)
	if is_locked(month):
		raise locked_error(month, doctype, name)


def _require_r01():
	if frappe.session.user != "Administrator" and LOCK_ROLE not in frappe.get_roles():
		raise frappe.PermissionError(
			_("Only the head of infection control (R01) can lock or unlock a period.")
		)


def _reason(reason) -> str:
	text = " ".join(str(reason or "").split())
	if not text:
		raise blocked(
			"HAI_CASE_REASON_REQUIRED",
			_("Reason is required"),
			_("A reason is required to unlock a reporting period."),
			_("Enter why the period must be unlocked."),
		)
	return text


def _doc(month):
	name = frappe.db.get_value(DOCTYPE, {"month": month}, "name")
	if name:
		return frappe.get_doc(DOCTYPE, name)
	return frappe.get_doc({"doctype": DOCTYPE, "month": month})


def _save(doc):
	doc.flags[SERVICE_FLAG] = True
	doc.flags.ignore_permissions = True
	doc.save()
	return doc


def _set_census(month, locked):
	start, end = bounds(month)
	frappe.db.sql(
		f"update `tab{CENSUS}` set locked=%s where census_date between %s and %s",  # nosec B608 - hằng tên bảng
		(1 if locked else 0, start, end),
	)


def lock(month):
	"""R01 khóa kỳ (gọi lại khi đã khóa thì giữ nguyên); trả doc kỳ."""
	_require_r01()
	check_month(month)
	if getdate(f"{month}-01") > getdate(today()):
		raise blocked(
			"HAI_PERIOD_INVALID",
			_("Period not valid"),
			_("The period {0} has not started yet.").format(period_name(month)),
			_("Choose the current or an earlier month."),
		)
	doc = _doc(month)
	if cint(doc.locked):
		return doc
	doc.update({"locked": 1, "locked_by": frappe.session.user, "locked_on": now_datetime()})
	_save(doc)
	_set_census(month, True)
	audit.log("Update", DOCTYPE, doc.name, old={"locked": 0}, new={"locked": 1})
	return doc


def unlock(month, reason):
	"""R01 mở khóa có lý do (Audit Log); mẫu số của tháng sửa được lại."""
	_require_r01()
	check_month(month)
	text = _reason(reason)
	doc = _doc(month)
	if doc.is_new() or not cint(doc.locked):
		return doc
	doc.update(
		{
			"locked": 0,
			"unlock_count": cint(doc.unlock_count) + 1,
			"unlocked_by": frappe.session.user,
			"unlocked_on": now_datetime(),
			"unlock_reason": text,
		}
	)
	_save(doc)
	_set_census(month, False)
	audit.log("Override", DOCTYPE, doc.name, old={"locked": 1}, new={"locked": 0}, reason=text)
	return doc


def validate(doc):
	check_month(doc.month)
	if not doc.flags.get(SERVICE_FLAG):
		frappe.throw(_("Use Lock period / Unlock period to change a reporting period."))


def on_trash(doc):
	frappe.throw(_("A reporting period is never deleted."))


# --- danh sách kỳ cho SCR-56 ----------------------------------------------------------------------------------------


def recent_months(count=6, until=None):
	month = month_of(until or today())
	months = [month]
	for _step in range(count - 1):
		months.append(month_of(add_months(getdate(f"{months[-1]}-01"), -1)))
	return months


def _missing_wards(month):
	"""Số khoa nội trú chưa có đủ mẫu số các ngày đã qua của tháng (chỉ để nhắc trước khi khóa)."""
	start, end = bounds(month)
	end = min(end, getdate(today()))
	if end < start:
		return 0
	expected = (end - start).days + 1
	wards = frappe.get_all(
		"Department", filters={"tc_inpatient": 1, "disabled": 0, "is_group": 0}, pluck="name"
	)
	if not wards:
		return 0
	counts = dict(
		frappe.get_all(
			CENSUS,
			filters={"department": ["in", wards], "census_date": ["between", [start, end]]},
			fields=["department", "count(name) as days"],
			group_by="department",
			as_list=True,
		)
	)
	return sum(1 for ward in wards if cint(counts.get(ward)) < expected)


def rows(months=None):
	months = months or recent_months()
	stored = {
		row.month: row
		for row in frappe.get_all(
			DOCTYPE,
			filters={"month": ["in", months]},
			fields=["name", "month", "locked", "locked_by", "locked_on", "unlock_count", "unlock_reason"],
		)
	}
	out = []
	for month in months:
		row = stored.get(month) or {}
		locked = cint(row.get("locked"))
		out.append(
			{
				"name": period_name(month),
				"month": month,
				"locked": locked,
				"locked_by": row.get("locked_by"),
				"locked_by_name": frappe.utils.get_fullname(row.get("locked_by"))
				if row.get("locked_by")
				else None,
				"locked_on": str(row.get("locked_on")) if row.get("locked_on") else None,
				"unlock_count": cint(row.get("unlock_count")),
				"unlock_reason": row.get("unlock_reason"),
				"missing_wards": 0 if locked else _missing_wards(month),
			}
		)
	return out
