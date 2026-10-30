"""Loại chất thải (FEAT-047, FR-M10-01, .1-.4, BRU-WST-001, BRU-WST-002, A-60 W6-W8)."""

import frappe
from frappe.utils import add_days, today

from tracecore.tests.factories import make_waste_type
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.waste import types


class TestWasteType(IsolatedTestCase):
	@bru("BRU-WST-001")
	def test_group_sets_color_and_color_cannot_be_changed(self):
		expected = {
			"Sharp Infectious": "Yellow",
			"Non-sharp Infectious": "Yellow",
			"High-risk Infectious": "Yellow",
			"Anatomical": "Yellow",
			"Hazardous Non-infectious": "Black",
			"General": "Green",
			"Recyclable": "White",
		}
		self.assertEqual(types.GROUP_COLORS, expected)
		for group, color in expected.items():
			self.assertEqual(make_waste_type(waste_group=group).color_code, color)
		doc = make_waste_type(waste_group="General")
		doc.color_code = "Yellow"
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.color_code, "Green")

	def test_missing_required_fields_are_named(self):
		for field in ("waste_group", "packaging", "max_storage_hours"):
			with self.subTest(field=field):
				doc = make_waste_type()
				doc.set(field, None)
				doc.flags.ignore_links = True
				with self.assertRaises(frappe.ValidationError) as ctx:
					doc.save(ignore_permissions=True)
				self.assertIn(frappe.get_meta("Waste Type").get_label(field), str(ctx.exception))

	def test_weight_and_hours_must_be_positive(self):
		for values in ({"std_weight_kg": 0}, {"max_storage_hours": -1}):
			with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
				make_waste_type(**values)

	@bru("BRU-WST-002")
	def test_storage_hours_other_than_default_need_a_reason(self):
		self.assertEqual((types.DEFAULT_STORAGE_HOURS, types.DEFAULT_COLD_HOURS), (48, 168))
		with self.assertRaises(frappe.ValidationError):
			make_waste_type(max_storage_hours=24)
		with self.assertRaises(frappe.ValidationError):
			make_waste_type(max_storage_cold_hours=100)
		doc = make_waste_type(max_storage_hours=24, storage_override_reason="Hospital rule")
		self.assertEqual(doc.max_storage_hours, 24)
		self.assertEqual(make_waste_type(max_storage_cold_hours=168).max_storage_cold_hours, 168)

	def test_rate_versions_keep_old_rows_and_pick_by_date(self):
		doc = make_waste_type(rates=[{"effective_from": add_days(today(), -10), "rate_per_kg": 1000}])
		doc.append("rates", {"effective_from": today(), "rate_per_kg": 2000})
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
		self.assertEqual(types.rate_on(doc.name, add_days(today(), -5)), 1000)
		self.assertEqual(types.rate_on(doc.name, today()), 2000)
		self.assertEqual(types.rate_on(doc.name, add_days(today(), -30)), 0)

	def test_old_rate_cannot_be_edited_or_removed(self):
		doc = make_waste_type(rates=[{"effective_from": today(), "rate_per_kg": 1000}])
		doc.flags.ignore_links = True
		doc.rates[0].rate_per_kg = 5
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		doc.reload()
		doc.flags.ignore_links = True
		doc.rates = []
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_duplicate_rate_date_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_waste_type(
				rates=[
					{"effective_from": today(), "rate_per_kg": 1},
					{"effective_from": today(), "rate_per_kg": 2},
				]
			)
