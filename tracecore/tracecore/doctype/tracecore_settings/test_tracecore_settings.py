"""TraceCore Settings: cờ tính năng toàn site (FEAT-014 Task 5, A-06 I7, I15).

Chỉ TC R10 và System Manager ghi; các role TC đọc; đổi cờ ghi Audit Log Update. DocType không Link ERPNext.
"""

import frappe

from tracecore.instrument import catalog
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase

SETTINGS = "TraceCore Settings"
READ_ONLY_ROLES = [f"TC R0{n}" for n in range(1, 10)]


def _save_as(email, value):
	frappe.set_user(email)
	try:
		doc = frappe.get_single(SETTINGS)
		doc.enable_instrument_giai = value
		doc.save()
	finally:
		frappe.set_user("Administrator")


class TestTraceCoreSettings(IsolatedTestCase):
	def test_single_in_tracecore_module_default_off(self):
		meta = frappe.get_meta(SETTINGS)
		self.assertTrue(meta.issingle)
		self.assertEqual(meta.module, "TraceCore")
		field = meta.get_field("enable_instrument_giai")
		self.assertEqual((field.fieldtype, field.default), ("Check", "0"))
		self.assertFalse(catalog.giai_enabled())

	def test_settings_permissions_and_audit(self):
		r02 = make_user("settings-r02@example.com", ["TC R02"])
		r10 = make_user("settings-r10@example.com", ["TC R10"])
		for role in READ_ONLY_ROLES:
			email = make_user(f"settings-{role.lower().replace(' ', '')}@example.com", [role])
			self.assertTrue(frappe.has_permission(SETTINGS, "read", user=email), msg=role)
			self.assertFalse(frappe.has_permission(SETTINGS, "write", user=email), msg=role)
		for email in (r10, make_user("settings-sm@example.com", ["System Manager"])):
			self.assertTrue(frappe.has_permission(SETTINGS, "write", user=email), msg=email)

		# R02 không sửa được cờ
		with self.assertRaises(frappe.PermissionError):
			_save_as(r02, 1)
		self.assertFalse(catalog.giai_enabled())

		# R10 đổi cờ → Audit Log Update có giá trị cũ/mới
		before = frappe.db.count("Audit Log", {"ref_doctype": SETTINGS, "action": "Update"})
		_save_as(r10, 1)
		self.assertTrue(catalog.giai_enabled())
		rows = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": SETTINGS, "action": "Update"},
			fields=["user", "ref_name", "old_value", "new_value"],
			order_by="creation desc, name desc",
		)
		self.assertEqual(len(rows), before + 1)
		row = rows[0]
		self.assertEqual((row.user, row.ref_name), (r10, SETTINGS))
		self.assertEqual(frappe.parse_json(row.new_value), {"enable_instrument_giai": 1})
		self.assertEqual(frappe.parse_json(row.old_value), {"enable_instrument_giai": 0})

		_save_as(r10, 0)
		self.assertFalse(catalog.giai_enabled())

	def test_settings_cannot_be_deleted(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_single(SETTINGS).delete()
