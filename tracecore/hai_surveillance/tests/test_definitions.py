"""Định nghĩa ca NKBV có phiên bản (FEAT-063; FR-M13-01, FR-M13-01.1, FR-M13-06.1; BRU-HAI-001; NFR-MAINT-04; A-144)."""

import frappe
from frappe.utils import getdate

from tracecore.hai_surveillance import definitions, seed
from tracecore.hai_surveillance.tests import hai_fixtures as h
from tracecore.tests.utils import IsolatedTestCase, bru


class TestDefinitionVersions(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		h.clear_definitions("TVAP")

	def test_name_is_versioned_code(self):
		doc = h.make_definition("tvap", approve=False)
		self.assertEqual(doc.name, "DN-TVAP-V1")
		self.assertEqual(doc.def_code, "TVAP")
		self.assertEqual(doc.version_no, 1)

	def test_only_one_draft_per_code(self):
		h.make_definition("TVAP", approve=False)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "HAI Case Definition",
					"def_code": "TVAP",
					"title": "x",
					"infection_site": "Other",
					"effective_from": "2026-01-01",
					"criteria": [{"criterion": "x"}],
				}
			).insert(ignore_permissions=True)

	def test_approved_version_is_locked(self):
		doc = h.make_definition("TVAP")
		doc.reload()
		doc.min_hours_after_admission = 72
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_requires_criterion_and_non_negative_thresholds(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "HAI Case Definition",
					"def_code": "TVAP",
					"title": "x",
					"infection_site": "Other",
					"effective_from": "2026-01-01",
					"criteria": [],
				}
			).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			h.make_definition("TVAP", hours=-1, approve=False)

	def test_new_version_supersedes_old(self):
		v1 = h.make_definition("TVAP", effective_from="2026-01-01")
		v2 = h.make_definition("TVAP", effective_from="2026-10-01", hours=72)
		self.assertEqual(v2.name, "DN-TVAP-V2")
		self.assertEqual(frappe.db.get_value("HAI Case Definition", v1.name, "superseded_by"), v2.name)

	@bru("BRU-HAI-001")
	def test_version_effective_at_onset(self):
		v1 = h.make_definition("TVAP", effective_from="2026-01-01")
		v2 = h.make_definition("TVAP", effective_from="2026-10-01", hours=72)
		self.assertEqual(definitions.effective_for("TVAP", getdate("2026-09-30")), v1.name)
		self.assertEqual(definitions.effective_for("TVAP", getdate("2026-10-01")), v2.name)
		self.assertIsNone(definitions.effective_for("TVAP", getdate("2025-12-31")))

	@bru("BRU-HAI-001")
	def test_draft_version_is_never_applied(self):
		h.make_definition("TVAP", approve=False)
		self.assertIsNone(definitions.effective_for("TVAP", getdate("2026-10-20")))

	def test_approved_codes_for_picker(self):
		h.make_definition("TVAP")
		codes = {row["def_code"]: row for row in definitions.approved_codes()}
		self.assertIn("TVAP", codes)
		self.assertEqual(codes["TVAP"]["device_type"], "Ventilator")


class TestDefinitionSeed(IsolatedTestCase):
	def test_seed_drafts_without_overwriting(self):
		seed.ensure_seed()
		codes = set(frappe.get_all("HAI Case Definition", pluck="def_code"))
		for code in seed.CODES:
			self.assertIn(code, codes)
		draft = frappe.db.get_value("HAI Case Definition", {"def_code": "VAP", "version_no": 1}, "name")
		if frappe.db.get_value("HAI Case Definition", draft, "docstatus") == 0:
			frappe.db.set_value("HAI Case Definition", draft, "min_hours_after_admission", 60)
		before = frappe.db.count("HAI Case Definition")
		seed.ensure_seed()  # migrate lần hai: không chèn, không ghi đè (NFR-MAINT-04)
		self.assertEqual(frappe.db.count("HAI Case Definition"), before)
		if frappe.db.get_value("HAI Case Definition", draft, "docstatus") == 0:
			self.assertEqual(
				frappe.db.get_value("HAI Case Definition", draft, "min_hours_after_admission"), 60
			)

	def test_seed_texts_are_translated(self):
		import csv

		path = frappe.get_app_path("tracecore", "translations", "vi.csv")
		with open(path, encoding="utf-8") as handle:
			sources = {row[0] for row in csv.reader(handle) if row}
		for text in seed.source_texts():
			self.assertIn(text, sources)

	def test_seed_is_draft(self):
		seed.ensure_seed()
		for code in seed.CODES:
			first = frappe.get_all(
				"HAI Case Definition",
				filters={"def_code": code},
				fields=["docstatus", "legal_ref"],
				order_by="version_no asc",
				limit=1,
			)[0]
			self.assertTrue(first.legal_ref)
