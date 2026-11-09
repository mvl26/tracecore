"""Chấm điểm phiếu theo phương pháp của mẫu (FEAT-060 AC-6; FR-M12-06, BRU-AUD-005, BRU-AUD-003 phần mẫu số)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.compliance_audit import scoring
from tracecore.tests.utils import bru


def _row(code, answer, weight=1, critical=0, answer_type="Pass/Fail"):
	return frappe._dict(item_code=code, answer=answer, weight=weight, is_critical=critical, answer_type=answer_type)


def _session(method, rows, threshold=None):
	return frappe._dict(scoring_method=method, answers=rows), frappe._dict(pass_threshold=threshold)


class TestWeightedScore(FrappeTestCase):
	def test_score_is_weighted_pass_over_applicable(self):
		doc, tpl = _session("Weighted Score", [_row("A", "Pass", 2), _row("B", "Fail", 1), _row("C", "Pass", 1)])
		self.assertEqual(scoring.score(doc, tpl), (75.0, "Pass", False))

	def test_na_items_leave_the_denominator(self):
		doc, tpl = _session("Weighted Score", [_row("A", "Pass", 3), _row("B", "N/A", 5), _row("C", "Fail", 1)])
		self.assertEqual(scoring.score(doc, tpl)[0], 75.0)

	@bru("BRU-AUD-005")
	def test_critical_fail_fails_regardless_of_score(self):
		rows = [_row(f"P{i}", "Pass", 1) for i in range(19)] + [_row("X", "Fail", 1, critical=1)]
		doc, tpl = _session("Weighted Score", rows)
		self.assertEqual(scoring.score(doc, tpl), (95.0, "Fail", True))

	def test_threshold_decides_without_critical_fail(self):
		rows = [_row("A", "Pass", 4), _row("B", "Fail", 1)]
		self.assertEqual(scoring.score(*_session("Weighted Score", rows, threshold=85))[1], "Fail")
		self.assertEqual(scoring.score(*_session("Weighted Score", rows, threshold=80))[1], "Pass")
		self.assertEqual(scoring.score(*_session("Weighted Score", rows))[1], "Pass")

	def test_nothing_applicable_is_not_scored(self):
		"""Mọi mục Không áp dụng → điểm rỗng, không ghi 0 (BRU-RPT-001)."""
		doc, tpl = _session("Weighted Score", [_row("A", "N/A"), _row("B", None)])
		self.assertEqual(scoring.score(doc, tpl), (None, None, False))

	def test_non_pass_fail_items_are_not_scored(self):
		rows = [_row("A", "Pass", 1), _row("N", "Fail", 9, answer_type="Number")]
		self.assertEqual(scoring.score(*_session("Weighted Score", rows))[0], 100.0)

	def test_rounding_one_decimal(self):
		rows = [_row("A", "Pass"), _row("B", "Pass"), _row("C", "Fail")]
		self.assertEqual(scoring.score(*_session("Weighted Score", rows))[0], 66.7)


class TestAllOrNone(FrappeTestCase):
	def test_one_fail_fails_bundle(self):
		rows = [_row(f"B{i}", "Pass") for i in range(5)] + [_row("B5", "Fail")]
		self.assertEqual(scoring.score(*_session("All or None", rows)), (None, "Fail", False))

	def test_all_applicable_pass_with_na(self):
		rows = [_row("B1", "Pass"), _row("B2", "N/A"), _row("B3", "Pass")]
		self.assertEqual(scoring.score(*_session("All or None", rows)), (None, "Pass", False))

	def test_threshold_ignored(self):
		rows = [_row("B1", "Pass")]
		self.assertEqual(scoring.score(*_session("All or None", rows, threshold=99))[1], "Pass")


class TestRegistry(FrappeTestCase):
	def test_unregistered_method_left_unscored(self):
		doc, tpl = _session("By Opportunity", [])
		self.assertEqual(scoring.score(doc, tpl), (None, None, False))

	def test_register_adds_method(self):
		self.addCleanup(scoring.SCORERS.pop, "Test Method", None)

		@scoring.register("Test Method")
		def _always(doc, template):
			return 50.0, "Fail", False

		self.assertEqual(scoring.score(*_session("Test Method", [])), (50.0, "Fail", False))
