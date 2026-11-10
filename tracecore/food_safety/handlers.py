"""Sức khỏe người chế biến thực phẩm (FEAT-073; FR-M17-02, FR-M17-02.1; BRU-FS-001; UC-56 bước 2, E1, E3, A3; A-151 Q4).

- Mỗi lần khám là một phiếu ``Food Handler Health Check`` ghi sổ; chỉ lưu kết luận Đủ/Không đủ và hạn khám kế tiếp,
  **không có trường chẩn đoán hay kết quả xét nghiệm** (BRU-FS-001).
- Người chế biến là nhân viên bệnh viện (``employee``) hoặc người của đơn vị suất ăn thuê ngoài (``supplier`` + họ tên);
  ``handler_key`` gom các lần khám của cùng một người, trạng thái lấy từ phiếu ghi sổ mới nhất.
- Còn ≤ 30 ngày → Sắp đến hạn; quá ``next_due`` → Quá hạn. Job hằng ngày nhắc R11 đúng mốc còn 30 ngày và khi quá hạn,
  mỗi mốc một lần (``reminded_level``). Người Không đủ chỉ hiện nhãn, không chặn giao dịch (UC-56 E3).
"""

import re

import frappe
from frappe import _
from frappe.utils import cstr, date_diff, formatdate, getdate, today

from tracecore.core import notification
from tracecore.core.errors import Block, BlockedError

DOCTYPE = "Food Handler Health Check"
FIT, UNFIT = "Fit", "Unfit"
VALID, DUE_SOON, OVERDUE = "Valid", "Due Soon", "Overdue"
NOTICE_DAYS = 30
DUE_EVENT = "FOOD_HANDLER_CHECK_DUE"
OVERDUE_EVENT = "FOOD_HANDLER_CHECK_OVERDUE"
LEVEL_NONE, LEVEL_DUE, LEVEL_OVERDUE = 0, 1, 2


def _blocked(code, title, reason, action):
	return BlockedError(Block(code, title, reason, action))


def _normal(name):
	return re.sub(r"\s+", " ", cstr(name)).strip().casefold()


def validate(doc):
	"""Gọi từ ``FoodHandlerHealthCheck.validate``."""
	if bool(doc.employee) == bool(doc.supplier):
		raise _blocked(
			"FOOD_HANDLER_UNIT_REQUIRED",
			_("Choose the employee or the vendor"),
			_("A food handler is either hospital kitchen staff or staff of one catering vendor."),
			_("Choose the employee for hospital staff, or the catering vendor for outsourced staff."),
		)
	if doc.employee:
		employee = frappe.db.get_value(
			"Employee", doc.employee, ["employee_name", "department"], as_dict=True
		)
		if employee:
			doc.full_name = employee.employee_name or doc.full_name
			doc.department = doc.department or employee.department
		doc.handler_key = f"E:{doc.employee}"
	else:
		doc.handler_key = f"S:{doc.supplier}:{_normal(doc.full_name)}"
	doc.full_name = re.sub(r"\s+", " ", cstr(doc.full_name)).strip()
	checked_on, next_due = getdate(doc.checked_on), getdate(doc.next_due)
	if checked_on > getdate(today()) or next_due < checked_on:
		raise _blocked(
			"FOOD_HANDLER_DATE_INVALID",
			_("Check dates are not valid"),
			_(
				"Check date {0}, next due {1}: the check cannot be in the future and the next due date cannot be earlier."
			).format(formatdate(checked_on), formatdate(next_due)),
			_("Enter the check date from the health certificate and the next due date after it."),
		)


def state_of(next_due, day=None):
	left = date_diff(getdate(next_due), getdate(day or today()))
	if left < 0:
		return OVERDUE, left
	if left <= NOTICE_DAYS:
		return DUE_SOON, left
	return VALID, left


def _unit_names(rows):
	departments = {row.department for row in rows if not row.supplier and row.department}
	names = dict(
		frappe.get_all(
			"Department",
			filters={"name": ["in", list(departments) or [""]]},
			fields=["name", "department_name"],
			as_list=True,
		)
	)
	return names


def latest(day=None, department=None):
	"""Phiếu ghi sổ mới nhất (khám đến ``day``) của mỗi người chế biến kèm trạng thái tại ``day``."""
	filters = {"docstatus": 1, "checked_on": ["<=", getdate(day or today())]}
	if department:
		filters["department"] = department
	rows = frappe.get_all(
		DOCTYPE,
		filters=filters,
		fields=[
			"name",
			"handler_key",
			"full_name",
			"employee",
			"supplier",
			"supplier_name",
			"department",
			"checked_on",
			"next_due",
			"fit_for_work",
			"reminded_level",
		],
		order_by="checked_on desc, creation desc",
	)
	newest = {}
	for row in rows:
		newest.setdefault(row.handler_key, row)
	names = _unit_names(newest.values())
	result = []
	for row in newest.values():
		state, left = state_of(row.next_due, day)
		unit_key = f"S:{row.supplier}" if row.supplier else f"D:{row.department or ''}"
		unit = (
			row.supplier_name or row.supplier if row.supplier else names.get(row.department, row.department)
		)
		result.append(
			{
				**row,
				"state": state,
				"days_left": left,
				"unit": unit or "",
				"unit_key": unit_key,
			}
		)
	order = {OVERDUE: 0, DUE_SOON: 1, VALID: 2}
	result.sort(key=lambda r: (order[r["state"]], r["days_left"], r["full_name"]))
	return result


def not_eligible(day=None):
	"""Người chế biến không đủ điều kiện: kết luận Không đủ hoặc quá hạn khám."""
	return [row for row in latest(day) if row["fit_for_work"] == UNFIT or row["state"] == OVERDUE]


def overdue_by_unit(day=None):
	groups = {}
	for row in latest(day):
		if row["state"] != OVERDUE:
			continue
		group = groups.setdefault(row["unit_key"], {"unit": row["unit"], "handlers": []})
		group["handlers"].append(row)
	return sorted(groups.values(), key=lambda group: group["unit"])


def _remind(row, event, level, message):
	notification.emit(
		event,
		frappe._dict(doctype=DOCTYPE, name=row["name"]),
		subject=_("Food handler health check: {0}").format(row["full_name"]),
		message=message,
	)
	frappe.db.set_value(DOCTYPE, row["name"], "reminded_level", level, update_modified=False)


def run_daily(day=None):
	"""Scheduler hằng ngày: nhắc R11 còn 30 ngày / quá hạn khám (FR-M17-02); trả số nhắc đã gửi."""
	day = getdate(day or today())
	sent = 0
	for row in latest(day):
		level = row["reminded_level"] or LEVEL_NONE
		if row["state"] == OVERDUE and level < LEVEL_OVERDUE:
			_remind(
				row,
				OVERDUE_EVENT,
				LEVEL_OVERDUE,
				_("The health check of {0} ({1}) was due on {2}.").format(
					row["full_name"], row["unit"], formatdate(row["next_due"])
				),
			)
			sent += 1
		elif row["state"] == DUE_SOON and row["days_left"] == NOTICE_DAYS and level < LEVEL_DUE:
			_remind(
				row,
				DUE_EVENT,
				LEVEL_DUE,
				_("The health check of {0} ({1}) is due on {2}: {3} days left.").format(
					row["full_name"], row["unit"], formatdate(row["next_due"]), row["days_left"]
				),
			)
			sent += 1
	return sent
