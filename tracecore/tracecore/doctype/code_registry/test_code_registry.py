import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import code_registry
from tracecore.tests.factories import make_set_type
from tracecore.tests.utils import bru


class TestCodeRegistry(FrappeTestCase):
	@bru("BRU-ID-006")
	def test_register_and_duplicate_rejected(self):
		code_registry.register("TR-901", "TR-", "Zone Station", "TR-901")
		self.assertTrue(code_registry.is_issued("TR-901"))
		with self.assertRaises(code_registry.CodeAlreadyIssuedError):
			code_registry.register("TR-901", "TR-")

	@bru("BRU-ID-006")
	def test_registry_entry_immutable(self):
		code_registry.register("TR-902", "TR-")
		doc = frappe.get_doc("Code Registry", "TR-902")
		doc.prefix = "XX-"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_registry_entry_can_be_disabled(self):
		code_registry.register("TR-904", "TR-")
		doc = frappe.get_doc("Code Registry", "TR-904")
		doc.status = "Disabled"
		doc.disabled_reason = "Station removed"
		doc.save()
		self.assertIsNotNone(doc.disabled_on)
		self.assertTrue(code_registry.is_issued("TR-904"))

	@bru("BRU-ID-006")
	def test_registry_entry_cannot_be_deleted(self):
		code_registry.register("TR-903", "TR-")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Code Registry", "TR-903")
		self.assertTrue(frappe.db.exists("Code Registry", "TR-903"))

	@bru("BRU-ID-006")
	def test_next_set_id_unique_and_registered(self):
		make_set_type("CRT")
		first = code_registry.next_set_id("CRT")
		second = code_registry.next_set_id("CRT")
		self.assertNotEqual(first, second)
		for code in (first, second):
			self.assertTrue(code.startswith(code_registry.company_prefix() + "CRT"))
			self.assertTrue(code_registry.is_issued(code))
			self.assertEqual(frappe.db.get_value("Code Registry", code, "ref_doctype"), "Set Unit")

	@bru("BRU-ID-001")
	def test_next_set_id_skips_issued_serial(self):
		first = code_registry.next_set_id("CRS")
		serial = int(first[-6:])
		taken = f"{code_registry.company_prefix()}CRS{serial + 1:06d}"
		code_registry.register(taken, "manual")
		second = code_registry.next_set_id("CRS")
		self.assertEqual(int(second[-6:]), serial + 2)
