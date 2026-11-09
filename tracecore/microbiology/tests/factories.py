"""Dữ liệu test M14 (FEAT-067): loài, quy tắc đa kháng, chủng phân lập."""

import frappe

from tracecore.microbiology import isolates
from tracecore.tests.factories import make_department


def make_organism(code="kpn", name="Klebsiella pneumoniae", group="Enterobacterales"):
	if frappe.db.exists("Organism", code):
		frappe.db.set_value("Organism", code, {"organism_name": name, "organism_group": group, "disabled": 0})
		return code
	return (
		frappe.get_doc(
			{"doctype": "Organism", "organism_code": code, "organism_name": name, "organism_group": group}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_rule(
	code="T-CRE",
	label="CRE",
	organisms=({"organism_group": "Enterobacterales"},),
	criteria=(("MEM", "Carbapenems"), ("IPM", "Carbapenems")),
	condition="Resistant to any",
	min_classes=0,
	submit=True,
	effective_from="2026-01-01",
	**fields,
):
	doc = frappe.get_doc(
		{
			"doctype": "MDRO Rule",
			"rule_code": code,
			"label": label,
			"condition": condition,
			"min_classes": min_classes,
			"precaution_type": "Contact",
			"effective_from": effective_from,
			"organisms": list(organisms),
			"criteria": [{"antibiotic": abx, "antibiotic_class": cls} for abx, cls in criteria],
			**fields,
		}
	).insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def isolate_values(lab="L-001", organism="kpn", patient="BN0001234", collected_on="2026-08-10", **extra):
	return {
		"lab_sample_id": lab,
		"organism": organism,
		"patient_code": patient,
		"birth_year": 1960,
		"sex": "Male",
		"department": extra.pop("department", None) or make_department("Khoa Hồi sức vi sinh"),
		"specimen_type": "Blood",
		"collected_on": collected_on,
		**extra,
	}


def new_isolate(results=(("MEM", "R"),), source=isolates.SOURCE_IMPORT, **values):
	susceptibility = [{"antibiotic": abx, "result": result} for abx, result in results]
	return isolates.create(isolate_values(**values), susceptibility, source=source)
