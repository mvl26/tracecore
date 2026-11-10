"""Dữ liệu test M15 (FEAT-070): mức nguy cơ, vùng, ngưỡng, kế hoạch, mẫu, phiếu VSMT/hạ tầng."""

import frappe
from frappe.utils import today

from tracecore.compliance_audit.tests import factories as af
from tracecore.tests import factories

R01, R02, R11, R12, R13 = "TC R01", "TC R02", "TC R11", "TC R12", "TC R13"


def make_level(name="T Rất cao", minimum=4, high=1, order=40):
	if frappe.db.exists("Environment Risk Level", name):
		frappe.db.set_value(
			"Environment Risk Level",
			name,
			{"min_audits_per_month": minimum, "is_high_risk": high, "sort_order": order, "disabled": 0},
		)
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "Environment Risk Level",
				"risk_name": name,
				"min_audits_per_month": minimum,
				"is_high_risk": high,
				"sort_order": order,
				"legal_ref": "QD 3916/QD-BYT",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_zone(department, area="Phòng mổ T1", level=None, party="Department", supplier=None, **values):
	return frappe.get_doc(
		{
			"doctype": "Environment Zone",
			"department": department,
			"area_name": area,
			"risk_level": make_level() if level is None else level,
			"responsible_party": party,
			"supplier": supplier,
			**values,
		}
	).insert(ignore_permissions=True)


def make_limit(
	code="T-PM-KK",
	value=10,
	sample_type="Air",
	method="Culture",
	effective_from="2026-01-01",
	submit=True,
	**values,
):
	doc = frappe.get_doc(
		{
			"doctype": "Environmental Limit",
			"limit_code": code,
			"title": f"Limit {code}",
			"sample_type": sample_type,
			"method": method,
			"parameter": "Total aerobic count",
			"limit_value": value,
			"unit": "CFU/m3",
			"legal_ref": "Draft - expert review",
			"effective_from": effective_from,
			**values,
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def make_sample(zone, value, code="T-PM-KK", sampled_on=None, submit=True, **values):
	doc = frappe.get_doc(
		{
			"doctype": "Environmental Sample",
			"environment_zone": zone,
			"sample_type": values.pop("sample_type", "Air"),
			"method": values.pop("method", "Culture"),
			"limit_code": code,
			"sampled_on": sampled_on or today(),
			"result_value": value,
			**values,
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def make_env_template(code="T-VSMT", audit_type="Environmental Hygiene", submit=True, **values):
	values.setdefault("effective_from", "2026-01-01")
	return af.make_template(
		code,
		submit=submit,
		audit_type=audit_type,
		title=f"Template {code}",
		items=(
			("ENV-01", "Cleaning", "Surface is clean", 1, 1),
			("ENV-02", "Cleaning", "Right chemical", 1, 0),
		),
		**values,
	)


def make_infra_template(code="T-INFRA-VENT", category="Ventilation", interval=180, submit=True):
	return make_env_template(
		code,
		audit_type="Infrastructure",
		submit=submit,
		infra_category=category,
		inspection_interval_days=interval,
	)


def make_session(template, department, zone=None, passed=True, audit_date=None, submit=True, **values):
	answer = "Pass" if passed else "Fail"
	doc = frappe.get_doc(
		{
			"doctype": "Audit Session",
			"audit_template": template,
			"department": department,
			"environment_zone": zone,
			"audit_date": audit_date or today(),
			"observer": values.pop("observer", None) or af.make_observer(),
			"answers": [
				{"item_code": "ENV-01", "answer": answer, "note": "" if passed else "Bụi"},
				{"item_code": "ENV-02", "answer": "Pass"},
			],
			**values,
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def make_department(name):
	return factories.make_department(name)
