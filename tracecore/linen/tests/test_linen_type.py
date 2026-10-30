"""Linen Type (FEAT-033; FR-M3-02, .1-.3; BRU-LIN-001, BRU-LIN-002; A-49 L2, L10)."""

import frappe

from tracecore.tests.factories import make_department, make_linen_collection, make_linen_type
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

DOCTYPE = "Linen Type"


class TestLinenType(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")  # test trước có thể để lại user khác
		self.addCleanup(frappe.set_user, "Administrator")

	@bru("BRU-LIN-001")
	def test_type_is_saved_with_standard_weight_and_value(self):  # FR-M3-02
		doc = make_linen_type(std_weight_kg=0.75, unit_value=120000)
		self.assertEqual(doc.name, doc.type_name)
		self.assertEqual(doc.std_weight_kg, 0.75)
		self.assertEqual(doc.unit_value, 120000)
		self.assertEqual(doc.is_active, 1)

	@bru("BRU-LIN-001")
	def test_standard_weight_must_be_positive(self):  # FR-M3-02.1
		for weight in (0, -1):
			with self.assertRaises(frappe.ValidationError):
				make_linen_type(std_weight_kg=weight)

	@bru("BRU-LIN-001")
	def test_duplicate_name_is_blocked(self):  # FR-M3-02.3
		make_linen_type("Săng trải giường A")
		with self.assertRaises(frappe.DuplicateEntryError):
			make_linen_type("Săng trải giường A")

	def test_name_is_trimmed_before_the_duplicate_check(self):
		make_linen_type("Áo mổ B")
		with self.assertRaises((frappe.DuplicateEntryError, frappe.ValidationError)):
			make_linen_type("  Áo mổ B ")

	def test_quota_min_cannot_exceed_max(self):
		with self.assertRaises(frappe.ValidationError):
			make_linen_type(quotas=[{"department": make_department(), "min_qty": 10, "max_qty": 5}])

	def test_quota_rejects_negative_numbers(self):
		with self.assertRaises(frappe.ValidationError):
			make_linen_type(quotas=[{"department": make_department(), "min_qty": -1, "max_qty": 5}])

	def test_one_quota_row_per_department(self):
		department = make_department()
		with self.assertRaises(frappe.ValidationError):
			make_linen_type(
				quotas=[
					{"department": department, "min_qty": 1, "max_qty": 5},
					{"department": department, "min_qty": 2, "max_qty": 6},
				]
			)

	def test_quota_is_saved_per_department(self):
		department = make_department()
		doc = make_linen_type(quotas=[{"department": department, "min_qty": 5, "max_qty": 40}])
		self.assertEqual(
			(doc.quotas[0].department, doc.quotas[0].min_qty, doc.quotas[0].max_qty), (department, 5, 40)
		)

	@bru("BRU-LIN-001")
	def test_inactive_type_keeps_history_but_cannot_be_collected(self):  # FR-M3-02.2, UC-16 E2
		doc = make_linen_type()
		collection = make_linen_collection(
			lines=[{"linen_type": doc.name, "qty": 4, "weight_kg": 2}], submit=True
		)
		doc.is_active = 0
		doc.save()
		self.assertEqual(frappe.db.get_value("Linen Collection", collection.name, "docstatus"), 1)
		with self.assertRaises(frappe.ValidationError):
			make_linen_collection(lines=[{"linen_type": doc.name, "qty": 4, "weight_kg": 2}])

	def test_type_cannot_be_deleted(self):
		doc = make_linen_type()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(DOCTYPE, doc.name, force=True)
