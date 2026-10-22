"""Instrument Group: nhóm dụng cụ có ngưỡng bảo dưỡng theo nhóm (FEAT-014 Task 4; FR-M1-09; A-06 I5, I15)."""

import frappe
from frappe.permissions import get_doc_permissions

from tracecore.tests.factories import make_instrument_group
from tracecore.tests.utils import IsolatedTestCase


class TestInstrumentGroup(IsolatedTestCase):
	def test_threshold_fields_match_instrument(self):
		meta = frappe.get_meta("Instrument Group")
		self.assertEqual(meta.autoname, "field:group_name")
		interval = meta.get_field("maint_interval_cycles")
		self.assertEqual((interval.fieldtype, interval.non_negative), ("Int", 1))
		self.assertEqual(
			meta.get_field("maint_type").options,
			frappe.get_meta("Instrument").get_field("maint_type").options,
		)
		self.assertIn(meta.get_field("description").fieldtype, ("Small Text", "Text"))

	def test_group_threshold_saved_and_audited(self):
		name = make_instrument_group(" IG-LUBE ", interval=30, maint_type="Lubrication", description="Kéo")
		self.assertEqual(name, "IG-LUBE")
		doc = frappe.get_doc("Instrument Group", name)
		self.assertEqual((doc.maint_interval_cycles, doc.maint_type), (30, "Lubrication"))
		self.assertEqual(
			frappe.db.count(
				"Audit Log", {"ref_doctype": "Instrument Group", "ref_name": name, "action": "Create"}
			),
			1,
		)
		doc.maint_interval_cycles = -1
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_group_cannot_be_deleted_or_renamed(self):
		name = make_instrument_group("IG-KEEP")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Instrument Group", name)
		self.assertTrue(frappe.db.exists("Instrument Group", name))
		meta = frappe.get_meta("Instrument Group")
		self.assertFalse(meta.allow_rename)
		self.assertTrue(meta.get_field("group_name").set_only_once)

	def test_permissions(self):
		doc = frappe.get_doc("Instrument Group", make_instrument_group("IG-PERM"))
		for role, can_write in (
			("TC R02", True),
			("TC R10", True),
			("System Manager", True),
			("TC R01", False),
			("TC R04", False),
		):
			perms = [p for p in frappe.get_meta("Instrument Group").permissions if p.role == role]
			self.assertEqual(len(perms), 1, role)
			self.assertTrue(perms[0].read, role)
			self.assertEqual(bool(perms[0].write), can_write, role)
			self.assertFalse(perms[0].delete, role)
		self.assertTrue(get_doc_permissions(doc).get("read"))
