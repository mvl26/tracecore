"""Phần "kết quả giám sát tuân thủ" của gói hồ sơ KSNK (FEAT-074; FR-M9-30; BRU-RPT-002; A-152)."""

import frappe

from tracecore.compliance_audit import dossier
from tracecore.compliance_audit.tests.factories import make_template
from tracecore.core import dossier as core_dossier
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru


def session(template, department, audit_date, result="Pass", score=90):
	doc = frappe.get_doc(
		{
			"doctype": "Audit Session",
			"audit_template": template.name,
			"template_code": template.template_code,
			"template_title": template.title,
			"audit_type": template.audit_type,
			"scoring_method": template.scoring_method,
			"audit_date": audit_date,
			"department": department,
			"result": result,
			"score_pct": score,
			"docstatus": 1,
		}
	)
	doc.db_insert()
	return doc


class TestComplianceDossier(IsolatedTestCase):
	@bru("BRU-RPT-002")
	def test_monthly_aggregates_without_people(self):
		template = make_template(code="T-DOS74")
		department = factories.make_department("Khoa hồ sơ tuân thủ")
		session(template, department, "2026-01-10")
		session(template, department, "2026-01-20", result="Fail", score=50)
		session(template, department, "2026-03-05")  # ngoài dải
		ctx = core_dossier.context("2026-01", "2026-02")
		rows = [row for row in dossier.rows(ctx) if row["template_code"] == "T-DOS74"]
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual((row["month"], row["sessions"], row["passed"], row["scored"]), ("2026-01", 2, 1, 2))
		self.assertEqual(row["pass_rate"], 50.0)
		section = dossier.register()[0]
		self.assertTrue(core_dossier.check_section(section))
		self.assertNotIn("observer_name", {item.field for item in section.fields})
