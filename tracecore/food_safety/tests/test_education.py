"""Buổi truyền thông KSNK và báo cáo quý (FEAT-073; FR-M17-05, FR-M17-05.1, FR-M17-01.2; UC-56 bước 5)."""

import frappe
from frappe.utils import add_days, today

from tracecore.core.errors import BlockedError
from tracecore.food_safety import education
from tracecore.food_safety.report.food_safety_and_communication_by_quarter import (
	food_safety_and_communication_by_quarter as report,
)
from tracecore.food_safety.tests import factories as ff
from tracecore.tests.utils import IsolatedTestCase


class TestEducationSession(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete(education.DOCTYPE)
		self.ward = ff.make_department("ATTP Khoa Nhi")
		self.other = ff.make_department("ATTP Khoa Sản")

	def test_r12_records_and_sees_only_own_department(self):
		ff.make_session(self.other, attendees=31)
		r12 = ff.make_dept_user("attp-edu-r12@example.com", ff.R12, self.ward)
		frappe.set_user(r12)
		own = ff.make_session(self.ward)
		self.assertTrue(own.has_permission("write"))
		names = frappe.get_list(education.DOCTYPE, pluck="department")
		self.assertEqual(set(names), {self.ward})
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": education.DOCTYPE,
					"session_date": today(),
					"department": self.other,
					"audience": "Patients",
					"topic": "Hand Hygiene",
					"title": "Khoa khác",
					"attendee_count": 5,
				}
			).insert()

	def test_validation_attendees_date_and_material_type(self):
		with self.assertRaises(BlockedError) as ctx:
			ff.make_session(self.ward, attendees=0)
		self.assertEqual(ctx.exception.block.code, "EDUCATION_COUNT_INVALID")
		with self.assertRaises(BlockedError):
			ff.make_session(self.ward, session_date=add_days(today(), 2))
		regulation = ff.make_material("QD-ATTP-01", doc_type="Regulation")
		with self.assertRaises(BlockedError) as ctx:
			ff.make_session(self.ward, materials=regulation.name)
		self.assertEqual(ctx.exception.block.code, "EDUCATION_MATERIAL_INVALID")
		material = ff.make_material("TL-EDU-01")
		self.assertEqual(ff.make_session(self.ward, materials=material.name).materials, material.name)

	def test_cannot_delete(self):
		doc = ff.make_session(self.ward)
		with self.assertRaises(frappe.ValidationError):
			doc.delete()

	def test_quarter_summary_by_audience_and_topic(self):
		ff.make_session(self.ward, "Patient Families", 26, session_date="2026-11-01")
		ff.make_session(self.ward, "Patient Families", 14, session_date="2026-10-28")
		ff.make_session(self.other, "Patients", 31, session_date="2026-10-20", topic="Patient Counselling")
		ff.make_session(self.other, "Patients", 9, session_date="2026-09-30")
		summary = education.quarter_summary(2026, 4)
		self.assertEqual((summary["sessions"], summary["attendees"]), (3, 71))
		rows = {(r["audience"], r["topic"]): (r["sessions"], r["attendees"]) for r in summary["rows"]}
		self.assertEqual(
			rows,
			{("Patient Families", "Hand Hygiene"): (2, 40), ("Patients", "Patient Counselling"): (1, 31)},
		)
		self.assertEqual(education.quarter_of("2026-11-10"), (2026, 4))

	def test_quarter_report_lists_sessions_and_food_safety_lines(self):
		ff.make_session(self.ward, "Patient Families", 26, session_date="2026-11-01")
		columns, data = report.execute({"year": 2026, "quarter": "Q4"})
		self.assertEqual(
			[c["fieldname"] for c in columns], ["section", "item", "topic", "count", "attendees"]
		)
		communication = [row for row in data if row["section"] == "Communication"]
		self.assertEqual(communication[0]["count"], 1)
		self.assertEqual(communication[0]["attendees"], 26)
		self.assertTrue(any(row["section"] == "Food Safety" for row in data))
