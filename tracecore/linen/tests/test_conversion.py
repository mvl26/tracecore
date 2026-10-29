"""Quy đổi số chiếc ↔ kg và lệch 15 % (FEAT-033; FR-M3-01.3, .4; BRU-LIN-002; A-49 L4, L5)."""

import frappe

from tracecore.linen import collection
from tracecore.tests.utils import IsolatedTestCase, bru


class TestConvert(IsolatedTestCase):
	@bru("BRU-LIN-002")
	def test_only_pieces_gives_weight(self):  # FR-M3-01.3
		self.assertEqual(collection.convert(0.5, qty=10), (10, 5.0, "Converted"))

	@bru("BRU-LIN-002")
	def test_only_weight_gives_pieces(self):
		self.assertEqual(collection.convert(0.5, weight_kg=5.2), (10, 5.2, "Converted"))

	def test_weight_is_rounded_to_three_decimals(self):
		self.assertEqual(collection.convert(0.333, qty=7), (7, 2.331, "Converted"))

	def test_pieces_are_rounded_to_whole_numbers(self):
		self.assertEqual(collection.convert(0.4, weight_kg=1.0)[0], 2)

	def test_both_given_are_kept_untouched(self):
		self.assertEqual(collection.convert(0.5, qty=10, weight_kg=9), (10, 9, None))

	def test_neither_given_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			collection.convert(0.5)

	def test_weight_too_small_for_one_piece_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			collection.convert(0.5, weight_kg=0.1)

	def test_non_positive_values_are_rejected(self):
		for kwargs in ({"qty": 0}, {"qty": -2}, {"weight_kg": 0}, {"weight_kg": -1}):
			with self.assertRaises(frappe.ValidationError):
				collection.convert(0.5, **kwargs)


class TestVariance(IsolatedTestCase):
	@bru("BRU-LIN-002")
	def test_variance_is_relative_to_the_converted_weight(self):  # FR-M3-01.4
		self.assertAlmostEqual(collection.variance(0.5, 10, 5.0), 0)
		self.assertAlmostEqual(collection.variance(0.5, 10, 5.5), 0.1)
		self.assertAlmostEqual(collection.variance(0.5, 10, 4.0), 0.2)

	@bru("BRU-LIN-002")
	def test_exactly_fifteen_percent_is_not_over_the_limit(self):
		self.assertFalse(collection.over_tolerance(0.5, 10, 5.75))
		self.assertTrue(collection.over_tolerance(0.5, 10, 5.76))
		self.assertTrue(collection.over_tolerance(0.5, 10, 4.2))


class TestAllocateTotal(IsolatedTestCase):
	def test_total_is_shared_by_standard_weight(self):  # UC-16 A1, A-49 L5
		rows = [(0.5, 10), (1.0, 5)]  # 5 kg + 5 kg chuẩn
		self.assertEqual(collection.allocate_total(10, rows), [5.0, 5.0])

	def test_remainder_goes_to_the_last_row(self):
		weights = collection.allocate_total(10, [(1.0, 1), (1.0, 1), (1.0, 1)])
		self.assertEqual(weights, [3.333, 3.333, 3.334])
		self.assertEqual(round(sum(weights), 3), 10)

	def test_heavier_rows_get_a_larger_share(self):
		weights = collection.allocate_total(9, [(0.5, 2), (2.0, 4)])
		self.assertEqual(weights, [1.0, 8.0])

	def test_empty_rows_or_non_positive_total_are_rejected(self):
		for total, rows in ((10, []), (0, [(1, 1)]), (-3, [(1, 1)])):
			with self.assertRaises(frappe.ValidationError):
				collection.allocate_total(total, rows)
