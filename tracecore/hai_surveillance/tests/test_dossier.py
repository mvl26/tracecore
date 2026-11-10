"""Phần "giám sát NKBV, NKVM" của gói hồ sơ KSNK: danh sách mã BN che (FEAT-074; FR-M9-30.1; BRU-RPT-002; A-152 Q3)."""

import frappe

from tracecore.core import dossier as core_dossier
from tracecore.hai_surveillance import dossier
from tracecore.tests.utils import IsolatedTestCase, bru

CTX = ("2026-01", "2026-02")


def insert(doctype, **values):
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.db_insert()
	return doc


class TestHaiDossier(IsolatedTestCase):
	@bru("BRU-RPT-002", "BRU-HAI-005")
	def test_confirmed_cases_in_range_with_masked_codes(self):
		ctx = core_dossier.context(*CTX)
		inside = insert(
			"HAI Case",
			status="Confirmed",
			docstatus=1,
			onset_date="2026-02-03",
			def_code="VAP",
			patient_code_masked="***5678",
		)
		insert(
			"HAI Case",
			status="Suspected",
			docstatus=0,
			onset_date="2026-02-04",
			patient_code_masked="***1111",
		)
		insert(
			"HAI Case",
			status="Confirmed",
			docstatus=1,
			onset_date="2026-04-01",
			patient_code_masked="***2222",
		)
		rows = dossier.case_rows(ctx)
		self.assertEqual([row.name for row in rows], [inside.name])
		cases, ssi = dossier.register()
		self.assertEqual(core_dossier.check_rows(cases, rows), rows)
		self.assertFalse(cases.in_pdf)
		self.assertNotIn("patient_code", {item.field for item in cases.fields + ssi.fields})

	def test_ssi_in_range(self):
		ctx = core_dossier.context(*CTX)
		inside = insert(
			"Surgical Surveillance",
			surgery_date="2026-01-15",
			outcome="No SSI",
			patient_code_masked="***9012",
		)
		insert("Surgical Surveillance", surgery_date="2025-12-31", patient_code_masked="***3333")
		self.assertEqual([row.name for row in dossier.ssi_rows(ctx)], [inside.name])
