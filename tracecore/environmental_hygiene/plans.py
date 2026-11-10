"""Kế hoạch lấy mẫu môi trường (FEAT-070; FR-M15-05, .1; UC-54 bước 4, E3; A-148 c).

- Mỗi dòng vùng của `Sampling Plan` có ``next_due``. Scheduler hằng ngày (``run_daily``): đến hạn → ToDo cho người phụ
  trách (một lần, đến khi có mẫu) + thông báo; quá hạn 7 ngày → nhắc R01 một lần (``overdue_notified``).
- Mẫu ghi sổ (không phải mẫu lại) cùng vùng, cùng loại mẫu → ``last_sampled_on``, ``next_due`` = ngày lấy + chu kỳ,
  đóng ToDo của vùng.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, date_diff, getdate, today

from tracecore.core import notification

DOCTYPE = "Sampling Plan"
ROW_DOCTYPE = "Sampling Plan Zone"
DUE_EVENT = "ENV_SAMPLING_DUE"
OVERDUE_EVENT = "ENV_SAMPLE_OVERDUE"
OVERDUE_REMINDER_DAYS = 7
FREQUENCY_MONTHS = {"Monthly": 1, "Quarterly": 3, "Semi-annual": 6, "Annual": 12}
WEEKLY = "Weekly"


def validate(doc):
	seen = set()
	for row in doc.zones:
		if row.environment_zone in seen:
			frappe.throw(_("Row {0}: zone {1} is listed twice.").format(row.idx, row.environment_zone))
		seen.add(row.environment_zone)


def next_after(on, frequency):
	if frequency == WEEKLY:
		return add_days(on, 7)
	return add_months(on, FREQUENCY_MONTHS.get(frequency, 1))


def _rows(on=None, only_due=False):
	filters = {"active": 1}
	plans = frappe.get_all(
		DOCTYPE, filters=filters, fields=["name", "title", "sample_type", "frequency", "assignee"]
	)
	result = []
	for plan in plans:
		row_filters = {"parent": plan.name, "parenttype": DOCTYPE}
		if only_due:
			row_filters["next_due"] = ["<=", getdate(on)]
		for row in frappe.get_all(
			ROW_DOCTYPE,
			filters=row_filters,
			fields=["name", "environment_zone", "environment_zone_name", "next_due", "overdue_notified"],
			order_by="next_due asc",
		):
			result.append((plan, row))
	return result


def overdue(on=None):
	"""Vùng có hạn lấy mẫu đã qua mà chưa có mẫu (FR-M15-05)."""
	on = getdate(on or today())
	return [
		{
			"plan": plan.name,
			"title": plan.title,
			"sample_type": plan.sample_type,
			"zone": row.environment_zone,
			"area_name": row.environment_zone_name,
			"next_due": row.next_due,
			"days_late": date_diff(on, row.next_due),
		}
		for plan, row in _rows(on, only_due=True)
		if getdate(row.next_due) < on
	]


def _user(employee):
	return employee and frappe.db.get_value("Employee", employee, "user_id")


def _task_open(plan, zone):
	return frappe.db.exists(
		"ToDo",
		{
			"reference_type": DOCTYPE,
			"reference_name": plan,
			"status": "Open",
			"description": ["like", f"%[{zone}]%"],
		},
	)


def run_daily(on=None):
	"""Scheduler hằng ngày: giao việc khi đến hạn, nhắc R01 khi quá hạn 7 ngày (FR-M15-05, .1)."""
	on = getdate(on or today())
	for plan, row in _rows(on, only_due=True):
		user = _user(plan.assignee)
		if user and not _task_open(plan.name, row.environment_zone):
			frappe.get_doc(
				{
					"doctype": "ToDo",
					"allocated_to": user,
					"reference_type": DOCTYPE,
					"reference_name": plan.name,
					"date": row.next_due,
					"description": _("Take {0} sample in zone {1} [{2}] — plan {3}, due {4}.").format(
						_(plan.sample_type),
						row.environment_zone_name or row.environment_zone,
						row.environment_zone,
						plan.title,
						frappe.format(row.next_due, "Date"),
					),
				}
			).insert(ignore_permissions=True)
			notification.emit(
				DUE_EVENT,
				frappe._dict(doctype=DOCTYPE, name=plan.name),
				subject=_("Environmental sampling due — {0}").format(row.environment_zone_name),
				users=[user],
			)
		if date_diff(on, row.next_due) >= OVERDUE_REMINDER_DAYS and not row.overdue_notified:
			notification.emit(
				OVERDUE_EVENT,
				frappe._dict(doctype=DOCTYPE, name=plan.name),
				subject=_("Environmental sample overdue {0} days — {1}").format(
					date_diff(on, row.next_due), row.environment_zone_name
				),
			)
			frappe.db.set_value(ROW_DOCTYPE, row.name, "overdue_notified", 1, update_modified=False)


def on_sample(sample):
	"""Mẫu (không phải mẫu lại) đã ghi sổ: đẩy hạn kế tiếp của kế hoạch cùng vùng, cùng loại mẫu; đóng việc."""
	plans = (
		[sample.sampling_plan]
		if sample.sampling_plan
		else frappe.get_all(DOCTYPE, filters={"active": 1, "sample_type": sample.sample_type}, pluck="name")
	)
	for plan in plans:
		frequency = frappe.db.get_value(DOCTYPE, plan, "frequency")
		for row in frappe.get_all(
			ROW_DOCTYPE,
			filters={"parent": plan, "parenttype": DOCTYPE, "environment_zone": sample.environment_zone},
			pluck="name",
		):
			frappe.db.set_value(
				ROW_DOCTYPE,
				row,
				{
					"last_sampled_on": sample.sampled_on,
					"next_due": next_after(sample.sampled_on, frequency),
					"overdue_notified": 0,
				},
				update_modified=False,
			)
			for todo in frappe.get_all(
				"ToDo",
				filters={
					"reference_type": DOCTYPE,
					"reference_name": plan,
					"status": "Open",
					"description": ["like", f"%[{sample.environment_zone}]%"],
				},
				pluck="name",
			):
				frappe.db.set_value("ToDo", todo, "status", "Closed")
