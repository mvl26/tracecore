"""Tổng hợp tỷ lệ vệ sinh tay (FEAT-061 AC-3, AC-5, AC-7, AC-10; FR-M12-05, FR-M12-11, FR-M12-14.1; BRU-AUD-002, BRU-RPT-001)."""

import frappe
from frappe.utils import add_months, today

from tracecore.compliance_audit import compliance, hand_hygiene, indicators
from tracecore.compliance_audit.tests.factories import (
	R12,
	make_dept_user,
	make_observer,
	make_template,
	make_vst_template,
	opportunity,
)
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

DOCTYPE = "Audit Session"
test_ignore = ["Item", "Batch", "Supplier", "Incident CAPA", "Department", "User", "Employee"]


def filters(**values):
	return {"from_date": add_months(today(), -1), "to_date": today(), "template_code": "T-VSTA", **values}


class AggregateCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.dept_a = factories.make_department("Hygiene Agg Ward A")
		self.dept_b = factories.make_department("Hygiene Agg Ward B")
		self.template = make_vst_template("T-VSTA", min_sample=10)
		self.observer = make_observer()

	def post(self, rows, department=None, template=None, submit=True, **values):
		doc = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"audit_template": template or self.template.name,
				"department": department or self.dept_a,
				"observer": self.observer,
				"opportunities": rows,
				**values,
			}
		).insert()
		if submit:
			doc.submit()
		return doc


def repeat(count, **values):
	return [opportunity(**values) for _ in range(count)]


class TestHygieneBreakdown(AggregateCase):
	@bru("BRU-AUD-002")
	def test_rate_by_department(self):
		self.post(repeat(30, action="Hand Rub") + repeat(10, action="Missed"))
		self.post(repeat(4, action="Hand Wash") + repeat(4, action="Missed"), department=self.dept_b)
		rows = {row.key: row for row in hand_hygiene.breakdown(filters(), "department")}
		self.assertEqual(
			(rows[self.dept_a].total, rows[self.dept_a].actioned, rows[self.dept_a].rate), (40, 30, 75.0)
		)
		self.assertEqual(rows[self.dept_b].rate, 50.0)
		self.assertEqual(rows[self.dept_b].sample_note, "Insufficient sample")  # n = 8 < min_sample 10
		self.assertEqual(rows[self.dept_a].sample_note, "")

	def test_breakdown_by_profession_moment_and_month(self):
		self.post(
			repeat(4, role="Doctor", moment="1", action="Hand Rub")
			+ repeat(4, role="Nurse", moment="1", action="Missed")
			+ repeat(2, role="Nurse", moment="4", action="Hand Wash", technique_ok=1)
		)
		by_role = {row.key: row for row in hand_hygiene.breakdown(filters(), "profession")}
		self.assertEqual((by_role["Doctor"].rate, by_role["Nurse"].rate), (100.0, 33.3))
		by_moment = {row.key: row for row in hand_hygiene.breakdown(filters(), "moment")}
		self.assertEqual(
			(by_moment["1"].total, by_moment["1"].rate, by_moment["4"].technique_rate), (8, 50.0, 100.0)
		)
		by_month = hand_hygiene.breakdown(filters(), "month")
		self.assertEqual([(row.key, row.total) for row in by_month], [(today()[:7], 10)])

	def test_filters_narrow_the_count(self):
		self.post(repeat(3, role="Doctor", moment="2") + repeat(2, role="Nurse", moment="2", action="Missed"))
		only = hand_hygiene.breakdown(filters(profession="Nurse", moment="2"), "department")
		self.assertEqual([(row.total, row.rate) for row in only], [(2, 0.0)])

	def test_unknown_group_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			hand_hygiene.breakdown(filters(), "person")

	@bru("BRU-RPT-001")
	def test_no_opportunity_is_not_calculated_rather_than_zero(self):
		rows = hand_hygiene.breakdown(filters(department=self.dept_b), "department")
		self.assertEqual(rows, [])
		self.assertEqual(hand_hygiene.rate_label(frappe._dict(rate=None, total=0)), "Not calculated")

	def test_draft_and_cancelled_sessions_are_excluded(self):
		self.post(repeat(6), submit=False)
		cancelled = self.post(repeat(7))
		cancelled.cancel()
		kept = self.post(repeat(2))
		self.assertEqual(
			[(row.key, row.total) for row in hand_hygiene.breakdown(filters(), "department")],
			[(self.dept_a, 2)],
		)
		self.assertTrue(kept.name)

	def test_label_has_one_decimal_and_flags_small_samples(self):
		sep = "," if (frappe.db.get_default("number_format") or "").endswith(",##") else "."
		self.assertEqual(
			hand_hygiene.rate_label(frappe._dict(rate=82.0, total=50, sample_note="")), f"82{sep}0 % (n = 50)"
		)
		small = hand_hygiene.rate_label(frappe._dict(rate=75.0, total=8, sample_note="Insufficient sample"))
		self.assertEqual(small, f"75{sep}0 % (n = 8, insufficient sample)")


class TestHygieneFeedsComplianceViews(AggregateCase):
	def test_compliance_aggregate_counts_opportunities_for_hygiene(self):
		self.post(repeat(41) + repeat(9, action="Missed"))
		scored = make_template("T-VSTA-PPE")
		self.post([], template=scored.name, submit=False)  # phiếu khác loại không lẫn vào
		rows = compliance.aggregate({**filters(), "template_code": "T-VSTA"})
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual((row.sessions, row.passed, row.scored, row.pass_rate), (1, 41, 50, 82.0))
		self.assertEqual(row.sample_note, "")

	def test_compliance_aggregate_flags_small_hygiene_sample(self):
		self.post(repeat(6) + repeat(2, action="Missed"))
		row = compliance.aggregate(filters())[0]
		self.assertEqual((row.scored, row.sample_note), (8, "Insufficient sample"))

	def test_session_count_of_hygiene_is_posted_sessions(self):
		self.post(repeat(3))
		self.post(repeat(3))
		self.assertEqual(compliance.aggregate(filters())[0].sessions, 2)

	def test_indicator_functions_return_numerator_denominator_sample(self):
		self.post(
			repeat(6, action="Hand Rub", technique_ok=1)
			+ repeat(2, action="Hand Wash", technique_ok=0)
			+ repeat(2, action="Missed")
		)
		period = today()[:7]
		functions = indicators.register()
		self.assertEqual(functions["HAND_HYGIENE_RATE"](period, self.dept_a), (8, 10, 10))
		self.assertEqual(functions["HAND_HYGIENE_TECHNIQUE"](period, self.dept_a), (6, 8, 8))
		self.assertEqual(functions["HAND_HYGIENE_RATE"](period, self.dept_b), (0, 0, 0))

	def test_hygiene_sessions_do_not_count_in_pass_rate_of_sessions(self):
		self.post(repeat(4))
		self.assertEqual(indicators.register()["AUDIT_PASS_RATE"](today()[:7], self.dept_a), (0, 0, 0))


class TestHygieneDepartmentScope(AggregateCase):
	def test_r12_sees_only_own_department(self):
		self.post(repeat(4), department=self.dept_a)
		self.post(repeat(6), department=self.dept_b)
		user = make_dept_user("hyg-agg-r12@example.com", R12, self.dept_a)
		frappe.set_user(user)
		self.assertEqual([row.key for row in hand_hygiene.breakdown(filters(), "department")], [self.dept_a])
		self.assertEqual([row.department for row in compliance.aggregate(filters())], [self.dept_a])
