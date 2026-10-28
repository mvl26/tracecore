"""Cost Category và Cost Settings (FEAT-044; FR-M7-01.1; UC-27 E3; architecture A-47 C3, C6, C12)."""

import frappe
from frappe.utils import add_days, today

from tracecore.costing import entry as costing
from tracecore.costing import setup
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase

CATEGORY = "Cost Category"
SETTINGS = "Cost Settings"


class TestCostCategory(IsolatedTestCase):
	def test_twelve_system_categories_exist(self):  # FR-M7-01.1
		self.assertEqual(len(setup.SYSTEM_CATEGORIES), 12)
		for name in setup.SYSTEM_CATEGORIES:
			self.assertEqual(frappe.db.get_value(CATEGORY, name, ["is_system", "is_active"]), (1, 1), name)

	def test_ensure_categories_is_idempotent_and_restores_missing_ones(self):
		self.assertEqual(setup.ensure_categories(), [])
		frappe.db.delete(CATEGORY, {"name": "Steam Cost"})
		self.assertEqual(setup.ensure_categories(), ["Steam Cost"])
		self.assertEqual(setup.ensure_categories(), [])

	def test_system_category_cannot_be_deleted_or_renamed(self):  # FR-M7-01.1
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(CATEGORY, "Electricity Expense", ignore_permissions=True)
		self.assertTrue(frappe.db.exists(CATEGORY, "Electricity Expense"))
		with self.assertRaises(frappe.ValidationError):
			frappe.rename_doc(CATEGORY, "Electricity Expense", "Dien", force=True)
		self.assertTrue(frappe.db.exists(CATEGORY, "Electricity Expense"))

	def test_r09_adds_a_custom_category_which_is_not_system(self):
		user = make_user("cc-r09@example.com", ["TC R09"])
		frappe.set_user(user)
		try:
			doc = frappe.get_doc({"doctype": CATEGORY, "category_name": "Kiểm định ngoài"}).insert()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(doc.name, "Kiểm định ngoài")
		self.assertEqual(doc.is_system, 0)

	def test_no_category_is_deleted_but_a_custom_one_can_be_switched_off(self):
		doc = frappe.get_doc({"doctype": CATEGORY, "category_name": "Tạm dùng"}).insert()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(CATEGORY, doc.name, ignore_permissions=True)
		doc.is_active = 0
		doc.save()
		self.assertEqual(frappe.db.get_value(CATEGORY, doc.name, "is_active"), 0)

	def test_user_cannot_mark_a_category_as_system(self):
		doc = frappe.get_doc({"doctype": CATEGORY, "category_name": "Tự đặt", "is_system": 1}).insert()
		self.assertEqual(doc.is_system, 0)

	def test_category_permissions(self):  # A-47 C12
		expected = {
			"TC R09": {"read": 1, "write": 1},
			"TC R01": {"read": 1, "write": 0},
			"TC R02": {"read": 1, "write": 0},
			"TC R10": {"read": 1, "write": 0},
			"TC R03": {"read": 0, "write": 0},
		}
		for role, flags in expected.items():
			user = make_user(f"cc-{role.split()[-1].lower()}@example.com", [role])
			for ptype, allowed in flags.items():
				self.assertEqual(
					int(bool(frappe.has_permission(CATEGORY, ptype, user=user))),
					allowed,
					msg=f"{role} {ptype}",
				)


class TestCostSettings(IsolatedTestCase):
	def test_locked_until_is_empty_by_default(self):
		self.assertIsNone(costing.locked_until())

	def test_only_r01_changes_the_period_lock(self):  # A-47 C6
		expected = {
			"TC R01": {"read": 1, "write": 1},
			"TC R09": {"read": 1, "write": 0},
			"TC R02": {"read": 0, "write": 0},
			"TC R03": {"read": 0, "write": 0},
		}
		for role, flags in expected.items():
			user = make_user(f"cs-{role.split()[-1].lower()}@example.com", [role])
			for ptype, allowed in flags.items():
				self.assertEqual(
					int(bool(frappe.has_permission(SETTINGS, ptype, user=user))),
					allowed,
					msg=f"{role} {ptype}",
				)

	def test_lock_date_is_stored(self):
		frappe.db.set_single_value(SETTINGS, "locked_until", add_days(today(), -1))
		self.assertEqual(str(costing.locked_until()), str(add_days(today(), -1)))
