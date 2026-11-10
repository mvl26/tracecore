"""Mã người bệnh dùng chung KSNK (FEAT-067; ADR-010 mở rộng; NFR-PRIV-01; A-136 Q7)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import patient_code
from tracecore.tests.factories import make_user


class TestPatientCode(FrappeTestCase):
	def test_mask_keeps_only_the_last_four(self):
		self.assertEqual(patient_code.mask(" bn0001234 "), "***1234")
		self.assertEqual(patient_code.mask("1234"), "***")
		self.assertEqual(patient_code.mask(""), "")

	def test_placeholder_is_not_rehashed(self):
		doc = frappe._dict(patient_code="*****", patient_code_hash="old")
		patient_code.apply(doc)
		self.assertEqual(doc.patient_code_hash, "old")

	def test_system_manager_alone_cannot_reveal(self):
		frappe.set_user(make_user("pc-sysman@example.com", ["System Manager"]))
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			patient_code.reveal("Microbiology Isolate", "VS-X", "lý do")

	def test_doctype_without_patient_code_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			patient_code.reveal("Organism", "kpn", "lý do")
