"""Báo cáo "Hand Hygiene Compliance" và khối vệ sinh tay của SCR-53 (FEAT-061 AC-3, AC-5, AC-10; FR-M12-05, FR-M12-14)."""

import frappe
from frappe.utils import get_first_day, get_last_day, getdate

from tracecore.compliance_audit import board
from tracecore.compliance_audit.report.hand_hygiene_compliance import hand_hygiene_compliance as report
from tracecore.compliance_audit.tests.factories import (
	R12,
	make_dept_user,
	make_observer,
	make_vst_template,
	opportunity,
)
from tracecore.core import indicators as indicator_registry
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

TODAY = getdate()
test_ignore = ["Item", "Batch", "Supplier", "Incident CAPA", "Department", "User", "Employee"]


def many(count, **values):
	return [opportunity(**values) for _ in range(count)]


class HygieneReportCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.dept_a = factories.make_department("Hygiene Rpt Ward A")
		self.dept_b = factories.make_department("Hygiene Rpt Ward B")
		self.template = make_vst_template("T-VST-RPT", min_sample=20)
		self.observer = make_observer(first_name="Hygiene Report Observer")

	def post(self, rows, department=None):
		doc = frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": self.template.name,
				"department": department or self.dept_a,
				"observer": self.observer,
				"opportunities": rows,
			}
		).insert()
		doc.submit()
		return doc

	def filters(self, **values):
		return frappe._dict(
			from_date=get_first_day(TODAY), to_date=get_last_day(TODAY), template_code="T-VST-RPT", **values
		)


class TestHygieneReport(HygieneReportCase):
	@bru("BRU-AUD-002")
	def test_rows_by_department_with_rate_and_sample_label(self):
		self.post(many(6) + many(2, action="Missed"))
		columns, data = report.execute(self.filters())
		self.assertIn("compliance_rate", {column["fieldname"] for column in columns})
		self.assertEqual(len(data), 1)
		row = data[0]
		self.assertEqual(
			(row["group"], row["opportunities"], row["actioned"], row["compliance_rate"]),
			(self.dept_a, 8, 6, 75.0),
		)
		self.assertIn("n = 8", row["result"])
		self.assertIn("insufficient", row["result"].lower())

	def test_group_by_profession_and_moment(self):
		self.post(many(2, role="Doctor", moment="1") + many(2, role="Nurse", moment="3", action="Missed"))
		by_role = {row["group"]: row for row in report.execute(self.filters(group_by="profession"))[1]}
		self.assertEqual(
			(by_role["Doctor"]["compliance_rate"], by_role["Nurse"]["compliance_rate"]), (100.0, 0.0)
		)
		by_moment = {row["group"]: row for row in report.execute(self.filters(group_by="moment"))[1]}
		self.assertEqual(sorted(by_moment), ["1", "3"])

	def test_technique_rate_is_separate(self):
		self.post(
			many(3, technique_ok=1) + many(1, action="Hand Wash", technique_ok=0) + many(1, action="Missed")
		)
		row = report.execute(self.filters())[1][0]
		self.assertEqual((row["compliance_rate"], row["technique_rate"]), (80.0, 75.0))

	def test_date_order_is_checked(self):
		with self.assertRaises(frappe.ValidationError):
			report.execute(frappe._dict(from_date="2026-12-01", to_date="2026-01-01"))

	def test_registered_report_with_roles(self):
		doc = frappe.get_doc("Report", "Hand Hygiene Compliance")
		self.assertEqual(
			(doc.report_type, doc.ref_doctype, doc.is_standard), ("Script Report", "Audit Session", "Yes")
		)
		self.assertIn("TC R12", {row.role for row in doc.roles})

	def test_r12_scope(self):
		self.post(many(3), self.dept_a)
		self.post(many(4), self.dept_b)
		frappe.set_user(make_dept_user("hyg-rpt-r12@example.com", R12, self.dept_a))
		self.assertEqual([row["group"] for row in report.execute(self.filters())[1]], [self.dept_a])


class TestHygieneOnScr53(HygieneReportCase):
	def board(self, code="T-VST-RPT"):
		return board.compliance_board(
			{"from_date": get_first_day(TODAY), "to_date": get_last_day(TODAY), "template_code": code}
		)

	def test_board_carries_hand_hygiene_blocks(self):
		self.post(many(2, role="Doctor", moment="1") + many(2, role="Nurse", moment="2", action="Missed"))
		payload = self.board()
		hygiene = payload["hand_hygiene"]
		self.assertEqual({row["key"] for row in hygiene["profession"]}, {"Doctor", "Nurse"})
		self.assertEqual({row["key"] for row in hygiene["moment"]}, {"1", "2"})
		self.assertEqual(hygiene["total"], 4)
		# thẻ tổng của SCR-53 đếm cơ hội, không đếm phiếu
		self.assertEqual((payload["cards"]["scored"], payload["cards"]["passed"]), (4, 2))

	def test_board_without_hygiene_has_empty_block(self):
		self.assertEqual(self.board("NOPE")["hand_hygiene"]["total"], 0)

	def test_indicators_are_in_the_registry(self):
		registry = indicator_registry.registry()
		self.assertIn("HAND_HYGIENE_RATE", registry)
		self.assertIn("HAND_HYGIENE_TECHNIQUE", registry)
