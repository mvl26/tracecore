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


# --- nước thải y tế (FEAT-095, A-153) ------------------------------------------------------------------------------

ATTACHMENT = "/private/files/qtnt-ket-qua-test.pdf"


def make_lab(name="T Trung tâm QT Môi trường", vimcerts="VIMCERTS 112", until="2027-06-30"):
	"""Đơn vị quan trắc = Supplier có VIMCERTS (W5)."""
	supplier = factories.make_supplier(name)
	frappe.db.set_value("Supplier", supplier, {"tc_vimcerts_no": vimcerts, "tc_vimcerts_valid_until": until})
	return supplier


def make_point(name="T Đầu ra HTXLNT", point_type="Outlet", user=None, **values):
	return frappe.get_doc(
		{
			"doctype": "Wastewater Point",
			"point_name": name,
			"point_type": point_type,
			"treatment_system": "HTXLNT 300 m3",
			"responsible_user": user,
			**values,
		}
	).insert(ignore_permissions=True)


def rows_for(point, freq="3"):
	"""Dòng GPMT minh họa: pH 6-9, COD ≤ 100, Coliforms ≤ 5000 (tần suất ``freq``), Salmonella chỉ KPH 6 tháng, lưu
	lượng tự động."""
	return [
		{
			"wastewater_point": point,
			"parameter": "pH",
			"unit": "-",
			"min_value": 6,
			"max_value": 9,
			"frequency_months": freq,
		},
		{
			"wastewater_point": point,
			"parameter": "COD",
			"unit": "mg/L",
			"max_value": 100,
			"frequency_months": freq,
		},
		{
			"wastewater_point": point,
			"parameter": "Coliforms",
			"unit": "MPN/100mL",
			"max_value": 5000,
			"frequency_months": freq,
		},
		{
			"wastewater_point": point,
			"parameter": "Salmonella",
			"unit": "Vk/100mL",
			"detect_only": 1,
			"frequency_months": "6",
		},
		{
			"wastewater_point": point,
			"parameter": "Flow",
			"unit": "m3/day",
			"max_value": 300,
			"auto_monitored": 1,
		},
	]


def make_permit(code="T-0154", rows=None, effective_from="2026-01-01", submit=True, **values):
	doc = frappe.get_doc(
		{
			"doctype": "Wastewater Permit",
			"permit_code": code,
			"permit_no": f"{code}/GPMT-UBND",
			"issued_on": "2024-03-15",
			"valid_until": values.pop("valid_until", "2034-03-14"),
			"issuing_authority": "UBND tỉnh (test)",
			"standard": values.pop("standard", "QCVN 28:2010/BTNMT"),
			"standard_column": values.pop("standard_column", "B"),
			"effective_from": effective_from,
			"parameters": rows or [],
			**values,
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def make_monitoring(point, values, sampled_on="2026-10-20", lab=None, submit=True, attach=True, **extra):
	"""``values``: {thông số: số hoặc "KPH"}; dòng kết quả tự nạp theo GPMT rồi điền giá trị."""
	doc = frappe.get_doc(
		{
			"doctype": "Wastewater Monitoring",
			"wastewater_point": point,
			"sampled_on": sampled_on,
			"supplier": lab or make_lab(),
			"report_no": extra.pop("report_no", "2611/KQ-QTMT"),
			"attachment": ATTACHMENT if attach else None,
			**extra,
		}
	)
	from tracecore.environmental_hygiene import wastewater

	wastewater.load_parameters(doc)
	for row in doc.results:
		value = values.get(row.parameter)
		if value == "KPH":
			row.below_detection = 1
		elif value is not None:
			row.value = value
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc
