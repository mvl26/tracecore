"""Fixtures Nháp có phiên bản không bị migrate ghi đè (FEAT-067 AC-14; NFR-MAINT-04; D10)."""

import frappe

from tracecore.microbiology import seed
from tracecore.tests.utils import IsolatedTestCase, bru


class TestSeed(IsolatedTestCase):
	@bru("BRU-MDR-001")
	def test_migrate_twice_keeps_hospital_edits_and_drafts(self):
		frappe.db.delete("MDRO Rule Criterion", {"parenttype": "MDRO Rule"})
		frappe.db.delete("MDRO Rule Organism", {"parenttype": "MDRO Rule"})
		frappe.db.delete("MDRO Rule", {})
		created = seed.ensure_mdro_rules()
		self.assertEqual(sorted(created), ["MDR-CRE-V1", "MDR-ESBL-V1", "MDR-MRSA-V1"])
		self.assertEqual(
			set(frappe.get_all("MDRO Rule", filters={"name": ["in", created]}, pluck="docstatus")), {0}
		)
		edited = frappe.get_doc("MDRO Rule", "MDR-ESBL-V1")
		edited.notes = "Bệnh viện sửa"
		edited.save(ignore_permissions=True)
		frappe.get_doc("MDRO Rule", "MDR-CRE-V1").submit()
		self.assertEqual(seed.ensure_mdro_rules(), [])
		self.assertEqual(frappe.db.get_value("MDRO Rule", "MDR-ESBL-V1", "notes"), "Bệnh viện sửa")
		self.assertEqual(frappe.db.get_value("MDRO Rule", "MDR-CRE-V1", "docstatus"), 1)
		self.assertEqual(frappe.db.count("MDRO Rule"), 3)

	def test_organisms_are_inserted_once(self):
		seed.ensure_organisms()
		frappe.db.set_value("Organism", "kpn", "organism_name", "K. pneumoniae (bệnh viện)")
		self.assertEqual(seed.ensure_organisms(), [])
		self.assertEqual(frappe.db.get_value("Organism", "kpn", "organism_name"), "K. pneumoniae (bệnh viện)")
