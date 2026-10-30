"""Linen Collection (FEAT-033; FR-M3-01, .1, .3, .4, .5; UC-16 bước 1-5, E2, E3; BRU-LIN-001, BRU-LIN-002; A-49 L2-L6)."""

import frappe

from tracecore.tests.factories import (
	linen_line,
	make_department,
	make_linen_collection,
	make_linen_type,
)
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Linen Collection"


class LinenCollectionCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.sheet = make_linen_type(std_weight_kg=0.5)
		self.gown = make_linen_type(std_weight_kg=1.0)

	def collect(self, lines, **kwargs):
		return make_linen_collection(lines=lines, **kwargs)


class TestLinenCollectionData(LinenCollectionCase):
	def test_collection_is_named_lnc(self):  # A-49 L2
		self.assertRegex(self.collect([linen_line(self.sheet.name)]).name, r"^LNC-\d{4}-\d{5}$")

	@bru("BRU-LIN-001")
	def test_collection_with_all_fields_is_saved(self):  # FR-M3-01
		doc = self.collect([linen_line(self.sheet.name, 10, 5), linen_line(self.gown.name, 4, 4.2)])
		self.assertEqual((doc.total_qty, doc.total_weight_kg), (14, 9.2))
		self.assertTrue(doc.collected_at)
		self.assertEqual(doc.docstatus, 0)

	@bru("BRU-LIN-001")
	def test_missing_department_is_blocked(self):  # FR-M3-01.1
		with self.assertRaises(frappe.MandatoryError):
			self.collect([linen_line(self.sheet.name)], department=None)

	@bru("BRU-LIN-001")
	def test_missing_deliverer_is_blocked(self):
		with self.assertRaises(frappe.MandatoryError):
			self.collect([linen_line(self.sheet.name)], delivered_by="")

	@bru("BRU-LIN-001")
	def test_collection_without_lines_is_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			self.collect([])

	@bru("BRU-LIN-001")
	def test_missing_linen_type_is_blocked(self):
		with self.assertRaises(frappe.MandatoryError):
			self.collect([{"linen_type": None, "qty": 1, "weight_kg": 1}])

	@bru("BRU-LIN-001")
	def test_line_without_pieces_and_weight_is_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			self.collect([{"linen_type": self.sheet.name}])

	@bru("BRU-LIN-001")
	def test_non_positive_pieces_or_weight_are_blocked(self):
		for qty, weight in ((0, 5), (-1, 5), (10, 0), (10, -2)):
			with self.assertRaises(frappe.ValidationError, msg=(qty, weight)):
				self.collect([linen_line(self.sheet.name, qty, weight)])

	def test_unknown_department_is_rejected(self):
		with self.assertRaises(frappe.LinkValidationError):
			self.collect([linen_line(self.sheet.name)], department="Không có khoa này")

	def test_department_is_kept(self):
		department = make_department()
		self.assertEqual(
			self.collect([linen_line(self.sheet.name)], department=department).department, department
		)

	def test_contaminated_flag_is_kept_per_line(self):  # FR-M3-01
		doc = self.collect(
			[
				linen_line(self.sheet.name, 10, 5, contaminated=1),
				linen_line(self.gown.name, 4, 4, contaminated=0),
			]
		)
		self.assertEqual([row.contaminated for row in doc.lines], [1, 0])

	def test_same_type_may_appear_on_both_flags(self):
		doc = self.collect(
			[
				linen_line(self.sheet.name, 10, 5, contaminated=1),
				linen_line(self.sheet.name, 6, 3, contaminated=0),
			]
		)
		self.assertEqual(doc.total_qty, 16)


class TestLinenCollectionConversion(LinenCollectionCase):
	@bru("BRU-LIN-002")
	def test_only_pieces_fills_weight(self):  # FR-M3-01.3
		doc = self.collect([{"linen_type": self.sheet.name, "qty": 12}])
		self.assertEqual((doc.lines[0].weight_kg, doc.lines[0].weight_source), (6.0, "Converted"))

	@bru("BRU-LIN-002")
	def test_only_weight_fills_pieces(self):
		doc = self.collect([{"linen_type": self.sheet.name, "weight_kg": 6.2}])
		self.assertEqual((doc.lines[0].qty, doc.lines[0].weight_source), (12, "Converted"))

	def test_scale_reading_keeps_its_source(self):
		doc = self.collect([linen_line(self.sheet.name, 10, 5.1, weight_source="Scale")])
		self.assertEqual(doc.lines[0].weight_source, "Scale")

	def test_default_source_is_manual(self):
		self.assertEqual(self.collect([linen_line(self.sheet.name)]).lines[0].weight_source, "Manual")

	@bru("BRU-LIN-002")
	def test_variance_over_fifteen_percent_needs_a_note(self):  # FR-M3-01.4
		with self.assertRaises(frappe.ValidationError):
			self.collect([linen_line(self.sheet.name, 10, 8)])

	@bru("BRU-LIN-002")
	def test_variance_with_note_keeps_the_entered_values(self):
		doc = self.collect([linen_line(self.sheet.name, 10, 8, variance_note="Vải ướt")])
		self.assertEqual((doc.lines[0].qty, doc.lines[0].weight_kg), (10, 8))

	@bru("BRU-LIN-002")
	def test_variance_within_fifteen_percent_needs_no_note(self):
		self.assertEqual(self.collect([linen_line(self.sheet.name, 10, 5.7)]).total_weight_kg, 5.7)

	def test_blank_note_does_not_count(self):
		with self.assertRaises(frappe.ValidationError):
			self.collect([linen_line(self.sheet.name, 10, 8, variance_note="   ")])

	def test_inactive_type_is_rejected(self):  # UC-16 E2
		frappe.db.set_value("Linen Type", self.sheet.name, "is_active", 0)
		with self.assertRaises(frappe.ValidationError):
			self.collect([linen_line(self.sheet.name)])


class TestLinenCollectionLifecycle(LinenCollectionCase):
	def test_submit_makes_the_collection_final(self):
		doc = self.collect([linen_line(self.sheet.name)], submit=True)
		self.assertEqual(doc.docstatus, 1)

	def test_submitted_collection_cannot_be_edited(self):  # UC-16 E3
		doc = self.collect([linen_line(self.sheet.name)], submit=True)
		doc.delivered_by = "Người khác"
		with self.assertRaises(frappe.UpdateAfterSubmitError):
			doc.save()

	def test_cancel_and_amend_replaces_a_signed_collection(self):  # UC-16 E3, A-49 L6
		doc = self.collect([linen_line(self.sheet.name, 10, 5)], submit=True)
		doc.cancel()
		amended = frappe.copy_doc(doc)
		amended.docstatus = 0
		amended.amended_from = doc.name
		amended.lines[0].qty = 11
		amended.lines[0].weight_kg = 5.5
		amended.insert().submit()
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "docstatus"), 2)
		self.assertEqual((amended.docstatus, amended.total_qty), (1, 11))
		self.assertTrue(amended.name.startswith(doc.name))

	def test_collection_cannot_be_deleted(self):
		doc = self.collect([linen_line(self.sheet.name)])
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(DOCTYPE, doc.name, force=True)
