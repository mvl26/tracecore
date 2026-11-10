"""Phần "kế hoạch, biên bản Hội đồng, đào tạo" của gói hồ sơ KSNK (FEAT-074; FR-M9-30; A-152)."""

import frappe

from tracecore.core import dossier as core_dossier
from tracecore.infection_program import dossier
from tracecore.tests.utils import IsolatedTestCase


def insert(doctype, **values):
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.db_insert()
	return doc


class TestProgramDossier(IsolatedTestCase):
	def test_plan_activities_of_the_years(self):
		plan = insert("IC Annual Plan", name="KH-2031-01", year=2031, docstatus=1, approved_on="2031-01-05")
		insert(
			"IC Plan Activity",
			parent=plan.name,
			parenttype="IC Annual Plan",
			parentfield="activities",
			idx=1,
			activity="Tập huấn vệ sinh tay quý I",
			status="Completed",
		)
		insert("IC Annual Plan", name="KH-2032-01", year=2032, docstatus=0)
		rows = dossier.plan_rows(core_dossier.context("2031-01", "2031-03"))
		self.assertEqual(
			[(row["plan"], row["activity"]) for row in rows], [(plan.name, "Tập huấn vệ sinh tay quý I")]
		)
		self.assertEqual(rows[0]["plan_state"], frappe._("Approved"))

	def test_committee_minutes_in_range(self):
		meeting = insert(
			"IC Committee Meeting",
			name="HH-2031-901",
			meeting_date="2031-02-10",
			docstatus=1,
			minutes="<p>Thông qua kế hoạch</p>",
		)
		insert(
			"IC Resolution",
			parent=meeting.name,
			parenttype="IC Committee Meeting",
			parentfield="resolutions",
			idx=1,
			content="Rà soát quy trình đặt catheter",
			status="Open",
		)
		insert("IC Committee Meeting", name="HH-2031-902", meeting_date="2031-02-11", docstatus=0)
		rows = dossier.meeting_rows(core_dossier.context("2031-01", "2031-03"))
		self.assertEqual([row["name"] for row in rows], [meeting.name])
		self.assertEqual(rows[0]["minutes"], "Thông qua kế hoạch")
		self.assertIn("Rà soát quy trình đặt catheter", rows[0]["resolutions"])

	def test_training_and_sections_are_safe(self):
		self.assertEqual(dossier.training_rows(core_dossier.context("2031-01", "2031-03")), [])
		for section in dossier.register():
			self.assertTrue(core_dossier.check_section(section))
