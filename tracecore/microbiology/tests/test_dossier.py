"""Phần "vi sinh - đa kháng - cách ly" của gói hồ sơ KSNK: mã BN che (FEAT-074; FR-M9-30.1; BRU-RPT-002; A-152 Q3)."""

import frappe

from tracecore.core import dossier as core_dossier
from tracecore.microbiology import dossier
from tracecore.tests.utils import IsolatedTestCase, bru


def insert(doctype, **values):
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.db_insert()
	return doc


class TestMicrobiologyDossier(IsolatedTestCase):
	@bru("BRU-RPT-002")
	def test_mdro_isolates_and_isolation_orders_in_range(self):
		ctx = core_dossier.context("2026-01", "2026-02")
		mdro = insert(
			"Microbiology Isolate",
			lab_sample_id="LAB-DOS-1",
			is_mdro=1,
			collected_on="2026-01-05",
			mdro_flags="CRE",
			patient_code_masked="***4321",
		)
		insert("Microbiology Isolate", lab_sample_id="LAB-DOS-2", is_mdro=0, collected_on="2026-01-06")
		insert("Microbiology Isolate", lab_sample_id="LAB-DOS-3", is_mdro=1, collected_on="2026-05-06")
		order = insert(
			"Isolation Order",
			docstatus=1,
			status="Open",
			start_at="2026-02-28 22:00:00",
			precaution_type="Contact",
			patient_code_masked="***4321",
		)
		insert("Isolation Order", docstatus=0, status="Draft", start_at="2026-02-10 08:00:00")
		isolates, orders = dossier.register()
		rows = dossier.isolate_rows(ctx)
		self.assertEqual([row.name for row in rows], [mdro.name])
		self.assertEqual(core_dossier.check_rows(isolates, rows), rows)
		self.assertEqual([row.name for row in dossier.isolation_rows(ctx)], [order.name])
		self.assertTrue(core_dossier.check_section(orders))
