"""Dữ liệu test dùng chung cho M16 (FEAT-071): nhân viên, mẫu theo dõi đã duyệt, ngưỡng giờ, yêu cầu tiêm chủng."""

import frappe
from frappe.utils import add_to_date, now_datetime

from tracecore.occupational_safety import config
from tracecore.tests import factories

SETTINGS = "IC Program Settings"
SHARPS = "Needlestick or Sharps"
SPLASH = "Mucous Membrane Splash"


def employee(first_name, department=None, user=None, designation=None, **fields):
	if user:
		fields["user_id"] = user
	if designation:
		if not frappe.db.exists("Designation", designation):
			frappe.get_doc({"doctype": "Designation", "designation_name": designation}).insert(
				ignore_permissions=True
			)
		fields["designation"] = designation
	return factories.make_employee(first_name=first_name, department=department, **fields).name


def clear_templates(exposure_type=None):
	"""Bỏ mẫu sẵn có trên site test (rollback theo savepoint) để test chỉ thấy mẫu của mình."""
	filters = {"exposure_type": exposure_type} if exposure_type else {}
	for name in frappe.get_all("Exposure Follow-up Template", filters=filters, pluck="name"):
		frappe.delete_doc("Exposure Follow-up Template", name, force=True, ignore_permissions=True)


def template(exposure_type=SHARPS, steps=(("Step 1", 0), ("Step 2", 42), ("Step 3", 180)), approve=True):
	doc = frappe.get_doc(
		{
			"doctype": "Exposure Follow-up Template",
			"exposure_type": exposure_type,
			"steps": [{"step": step, "days_after": days} for step, days in steps],
		}
	).insert(ignore_permissions=True)
	if approve:
		config.approve_template(doc.name)
		doc.reload()
	return doc


def thresholds(report_hours=None, prophylaxis_hours=None):
	frappe.db.set_single_value(SETTINGS, "exposure_report_hours", report_hours)
	frappe.db.set_single_value(SETTINGS, "exposure_prophylaxis_hours", prophylaxis_hours)


def hours_ago(hours):
	return add_to_date(now_datetime(), hours=-hours)


def requirement(vaccine, doses=3, interval=30, booster=0, departments=(), designations=(), approve=True):
	if frappe.db.exists("Immunization Requirement", vaccine):
		frappe.delete_doc("Immunization Requirement", vaccine, force=True, ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "Immunization Requirement",
			"vaccine": vaccine,
			"doses_required": doses,
			"dose_interval_days": interval,
			"booster_interval_days": booster,
			"departments": [{"department": d} for d in departments],
			"designations": [{"designation": d} for d in designations],
		}
	).insert(ignore_permissions=True)
	if approve:
		config.approve_requirement(doc.name)
		doc.reload()
	return doc
