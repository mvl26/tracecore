"""Phiếu vệ sinh tay theo cơ hội (FEAT-061 AC-3, AC-4, AC-6, AC-7, AC-8; BRU-AUD-002, BRU-AUD-004; FR-M12-05, FR-M12-10,
FR-M12-11)."""

import frappe

from tracecore.compliance_audit import hand_hygiene
from tracecore.compliance_audit.tests.factories import (
	make_observer,
	make_template,
	make_vst_template,
	opportunity,
)
from tracecore.core.errors import BlockedError
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

DOCTYPE = "Audit Session"
test_ignore = ["Item", "Batch", "Supplier", "Incident CAPA", "Department", "User", "Employee"]


class HygieneCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.dept_a = factories.make_department("Hygiene Ward A")
		self.dept_b = factories.make_department("Hygiene Ward B")
		self.template = make_vst_template("T-VST", min_sample=10)
		self.observer = make_observer()
		self.subject = make_observer(first_name="Hygiene Subject")

	def make_session(self, rows, submit=False, **values):
		doc = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"audit_template": values.pop("audit_template", self.template.name),
				"department": values.pop("department", self.dept_a),
				"observer": self.observer,
				"opportunities": rows,
				**values,
			}
		).insert()
		if submit:
			doc.submit()
		return doc

	def assertBlocked(self, code, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		self.assertEqual(caught.exception.block.code, code)


def spread(total, actioned, **values):
	"""`total` cơ hội, `actioned` trong đó có hành động (còn lại Không thực hiện)."""
	return [
		opportunity(action="Hand Rub" if index < actioned else "Missed", moment=str(index % 5 + 1), **values)
		for index in range(total)
	]


class TestHygieneRate(HygieneCase):
	@bru("BRU-AUD-002")
	def test_fifty_opportunities_forty_one_actioned_is_82_percent(self):
		doc = self.make_session(spread(50, 41), submit=True)
		self.assertEqual(doc.score_pct, 82.0)
		self.assertEqual(doc.scoring_method, "By Opportunity")
		self.assertEqual(hand_hygiene.stats(doc.opportunities).rate, 82.0)

	@bru("BRU-AUD-002")
	def test_rate_counts_opportunities_not_people(self):
		same = [opportunity(subject_employee=self.subject, moment=str(n)) for n in range(1, 4)]
		doc = self.make_session([*same, opportunity(action="Missed", subject_employee=self.subject)])
		stats = hand_hygiene.stats(doc.opportunities)
		self.assertEqual((stats.total, stats.actioned), (4, 3))
		self.assertEqual(doc.score_pct, 75.0)

	@bru("BRU-AUD-002")
	def test_technique_rate_excludes_missed_opportunities(self):
		rows = [
			opportunity(action="Hand Rub", technique_ok=1),
			opportunity(action="Hand Rub", technique_ok=1),
			opportunity(action="Hand Wash", technique_ok=1),
			opportunity(action="Hand Wash", technique_ok=0),
			opportunity(action="Missed", technique_ok=1),  # "Không thực hiện" không có kỹ thuật để chấm
		]
		doc = self.make_session(rows)
		stats = hand_hygiene.stats(doc.opportunities)
		self.assertEqual((stats.actioned, stats.technique_ok, stats.technique_rate), (4, 3, 75.0))
		self.assertEqual(doc.opportunities[-1].technique_ok, 0)

	def test_no_opportunities_has_no_rate_not_zero(self):
		doc = self.make_session([])
		self.assertIsNone(doc.score_pct)
		self.assertIsNone(hand_hygiene.stats(doc.opportunities).rate)

	def test_result_follows_pass_threshold_when_set(self):
		make_vst_template("T-VST-TH", pass_threshold=80)
		code = frappe.db.get_value("Audit Template", {"template_code": "T-VST-TH"}, "name")
		self.assertEqual(self.make_session(spread(50, 41), audit_template=code).result, "Pass")
		self.assertEqual(self.make_session(spread(50, 30), audit_template=code).result, "Fail")
		self.assertIsNone(self.make_session(spread(50, 30)).result)  # mẫu không đặt ngưỡng: không kết luận

	def test_profession_and_moment_are_kept_per_opportunity(self):
		doc = self.make_session(
			[opportunity(role="Doctor", moment="3"), opportunity(role="Nurse", moment="5")]
		)
		self.assertEqual(
			[(row.subject_role, row.moment) for row in doc.opportunities], [("Doctor", "3"), ("Nurse", "5")]
		)


class TestHygieneRules(HygieneCase):
	@bru("BRU-AUD-004")
	def test_observed_employee_cannot_be_the_observer(self):
		self.assertBlocked(
			"AUDIT_SELF_OBSERVATION",
			self.make_session,
			[opportunity(), opportunity(subject_employee=self.observer)],
		)
		self.assertEqual(frappe.db.count(DOCTYPE, {"observer": self.observer}), 0)

	def test_moment_must_belong_to_template(self):
		three = make_vst_template("T-VST-3", moments=("1", "2", "3"))
		self.assertBlocked(
			"AUDIT_OPPORTUNITY_INVALID",
			self.make_session,
			[opportunity(moment="4")],
			audit_template=three.name,
		)
		self.assertTrue(self.make_session([opportunity(moment="3")], audit_template=three.name))

	def test_opportunities_only_on_opportunity_templates(self):
		scored = make_template("T-OPP-PPE")
		self.assertBlocked(
			"AUDIT_OPPORTUNITY_INVALID", self.make_session, [opportunity()], audit_template=scored.name
		)

	def test_template_without_moment_items_accepts_moments_one_to_five(self):
		plain = make_template("T-OPP-PLAIN", scoring="By Opportunity")
		doc = self.make_session([opportunity(moment="5")], audit_template=plain.name)
		self.assertEqual(doc.opportunities[0].moment, "5")
		from tracecore.compliance_audit import pda

		row = next(row for row in pda.opportunity_templates() if row["name"] == plain.name)
		self.assertEqual([item["moment"] for item in row["moments"]], ["1", "2", "3", "4", "5"])

	def test_post_needs_at_least_one_opportunity(self):
		doc = self.make_session([])
		with self.assertRaises(BlockedError) as caught:
			doc.submit()
		self.assertEqual(caught.exception.block.code, "AUDIT_NO_OPPORTUNITY")

	def test_moment_of_reads_trailing_digit(self):
		self.assertEqual(hand_hygiene.moment_of("MOMENT-4"), "4")
		self.assertEqual(hand_hygiene.moment_of("TD2"), "2")
		self.assertIsNone(hand_hygiene.moment_of("PNC"))
		self.assertEqual(hand_hygiene.moments(self.template.name), ["1", "2", "3", "4", "5"])


class TestHygieneSample(HygieneCase):
	"""FR-M12-11, AC-7: cỡ mẫu của phiếu theo cơ hội là số cơ hội đã ghi sổ của khoa trong tháng."""

	def test_sample_counts_opportunities_of_the_month(self):
		first = self.make_session(spread(8, 6), submit=True)
		self.assertEqual((first.sample_n, first.sample_flag), (8, 1))
		second = self.make_session(spread(5, 5), submit=True)
		self.assertEqual((second.sample_n, second.sample_flag), (13, 0))

	def test_other_department_has_its_own_sample(self):
		self.make_session(spread(12, 12), submit=True)
		other = self.make_session(spread(3, 3), department=self.dept_b, submit=True)
		self.assertEqual((other.sample_n, other.sample_flag), (3, 1))

	def test_draft_session_does_not_count(self):
		self.make_session(spread(12, 12))
		posted = self.make_session(spread(2, 2), submit=True)
		self.assertEqual(posted.sample_n, 2)
